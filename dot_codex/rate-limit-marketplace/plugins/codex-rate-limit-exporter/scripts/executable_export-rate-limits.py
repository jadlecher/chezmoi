#!/usr/bin/env python3
"""Export Codex quota snapshots via OTLP from a plugin hook."""

from __future__ import annotations

import fcntl
import glob
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
DEFAULT_STATE_PATH = Path.home() / ".codex" / "codex-rate-limit-exporter-state.json"
DEFAULT_LOCK_PATH = Path.home() / ".codex" / "codex-rate-limit-exporter-state.lock"
DEFAULT_LOG_FILE = Path.home() / ".codex" / "log" / "codex-rate-limit-exporter.log"
DEFAULT_SERVICE_NAME = "codex-rate-limit-plugin"
DEFAULT_TIMEOUT_SECONDS = 5
METRIC_LOOKBACK_SECONDS = 30 * 24 * 60 * 60
PREFERRED_LIMIT_ID = "codex"


@dataclass
class Snapshot:
    identity: str
    observed_at: float
    plan_type: str
    rate_limit_reached_type: str | None
    primary: dict[str, Any]
    secondary: dict[str, Any]
    session_path: str
    limit_id: str
    reached_reason: str


def _log_local(message: str, *, log_file: Path = DEFAULT_LOG_FILE) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"{ts} {message}\n")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp_name, path)


