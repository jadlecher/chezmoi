#!/usr/bin/env python3
"""Claude Code statusline exporter.

Main mode (called by Claude Code statusLine):
  - Reads statusline JSON from stdin
  - Calls existing statusline-command.sh for git/context output
  - Appends rate-limit percentages to the statusline
  - Spawns a detached export worker if rate_limits are present
  - Prints combined statusline to stdout and exits immediately

Export worker mode (--export-worker <tmpfile>):
  - Reads JSON data from tmpfile, deletes it
  - Builds an OTLP/JSON metrics payload
  - POSTs to the OTel collector endpoint
  - Logs result to the configured log file
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SCRIPT_PATH = os.path.realpath(__file__)
EXISTING_STATUSLINE = os.path.expanduser("~/.claude/statusline-command.sh")
DEFAULT_LOG_FILE = os.path.expanduser("~/.claude/rate-limit-exporter.log")
DEFAULT_SERVICE_NAME = "claude-code-statusline-exporter"
DEFAULT_EXPORT_TIMEOUT = 5

_CYAN = "\033[0;36m"
_GREEN = "\033[0;32m"
_YELLOW = "\033[0;33m"
_RED = "\033[0;31m"
_RESET = "\033[0m"


def _log(msg: str, log_file: str = DEFAULT_LOG_FILE) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} {msg}\n"
    try:
        with open(log_file, "a") as f:
            f.write(line)
    except Exception:
        pass


def _color_pct(pct: float) -> str:
    if pct >= 85:
        color = _RED
    elif pct >= 70:
        color = _YELLOW
    else:
        color = _GREEN
    return f"{color}RL 5h:{pct:.0f}%{_RESET}" if False else f"{color}{pct:.0f}%{_RESET}"


def _render_rate_limits(rate_limits: dict) -> str:
    """Return a formatted string for the statusline, or '' if nothing to show."""
    parts = []
    for window_key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        entry = rate_limits.get(window_key)
        if not isinstance(entry, dict):
            continue
        pct = entry.get("used_percentage")
        if pct is None:
            continue
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            continue
        if pct >= 85:
            color = _RED
        elif pct >= 70:
            color = _YELLOW
        else:
            color = _GREEN
        parts.append(f"{color}{label}:{pct:.0f}%{_RESET}")
    if not parts:
        return ""
    return f"{_CYAN}RL{_RESET} " + " ".join(parts)


def _parse_resets_at(value) -> float | None:
    """Parse resets_at as epoch seconds, accepting ISO 8601 strings or numeric values."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.timestamp()
        except ValueError:
            pass
    return None


def _parse_otlp_headers(headers_str: str) -> dict[str, str]:
    """Parse OTEL_EXPORTER_OTLP_HEADERS 'Key=Value,Key=Value' format."""
    result = {}
    for part in headers_str.split(","):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip()] = v.strip()
    return result


def _parse_resource_attributes(attrs_str: str) -> list[dict]:
    """Parse OTEL_RESOURCE_ATTRIBUTES 'key=value,key=value' format."""
    result = []
    for part in attrs_str.split(","):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result.append({"key": k.strip(), "value": {"stringValue": v.strip()}})
    return result


def _build_otlp_payload(rate_limits: dict, service_name: str, resource_attrs: list[dict]) -> dict:
    """Build an OTLP/JSON metrics payload for rate-limit gauges."""
    now_ns = str(int(time.time() * 1e9))
    now_epoch = time.time()

    data_points_used: list[dict] = []
    data_points_resets: list[dict] = []

    for window_key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        entry = rate_limits.get(window_key)
        if not isinstance(entry, dict):
            continue

        pct = entry.get("used_percentage")
        if pct is not None:
            try:
                data_points_used.append({
                    "attributes": [{"key": "window", "value": {"stringValue": label}}],
                    "timeUnixNano": now_ns,
                    "asDouble": float(pct),
                })
            except (TypeError, ValueError):
                pass

        resets_epoch = _parse_resets_at(entry.get("resets_at"))
        if resets_epoch is not None:
            data_points_resets.append({
                "attributes": [{"key": "window", "value": {"stringValue": label}}],
                "timeUnixNano": now_ns,
                "asDouble": resets_epoch,
            })

    metrics = []
    if data_points_used:
        metrics.append({
            "name": "claude_code_rate_limit_used_percent",
            "description": "Claude.ai subscription rate-limit used percentage (0–100)",
            "unit": "",
            "gauge": {"dataPoints": data_points_used},
        })
    if data_points_resets:
        metrics.append({
            "name": "claude_code_rate_limit_resets_at_seconds",
            "description": "Unix epoch when the rate-limit window resets",
            "unit": "s",
            "gauge": {"dataPoints": data_points_resets},
        })

    metrics.append({
        "name": "claude_code_statusline_exporter_last_success_timestamp_seconds",
        "description": "Unix epoch of last successful export attempt",
        "unit": "s",
        "gauge": {"dataPoints": [{
            "timeUnixNano": now_ns,
            "asDouble": now_epoch,
        }]},
    })

    resource_attributes = [
        {"key": "service.name", "value": {"stringValue": service_name}},
    ] + resource_attrs

    return {
        "resourceMetrics": [{
            "resource": {"attributes": resource_attributes},
            "scopeMetrics": [{
                "scope": {"name": service_name, "version": "1.0.0"},
                "metrics": metrics,
            }],
        }]
    }


