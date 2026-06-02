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
DEFAULT_STATE_LOCK_PATH = Path.home() / ".codex" / "codex-rate-limit-exporter-state.lock"
DEFAULT_EXPORT_LOCK_PATH = Path.home() / ".codex" / "codex-rate-limit-exporter-export.lock"
DEFAULT_LOG_FILE = Path.home() / ".codex" / "log" / "codex-rate-limit-exporter.log"
DEFAULT_SERVICE_NAME = "codex-rate-limit-plugin"
DEFAULT_TIMEOUT_SECONDS = 5
FLUSH_TIMEOUT_SECONDS = 2
METRIC_LOOKBACK_SECONDS = 30 * 24 * 60 * 60
ACTIVE_DEBOUNCE_SECONDS = 10
WORKER_IDLE_SECONDS = 20
WORKER_START_GRACE_SECONDS = 5
WORKER_POLL_SECONDS = 1
SESSION_CURSOR_STATE_KEY = "session_cursors"
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


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
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
    now_ns = str(int(now * 1e9))
    source_user = os.environ.get("USER", "unknown")
    windows = [("5h", snapshot.primary), ("7d", snapshot.secondary)]

    used_points = []
    reset_points = []
    reached_points = []
    for window_name, window in windows:
        attrs = _window_attrs(window_name, snapshot.plan_type, source_user, snapshot.limit_id)
        used_points.append(_metric_point(now_ns, float(window["used_percent"]), attrs))
        reset_points.append(_metric_point(now_ns, float(window["resets_at"]), attrs))
        reached_points.append(
            _metric_point(
                now_ns,
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
            "gauge": {"dataPoints": [_metric_point(now_ns, snapshot.observed_at, common_attrs)]},
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
    if level == "INFO":
        return
    try:
        endpoint, headers = _load_endpoint_and_headers()
        _post_json(f"{endpoint}/v1/logs", _build_log_payload(level, message, attrs), headers)
    except Exception as exc:  # noqa: BLE001
        _log_local(f"log-post-failed: {exc}")


def _read_state_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return _read_json(path)
    except Exception:  # noqa: BLE001
        return {}


def _coerce_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"expected numeric value, got {value!r}")


def _coerce_float_or(value: Any, default: float) -> float:
    try:
        return _coerce_float(value)
    except Exception:  # noqa: BLE001
        return default


def _coerce_int_or(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _pruned_session_cursors(state: dict[str, Any], now: float) -> dict[str, dict[str, float | int]]:
    raw_cursors = state.get(SESSION_CURSOR_STATE_KEY)
    if not isinstance(raw_cursors, dict):
        return {}

    cutoff = now - METRIC_LOOKBACK_SECONDS
    cursors: dict[str, dict[str, float | int]] = {}
    for session_path, raw_entry in raw_cursors.items():
        if not isinstance(raw_entry, dict):
            continue
        updated_at = _coerce_float_or(raw_entry.get("updated_at"), 0.0)
        if updated_at < cutoff:
            continue
        cursors[str(session_path)] = {
            "inode": _coerce_int_or(raw_entry.get("inode"), 0),
            "offset": _coerce_int_or(raw_entry.get("offset"), 0),
            "mtime": _coerce_float_or(raw_entry.get("mtime"), 0.0),
            "updated_at": updated_at,
        }
    return cursors


def _prune_state(state: dict[str, Any], now: float) -> dict[str, Any]:
    payload = dict(state)
    payload.pop("post_tool_use", None)

    cursors = _pruned_session_cursors(payload, now)
    if cursors:
        payload[SESSION_CURSOR_STATE_KEY] = cursors
    else:
        payload.pop(SESSION_CURSOR_STATE_KEY, None)

    worker_pid = _coerce_int_or(payload.get("worker_pid"), 0)
    if worker_pid <= 0:
        payload.pop("worker_pid", None)
        payload.pop("worker_started_at", None)
    payload.pop("worker_starting", None)

    return payload


def _write_state_payload(state: dict[str, Any], now: float | None = None) -> None:
    now = time.time() if now is None else now
    payload = _prune_state(state, now)
    _write_json(DEFAULT_STATE_PATH, payload)


def _with_lock(lock_path: Path, callback):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        return callback()


def _read_state_locked() -> dict[str, Any]:
    return _read_state_file(DEFAULT_STATE_PATH)


def _update_state(mutator, *, now: float | None = None) -> Any:
    now = time.time() if now is None else now

    def _inner():
        state = _read_state_locked()
        result = mutator(state, now)
        _write_state_payload(state, now)
        return result

    return _with_lock(DEFAULT_STATE_LOCK_PATH, _inner)


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def _worker_is_healthy(state: dict[str, Any], now: float) -> bool:
    pid = _coerce_int_or(state.get("worker_pid"), 0)
    if pid > 0 and _pid_is_running(pid):
        return True
    starting_at = _coerce_float_or(state.get("worker_starting_at"), 0.0)
    return starting_at > 0 and now - starting_at < WORKER_START_GRACE_SECONDS


def _clear_worker_metadata(state: dict[str, Any]) -> None:
    state.pop("worker_pid", None)
    state.pop("worker_started_at", None)
    state.pop("worker_starting_at", None)


def _record_exported_snapshot(state: dict[str, Any], snapshot: Snapshot, now: float | None = None) -> None:
    state.update(
        {
            "last_exported_identity": snapshot.identity,
            "last_exported_observed_at": snapshot.observed_at,
            "last_session_path": snapshot.session_path,
            "last_limit_id": snapshot.limit_id,
            "updated_at": time.time() if now is None else now,
        }
    )


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


def _snapshot_is_newer(snapshot: Snapshot, observed_at: float, identity: str) -> bool:
    if snapshot.observed_at > observed_at:
        return True
    if snapshot.observed_at < observed_at:
        return False
    return snapshot.identity > identity


def _scan_session_file(
    session_path: str,
    cursor: dict[str, float | int] | None,
    last_observed_at: float,
    last_identity: str,
    now: float,
) -> tuple[dict[str, float | int], Snapshot | None, Snapshot | None]:
    stat_result = os.stat(session_path)
    inode = int(stat_result.st_ino)
    size = int(stat_result.st_size)
    mtime = float(stat_result.st_mtime)

    offset = 0
    if cursor is not None:
        same_inode = _coerce_int_or(cursor.get("inode"), 0) == inode
        previous_offset = _coerce_int_or(cursor.get("offset"), 0)
        previous_mtime = _coerce_float_or(cursor.get("mtime"), 0.0)
        if same_inode and size >= previous_offset and (size != previous_offset or mtime != previous_mtime):
            offset = previous_offset
        elif same_inode and size == previous_offset and mtime == previous_mtime:
            return {
                "inode": inode,
                "offset": size,
                "mtime": mtime,
                "updated_at": now,
            }, None, None

    preferred: Snapshot | None = None
    fallback: Snapshot | None = None
    with open(session_path, "r", encoding="utf-8") as handle:
        if offset > 0:
            handle.seek(offset)
        for line in handle:
            record = json.loads(line)
            if record.get("type") != "event_msg":
                continue
            snapshot = _build_snapshot(record, session_path)
            if snapshot is None or not _snapshot_is_newer(snapshot, last_observed_at, last_identity):
                continue
            if snapshot.limit_id == PREFERRED_LIMIT_ID:
                if preferred is None or _snapshot_is_newer(snapshot, preferred.observed_at, preferred.identity):
                    preferred = snapshot
            elif fallback is None or _snapshot_is_newer(snapshot, fallback.observed_at, fallback.identity):
                fallback = snapshot
        end_offset = handle.tell()

    return {
        "inode": inode,
        "offset": end_offset,
        "mtime": mtime,
        "updated_at": now,
    }, preferred, fallback


def _find_newest_snapshot(state: dict[str, Any], now: float) -> Snapshot | None:
    preferred: Snapshot | None = None
    fallback: Snapshot | None = None
    last_observed_at, last_identity = _get_last_export_cursor(state)
    cursors = _pruned_session_cursors(state, now)

    session_paths = sorted(
        glob.glob(str(Path.home() / ".codex" / "sessions" / "**" / "*.jsonl"), recursive=True),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    seen_paths = set(session_paths)
    for stale_path in list(cursors):
        if stale_path not in seen_paths:
            cursors.pop(stale_path, None)

    for session_path in session_paths:
        cursor = cursors.get(session_path)
        try:
            next_cursor, preferred_candidate, fallback_candidate = _scan_session_file(
                session_path,
                cursor,
                last_observed_at,
                last_identity,
                now,
            )
            cursors[session_path] = next_cursor
        except FileNotFoundError:
            cursors.pop(session_path, None)
            continue
        except Exception as exc:  # noqa: BLE001
            _post_log("ERROR", "codex quota parse error", {"session_path": session_path, "error": exc})
            continue

        if preferred_candidate is not None and (
            preferred is None or _snapshot_is_newer(preferred_candidate, preferred.observed_at, preferred.identity)
        ):
            preferred = preferred_candidate
        if fallback_candidate is not None and (
            fallback is None or _snapshot_is_newer(fallback_candidate, fallback.observed_at, fallback.identity)
        ):
            fallback = fallback_candidate

    state[SESSION_CURSOR_STATE_KEY] = cursors
    newest = preferred or fallback
    if newest is not None and newest.limit_id != PREFERRED_LIMIT_ID:
        _post_log(
            "WARN",
            "codex quota exporter using fallback limit_id",
            {"limit_id": newest.limit_id, "preferred_limit_id": PREFERRED_LIMIT_ID},
        )
    return newest


def _hook_event_name(hook_payload: dict[str, Any]) -> str:
    return str(hook_payload.get("event_name") or hook_payload.get("event") or "unknown")


def _parse_hook_payload(raw_hook_input: bytes) -> dict[str, Any]:
    if not raw_hook_input.strip():
        return {}
    try:
        decoded = json.loads(raw_hook_input.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        _post_log("ERROR", "codex hook input parse error", {"error": exc})
        return {}
    if isinstance(decoded, dict):
        return decoded
    _post_log("WARN", "codex hook input was not an object", {"type": type(decoded).__name__})
    return {}


def _spawn_worker() -> int:
    DEFAULT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    stderr_handle = DEFAULT_LOG_FILE.open("a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT_PATH), "--worker"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            close_fds=True,
            start_new_session=True,
        )
    finally:
        stderr_handle.close()
    return proc.pid


def _export_snapshot(snapshot: Snapshot, event_name: str, *, timeout: int) -> int:
    endpoint, headers = _load_endpoint_and_headers()
    try:
        _post_json(f"{endpoint}/v1/metrics", _build_metrics(snapshot), headers, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read(500).decode("utf-8", errors="replace")
        _post_log(
            "ERROR",
            "codex quota export failed",
            {
                "status": exc.code,
                "error": body or str(exc),
                "identity": snapshot.identity,
                "observed_at": snapshot.observed_at,
                "limit_id": snapshot.limit_id,
                "session_path": snapshot.session_path,
                "event_name": event_name,
            },
        )
        return 1
    except Exception as exc:  # noqa: BLE001
        _post_log(
            "ERROR",
            "codex quota export failed",
            {
                "error": str(exc),
                "identity": snapshot.identity,
                "observed_at": snapshot.observed_at,
                "limit_id": snapshot.limit_id,
                "session_path": snapshot.session_path,
                "event_name": event_name,
            },
        )
        return 1

    _post_log(
        "INFO",
        "codex quota export succeeded",
        {
            "session_path": snapshot.session_path,
            "identity": snapshot.identity,
            "hook_event": event_name,
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


def _run_export_cycle(event_name: str, *, timeout: int) -> int:
    def _inner() -> int:
        now = time.time()
        state = _read_state_locked()
        state["last_scan_started_at"] = now
        state["updated_at"] = now
        snapshot = _find_newest_snapshot(state, now)
        _write_state_payload(state, now)
        if snapshot is None:
            return 0

        rc = _export_snapshot(snapshot, event_name, timeout=timeout)
        finish = time.time()
        if rc == 0:
            def _record(state: dict[str, Any], locked_now: float) -> None:
                _record_exported_snapshot(state, snapshot, finish)
                state["updated_at"] = locked_now
            _update_state(_record, now=finish)
        return rc

    return _with_lock(DEFAULT_EXPORT_LOCK_PATH, _inner)


def _run_post_tool_use(event_name: str) -> int:
    now = time.time()

    def _mark(state: dict[str, Any], locked_now: float) -> bool:
        healthy = _worker_is_healthy(state, locked_now)
        state["last_activity_at"] = locked_now
        state["updated_at"] = locked_now
        if healthy:
            return False
        _clear_worker_metadata(state)
        state["worker_starting_at"] = locked_now
        return True

    should_spawn = _update_state(_mark, now=now)
    if not should_spawn:
        return 0

    try:
        pid = _spawn_worker()
    except Exception as exc:  # noqa: BLE001
        def _clear(state: dict[str, Any], locked_now: float) -> None:
            _clear_worker_metadata(state)
            state["last_activity_at"] = max(_coerce_float_or(state.get("last_activity_at"), 0.0), now)
            state["updated_at"] = locked_now
        _update_state(_clear)
        _post_log("ERROR", "codex quota worker spawn failed", {"error": exc, "event_name": event_name})
        return 0

    def _record_pid(state: dict[str, Any], locked_now: float) -> None:
        state["worker_pid"] = pid
        state["worker_started_at"] = locked_now
        state.pop("worker_starting_at", None)
        state["updated_at"] = locked_now

    _update_state(_record_pid)
    return 0


def _worker_should_exit(state: dict[str, Any], now: float) -> bool:
    last_activity = _coerce_float_or(state.get("last_activity_at"), 0.0)
    last_attempt = _coerce_float_or(state.get("last_worker_attempted_at"), 0.0)
    if last_activity <= 0:
        return True
    if last_activity > last_attempt:
        return False
    return now - last_activity >= WORKER_IDLE_SECONDS


def _worker_sleep_seconds(state: dict[str, Any], now: float) -> float:
    last_activity = _coerce_float_or(state.get("last_activity_at"), 0.0)
    last_attempt = _coerce_float_or(state.get("last_worker_attempted_at"), 0.0)
    if last_activity > last_attempt:
        remaining = ACTIVE_DEBOUNCE_SECONDS - (now - last_attempt)
        return max(float(WORKER_POLL_SECONDS), remaining)
    remaining = WORKER_IDLE_SECONDS - (now - last_activity)
    return max(float(WORKER_POLL_SECONDS), remaining)


def _run_worker() -> int:
    now = time.time()

    def _register(state: dict[str, Any], locked_now: float) -> None:
        state["worker_pid"] = os.getpid()
        state["worker_started_at"] = locked_now
        state.pop("worker_starting_at", None)
        state.setdefault("last_activity_at", locked_now)
        state["updated_at"] = locked_now

    _update_state(_register, now=now)

    try:
        while True:
            def _snapshot_state(state: dict[str, Any], locked_now: float) -> dict[str, float]:
                current_pid = _coerce_int_or(state.get("worker_pid"), 0)
                if current_pid not in (0, os.getpid()):
                    return {"takeover": 1.0, "sleep": 0.0}
                state["worker_pid"] = os.getpid()
                state["worker_started_at"] = _coerce_float_or(state.get("worker_started_at"), locked_now)
                state["updated_at"] = locked_now
                if _worker_should_exit(state, locked_now):
                    return {"exit": 1.0, "sleep": 0.0}
                last_activity = _coerce_float_or(state.get("last_activity_at"), 0.0)
                last_attempt = _coerce_float_or(state.get("last_worker_attempted_at"), 0.0)
                if last_activity > last_attempt and locked_now - last_attempt >= ACTIVE_DEBOUNCE_SECONDS:
                    state["last_worker_attempted_at"] = locked_now
                    state["updated_at"] = locked_now
                    return {"export": 1.0, "sleep": 0.0}
                return {"sleep": _worker_sleep_seconds(state, locked_now)}

            status = _update_state(_snapshot_state)
            if status.get("takeover"):
                return 0
            if status.get("exit"):
                return 0
            if status.get("export"):
                _run_export_cycle("PostToolUse", timeout=DEFAULT_TIMEOUT_SECONDS)
                continue
            time.sleep(status.get("sleep", float(WORKER_POLL_SECONDS)))
    finally:
        def _cleanup(state: dict[str, Any], locked_now: float) -> None:
            if _coerce_int_or(state.get("worker_pid"), 0) == os.getpid():
                _clear_worker_metadata(state)
                state["updated_at"] = locked_now
        _update_state(_cleanup)


def _run_flush(event_name: str) -> int:
    return _run_export_cycle(event_name, timeout=FLUSH_TIMEOUT_SECONDS)


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
        return _run_worker()
    if len(sys.argv) >= 2 and sys.argv[1] == "--flush-now":
        return _run_flush("flush-now")

    raw_hook_input = sys.stdin.buffer.read()
    hook_payload = _parse_hook_payload(raw_hook_input)
    event_name = _hook_event_name(hook_payload)
    try:
        if event_name == "PostToolUse":
            return _run_post_tool_use(event_name)
        return _run_flush(event_name)
    except urllib.error.HTTPError as exc:
        body = exc.read(200).decode("utf-8", errors="replace")
        _post_log("ERROR", "codex quota export HTTP error", {"status": exc.code, "body": body})
        return 1
    except Exception as exc:  # noqa: BLE001
        _post_log("ERROR", "codex quota export error", {"error": exc, "event_name": event_name})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