def _parse_config() -> dict[str, Any]:
    if not DEFAULT_CONFIG_PATH.exists():
        return {}
    with DEFAULT_CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def _parse_headers(value: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for part in value.split(","):
        if "=" not in part:
            continue
        key, _, raw = part.partition("=")
        headers[key.strip()] = raw.strip()
    return headers


def _load_endpoint_and_headers() -> tuple[str, dict[str, str]]:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    headers: dict[str, str] = {}

    env_headers = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").strip()
    if env_headers:
        headers.update(_parse_headers(env_headers))
    elif os.environ.get("AI_CLI_OTEL_INGEST_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['AI_CLI_OTEL_INGEST_TOKEN']}"

    config = _parse_config()
    exporter = ((config.get("otel") or {}).get("exporter") or {}).get("otlp-http") or {}
    if not endpoint:
        endpoint = str(exporter.get("endpoint", "")).strip()
    if not headers:
        raw_headers = exporter.get("headers") or {}
        if isinstance(raw_headers, dict):
            headers = {str(k): str(v) for k, v in raw_headers.items()}

    endpoint = endpoint.rstrip("/")
    for suffix in ("/v1/logs", "/v1/metrics"):
        if endpoint.endswith(suffix):
            endpoint = endpoint[: -len(suffix)]
            break

    if not endpoint:
        raise RuntimeError("OTLP endpoint not configured")
    return endpoint, headers


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
        if response.status >= 300:
            raise RuntimeError(f"unexpected HTTP status {response.status} from {url}")


def _resource_attributes(plan_type: str = "", source_user: str = "") -> list[dict[str, Any]]:
    attrs = [
        {"key": "service.name", "value": {"stringValue": DEFAULT_SERVICE_NAME}},
        {"key": "deployment.environment", "value": {"stringValue": "lab"}},
        {"key": "source_host", "value": {"stringValue": socket.gethostname()}},
        {"key": "source_user", "value": {"stringValue": source_user or os.environ.get("USER", "unknown")}},
    ]
    if plan_type:
        attrs.append({"key": "plan_type", "value": {"stringValue": plan_type}})
    return attrs


def _metric_point(observed_ns: str, value: float, attrs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    point: dict[str, Any] = {"timeUnixNano": observed_ns, "asDouble": float(value)}
    if attrs:
        point["attributes"] = attrs
    return point


def _window_attrs(window: str, plan_type: str, source_user: str, limit_id: str) -> list[dict[str, Any]]:
    return [
        {"key": "window", "value": {"stringValue": window}},
        {"key": "plan_type", "value": {"stringValue": plan_type}},
        {"key": "limit_id", "value": {"stringValue": limit_id}},
        {"key": "source_host", "value": {"stringValue": socket.gethostname()}},
        {"key": "source_user", "value": {"stringValue": source_user}},
    ]


def _root_attrs(plan_type: str, source_user: str, limit_id: str) -> list[dict[str, Any]]:
    return [
        {"key": "plan_type", "value": {"stringValue": plan_type}},
        {"key": "limit_id", "value": {"stringValue": limit_id}},
        {"key": "source_host", "value": {"stringValue": socket.gethostname()}},
        {"key": "source_user", "value": {"stringValue": source_user}},
    ]


def _build_metrics(snapshot: Snapshot) -> dict[str, Any]:
    now = time.time()
    observed_ns = str(int(snapshot.observed_at * 1e9))
    now_ns = str(int(now * 1e9))
    source_user = os.environ.get("USER", "unknown")
    windows = [("5h", snapshot.primary), ("7d", snapshot.secondary)]

    used_points = []
    reset_points = []
    reached_points = []
    for window_name, window in windows:
        attrs = _window_attrs(window_name, snapshot.plan_type, source_user, snapshot.limit_id)
        used_points.append(_metric_point(observed_ns, float(window["used_percent"]), attrs))
        reset_points.append(_metric_point(observed_ns, float(window["resets_at"]), attrs))
        reached_points.append(
            _metric_point(
                observed_ns,
                1.0 if snapshot.rate_limit_reached_type == window_name else 0.0,
                attrs,
            )
        )

    common_attrs = _root_attrs(snapshot.plan_type, source_user, snapshot.limit_id)
    metrics = [
        {
            "name": "codex_cli_rate_limit_used_percent",
            "description": "Most recent observed Codex rate-limit usage percentage.",
            "unit": "",
            "gauge": {"dataPoints": used_points},
        },
        {
            "name": "codex_cli_rate_limit_resets_at_seconds",
            "description": "Unix epoch when the last observed Codex quota window resets.",
            "unit": "s",
            "gauge": {"dataPoints": reset_points},
        },
        {
            "name": "codex_cli_rate_limit_snapshot_timestamp_seconds",
            "description": "Unix epoch of the latest observed Codex quota snapshot.",
            "unit": "s",
            "gauge": {"dataPoints": [_metric_point(observed_ns, snapshot.observed_at, common_attrs)]},
        },
        {
            "name": "codex_cli_rate_limit_export_timestamp_seconds",
            "description": "Unix epoch of the latest successful Codex quota export.",
            "unit": "s",
            "gauge": {"dataPoints": [_metric_point(now_ns, now, common_attrs)]},
        },
        {
            "name": "codex_cli_rate_limit_snapshot_present",
            "description": "Whether the Codex hook found a parseable quota snapshot.",
            "unit": "",
            "gauge": {"dataPoints": [_metric_point(now_ns, 1.0, common_attrs)]},
        },
        {
            "name": "codex_cli_rate_limit_rate_limit_reached",
            "description": "Whether Codex reported a reached rate-limit window in the latest snapshot.",
            "unit": "",
            "gauge": {"dataPoints": reached_points},
        },
    ]

    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": _resource_attributes(snapshot.plan_type, source_user)},
                "scopeMetrics": [
                    {
                        "scope": {"name": DEFAULT_SERVICE_NAME, "version": "1.0.0"},
                        "metrics": metrics,
                    }
                ],
            }
        ]
    }