def run_export_worker(tmpfile: str) -> None:
    log_file = os.path.expanduser(os.environ.get("CC_RL_LOG_FILE", DEFAULT_LOG_FILE))

    try:
        with open(tmpfile) as f:
            raw = f.read()
    except Exception as e:
        _log(f"export-worker: failed to read tmpfile {tmpfile}: {e}", log_file)
        return
    finally:
        try:
            os.unlink(tmpfile)
        except Exception:
            pass

    try:
        data = json.loads(raw)
    except Exception as e:
        _log(f"export-worker: JSON parse error: {e}", log_file)
        return

    rate_limits = data.get("rate_limits")
    if not isinstance(rate_limits, dict) or not rate_limits:
        _log("export-worker: no rate_limits in payload, skipping export", log_file)
        return

    endpoint_base = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    if not endpoint_base:
        try:
            settings_path = os.path.expanduser("~/.claude/settings.json")
            with open(settings_path) as f:
                settings = json.load(f)
            endpoint_base = settings.get("env", {}).get("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
        except Exception:
            pass
    if not endpoint_base:
        _log("export-worker: OTEL_EXPORTER_OTLP_ENDPOINT not set, skipping export", log_file)
        return

    headers_str = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
    if not headers_str:
        token = os.environ.get("AI_CLI_OTEL_INGEST_TOKEN", "")
        if token:
            headers_str = f"Authorization=Bearer {token}"
    headers = _parse_otlp_headers(headers_str) if headers_str else {}

    service_name = os.environ.get("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME)

    resource_attrs_str = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
    resource_attrs = _parse_resource_attributes(resource_attrs_str) if resource_attrs_str else []

    timeout = int(os.environ.get("CC_RL_EXPORT_TIMEOUT", DEFAULT_EXPORT_TIMEOUT))

    payload = _build_otlp_payload(rate_limits, service_name, resource_attrs)
    body = json.dumps(payload).encode("utf-8")

    url = f"{endpoint_base}/v1/metrics"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            **headers,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
        _log(f"export-worker: POST {url} -> {status}", log_file)
    except urllib.error.HTTPError as e:
        body_snippet = ""
        try:
            body_snippet = e.read(200).decode("utf-8", errors="replace")
        except Exception:
            pass
        _log(f"export-worker: HTTP error {e.code} for {url}: {body_snippet}", log_file)
    except Exception as e:
        _log(f"export-worker: export failed for {url}: {e}", log_file)


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--export-worker":
        run_export_worker(sys.argv[2])
        return

    log_file = os.path.expanduser(os.environ.get("CC_RL_LOG_FILE", DEFAULT_LOG_FILE))

    data_raw = sys.stdin.buffer.read()

    # Collect existing statusline output from the bash script
    existing_output = ""
    try:
        result = subprocess.run(
            ["bash", EXISTING_STATUSLINE],
            input=data_raw,
            capture_output=True,
            timeout=3,
        )
        existing_output = result.stdout.decode("utf-8", errors="replace")
    except Exception as e:
        _log(f"main: failed to run existing statusline: {e}", log_file)

    # Parse rate limits
    rate_limits: dict = {}
    try:
        data = json.loads(data_raw)
        rl = data.get("rate_limits")
        if isinstance(rl, dict):
            rate_limits = rl
    except Exception as e:
        _log(f"main: JSON parse error: {e}", log_file)

    rl_display = _render_rate_limits(rate_limits)

    # Combine outputs
    if existing_output and rl_display:
        sys.stdout.write(f"{existing_output} | {rl_display}")
    elif existing_output:
        sys.stdout.write(existing_output)
    elif rl_display:
        sys.stdout.write(rl_display)

    sys.stdout.flush()

    # Spawn detached export worker if we have rate limit data
    if rate_limits:
        tmpfile = f"/tmp/cc-rl-export-{os.getpid()}.json"
        try:
            with open(tmpfile, "w") as f:
                f.write(data_raw.decode("utf-8", errors="replace"))
            subprocess.Popen(
                [sys.executable, SCRIPT_PATH, "--export-worker", tmpfile],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=open(log_file, "a"),
                close_fds=True,
                start_new_session=True,
            )
        except Exception as e:
            _log(f"main: failed to spawn export worker: {e}", log_file)
            try:
                os.unlink(tmpfile)
            except Exception:
                pass


if __name__ == "__main__":
    main()