def _build_log_payload(level: str, message: str, attrs: dict[str, Any] | None = None) -> dict[str, Any]:
    now_ns = str(int(time.time() * 1e9))
    severity_number = {"INFO": 9, "WARN": 13, "ERROR": 17}.get(level, 9)
    attributes = []
    for key, value in (attrs or {}).items():
        if value is None:
            continue
        attributes.append({"key": str(key), "value": {"stringValue": str(value)}})

    return {
        "resourceLogs": [
            {
                "resource": {"attributes": _resource_attributes(source_user=os.environ.get("USER", "unknown"))},
                "scopeLogs": [
                    {
                        "scope": {"name": DEFAULT_SERVICE_NAME, "version": "1.0.0"},
                        "logRecords": [
                            {
                                "timeUnixNano": now_ns,
                                "severityNumber": severity_number,
                                "severityText": level,
                                "body": {"stringValue": message},
                                "attributes": attributes,
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _post_log(level: str, message: str, attrs: dict[str, Any] | None = None) -> None:
    _log_local(f"{level.lower()}: {message}")
    try:
        endpoint, headers = _load_endpoint_and_headers()
        _post_json(f"{endpoint}/v1/logs", _build_log_payload(level, message, attrs), headers)
    except Exception as exc:  # noqa: BLE001
        _log_local(f"log-post-failed: {exc}")


def _read_state() -> dict[str, Any]:
    if not DEFAULT_STATE_PATH.exists():
        return {}
    try:
        return _read_json(DEFAULT_STATE_PATH)
    except Exception:  # noqa: BLE001
        return {}


def _write_state(snapshot: Snapshot) -> None:
    _write_json(
        DEFAULT_STATE_PATH,
        {
            "last_exported_identity": snapshot.identity,
            "last_exported_observed_at": snapshot.observed_at,
            "last_session_path": snapshot.session_path,
            "last_limit_id": snapshot.limit_id,
            "updated_at": time.time(),
        },
    )


def _coerce_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"expected numeric value, got {value!r}")


def _get_last_export_cursor(state: dict[str, Any]) -> tuple[float, str]:
    observed_at = state.get("last_exported_observed_at")
    if observed_at is None:
        observed_at = state.get("last_snapshot_timestamp")
    try:
        last_observed_at = float(observed_at) if observed_at is not None else float("-inf")
    except (TypeError, ValueError):
        last_observed_at = float("-inf")

    identity = str(state.get("last_exported_identity") or state.get("last_export_identity") or "")
    return last_observed_at, identity


def _infer_reached_window(
    rate_limit_reached_type: Any,
    primary_used_percent: float,
    secondary_used_percent: float,
) -> tuple[str | None, str]:
    if rate_limit_reached_type == "primary":
        return "5h", "rate_limit_reached_type"
    if rate_limit_reached_type == "secondary":
        return "7d", "rate_limit_reached_type"
    if primary_used_percent >= 100.0:
        return "5h", "used_percent"
    if secondary_used_percent >= 100.0:
        return "7d", "used_percent"
    return None, "none"


def _build_snapshot(record: dict[str, Any], session_path: str) -> Snapshot | None:
    payload = record.get("payload") or {}
    if payload.get("type") != "token_count":
        return None

    rate_limits = payload.get("rate_limits") or {}
    primary = rate_limits.get("primary")
    secondary = rate_limits.get("secondary")
    if not isinstance(primary, dict) or not isinstance(secondary, dict):
        return None

    observed_at = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timestamp()
    if time.time() - observed_at > METRIC_LOOKBACK_SECONDS:
        return None

    primary_used_percent = _coerce_float(primary["used_percent"])
    secondary_used_percent = _coerce_float(secondary["used_percent"])
    reached_window, reached_reason = _infer_reached_window(
        rate_limits.get("rate_limit_reached_type"),
        primary_used_percent,
        secondary_used_percent,
    )
    limit_id = str(rate_limits.get("limit_id") or "unknown")
    return Snapshot(
        identity=f"{session_path}:{record['timestamp']}",
        observed_at=observed_at,
        plan_type=str(rate_limits.get("plan_type") or "unknown"),
        rate_limit_reached_type=reached_window,
        primary={
            "used_percent": primary_used_percent,
            "resets_at": _coerce_float(primary["resets_at"]),
        },
        secondary={
            "used_percent": secondary_used_percent,
            "resets_at": _coerce_float(secondary["resets_at"]),
        },
        session_path=session_path,
        limit_id=limit_id,
        reached_reason=reached_reason,
    )


def _find_snapshots_since(state: dict[str, Any]) -> list[Snapshot]:
    preferred: list[Snapshot] = []
    fallback: list[Snapshot] = []
    last_observed_at, last_identity = _get_last_export_cursor(state)
    session_paths = sorted(
        glob.glob(str(Path.home() / ".codex" / "sessions" / "**" / "*.jsonl"), recursive=True),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    for session_path in session_paths:
        try:
            with open(session_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    record = json.loads(line)
                    if record.get("type") != "event_msg":
                        continue
                    snapshot = _build_snapshot(record, session_path)
                    if snapshot is None:
                        continue
                    if snapshot.observed_at < last_observed_at:
                        continue
                    if snapshot.observed_at == last_observed_at and snapshot.identity <= last_identity:
                        continue
                    if snapshot.limit_id == PREFERRED_LIMIT_ID:
                        preferred.append(snapshot)
                    else:
                        fallback.append(snapshot)
        except Exception as exc:  # noqa: BLE001
            _post_log("ERROR", "codex quota parse error", {"session_path": session_path, "error": exc})

    snapshots = preferred if preferred else fallback
    snapshots.sort(key=lambda snapshot: (snapshot.observed_at, snapshot.identity))
    if snapshots and snapshots[0].limit_id != PREFERRED_LIMIT_ID:
        _post_log(
            "WARN",
            "codex quota exporter using fallback limit_id",
            {"limit_id": snapshots[0].limit_id, "preferred_limit_id": PREFERRED_LIMIT_ID},
        )
    return snapshots


def _spawn_worker(raw_hook_input: bytes) -> None:
    tmp_fd, tmp_name = tempfile.mkstemp(prefix="codex-rate-limit-hook-", suffix=".json")
    with os.fdopen(tmp_fd, "wb") as handle:
        handle.write(raw_hook_input)
    with DEFAULT_LOG_FILE.open("a", encoding="utf-8") as stderr_handle:
        subprocess.Popen(
            [sys.executable, str(SCRIPT_PATH), "--export-worker", tmp_name],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            close_fds=True,
            start_new_session=True,
        )


def _run_locked_exports(hook_payload: dict[str, Any]) -> int:
    DEFAULT_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DEFAULT_LOCK_PATH.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        state = _read_state()
        snapshots = _find_snapshots_since(state)
        if not snapshots:
            return 0

        endpoint, headers = _load_endpoint_and_headers()
        for snapshot in snapshots:
            _post_json(f"{endpoint}/v1/metrics", _build_metrics(snapshot), headers)
            _write_state(snapshot)
            _post_log(
                "INFO",
                "codex quota export succeeded",
                {
                    "session_path": snapshot.session_path,
                    "identity": snapshot.identity,
                    "hook_event": hook_payload.get("event_name") or hook_payload.get("event") or "unknown",
                    "plan_type": snapshot.plan_type,
                    "limit_id": snapshot.limit_id,
                    "observed_at": snapshot.observed_at,
                    "reached_window": snapshot.rate_limit_reached_type or "none",
                    "reached_reason": snapshot.reached_reason,
                    "five_hour_used_percent": snapshot.primary["used_percent"],
                    "seven_day_used_percent": snapshot.secondary["used_percent"],
                },
            )
    return 0


def run_export_worker(path: str) -> int:
    raw_hook_input = b"{}"
    try:
        raw_hook_input = Path(path).read_bytes()
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    hook_payload = {}
    if raw_hook_input.strip():
        try:
            hook_payload = json.loads(raw_hook_input.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            _post_log("ERROR", "codex hook input parse error", {"error": exc})

    return _run_locked_exports(hook_payload)


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--export-worker":
        try:
            return run_export_worker(sys.argv[2])
        except urllib.error.HTTPError as exc:
            body = exc.read(200).decode("utf-8", errors="replace")
            _post_log("ERROR", "codex quota export HTTP error", {"status": exc.code, "body": body})
            return 1
        except Exception as exc:  # noqa: BLE001
            _post_log("ERROR", "codex quota export error", {"error": exc})
            return 1

    raw_hook_input = sys.stdin.buffer.read()
    try:
        _spawn_worker(raw_hook_input)
    except Exception as exc:  # noqa: BLE001
        _post_log("ERROR", "failed to spawn Codex quota export worker", {"error": exc})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
