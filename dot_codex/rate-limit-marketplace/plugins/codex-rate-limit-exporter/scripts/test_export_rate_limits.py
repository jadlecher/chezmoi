#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).with_name("executable_export-rate-limits.py")
if not SCRIPT_PATH.exists():
    SCRIPT_PATH = Path(__file__).with_name("export-rate-limits.py")
SPEC = importlib.util.spec_from_file_location("export_rate_limits", SCRIPT_PATH)
assert SPEC is not None
exporter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["export_rate_limits"] = exporter
SPEC.loader.exec_module(exporter)


def snapshot(session_path: str, observed_at: float) -> exporter.Snapshot:
    identity = f"{session_path}:{observed_at:06.1f}"
    return exporter.Snapshot(
        identity=identity,
        observed_at=observed_at,
        plan_type="pro",
        rate_limit_reached_type=None,
        primary={"used_percent": 10.0, "resets_at": 1000.0},
        secondary={"used_percent": 20.0, "resets_at": 2000.0},
        session_path=session_path,
        limit_id="codex",
        reached_reason="none",
    )


def iter_points(metrics_payload: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    out = []
    resource_metrics = metrics_payload["resourceMetrics"]  # type: ignore[index]
    metrics = resource_metrics[0]["scopeMetrics"][0]["metrics"]  # type: ignore[index]
    for metric in metrics:
        for point in metric["gauge"]["dataPoints"]:
            out.append((metric["name"], point))
    return out


class ExporterPureTest(unittest.TestCase):
    def test_build_metrics_uses_export_time_timestamps(self) -> None:
        with mock.patch.object(exporter.time, "time", return_value=2000.0):
            payload = exporter._build_metrics(snapshot("/session/a.jsonl", 1000.0))

        now_ns = str(int(2000.0 * 1e9))
        for _, point in iter_points(payload):
            self.assertEqual(point["timeUnixNano"], now_ns)
        snapshot_point = next(
            point for name, point in iter_points(payload) if name == "codex_cli_rate_limit_snapshot_timestamp_seconds"
        )
        self.assertEqual(snapshot_point["asDouble"], 1000.0)

    def test_build_metrics_never_uses_future_observed_timestamp(self) -> None:
        with mock.patch.object(exporter.time, "time", return_value=2000.0):
            payload = exporter._build_metrics(snapshot("/session/a.jsonl", 3000.0))

        now_ns = str(int(2000.0 * 1e9))
        for _, point in iter_points(payload):
            self.assertEqual(point["timeUnixNano"], now_ns)

    def test_get_last_export_cursor_reads_legacy_keys(self) -> None:
        observed_at, identity = exporter._get_last_export_cursor(
            {"last_export_identity": "legacy-id", "last_snapshot_timestamp": 123.4}
        )

        self.assertEqual(observed_at, 123.4)
        self.assertEqual(identity, "legacy-id")

    def test_find_snapshots_prefers_codex_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / ".codex" / "sessions" / "2026"
            sessions.mkdir(parents=True)
            session_file = sessions / "session.jsonl"
            session_file.write_text(
                "\n".join(
                    [
                        '{"type":"event_msg","timestamp":"2026-05-01T00:00:00Z","payload":{"type":"token_count","rate_limits":{"plan_type":"pro","limit_id":"chatgpt","primary":{"used_percent":1,"resets_at":1},"secondary":{"used_percent":2,"resets_at":2}}}}',
                        '{"type":"event_msg","timestamp":"2026-05-01T00:01:00Z","payload":{"type":"token_count","rate_limits":{"plan_type":"pro","limit_id":"codex","primary":{"used_percent":3,"resets_at":3},"secondary":{"used_percent":4,"resets_at":4}}}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(exporter.Path, "home", return_value=root),
                mock.patch.object(exporter, "_get_last_export_cursor", return_value=(float("-inf"), "")),
                mock.patch.object(exporter, "_post_log"),
                mock.patch.object(exporter.time, "time", return_value=1714522000.0),
            ):
                got = exporter._find_snapshots_since({})

        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].limit_id, "codex")


class ExporterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.state_path = root / "state.json"
        self.lock_path = root / "state.lock"
        self.patches = [
            mock.patch.object(exporter, "DEFAULT_STATE_PATH", self.state_path),
            mock.patch.object(exporter, "DEFAULT_EXPORT_LOCK_PATH", self.lock_path),
            mock.patch.object(exporter, "_post_log"),
            mock.patch.object(exporter, "_load_endpoint_and_headers", return_value=("http://otel", {})),
            mock.patch.object(exporter, "_build_metrics", side_effect=lambda item: {"identity": item.identity}),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmpdir.cleanup()

    def read_state(self) -> dict[str, object]:
        with self.state_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def write_state(self, payload: dict[str, object]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def run_post_tool_use(
        self,
        snapshots: list[exporter.Snapshot],
        now: float,
        post_json: mock.Mock | None = None,
    ) -> int:
        if post_json is None:
            post_json = mock.Mock()
        with (
            mock.patch.object(exporter, "_find_snapshots_since", return_value=snapshots),
            mock.patch.object(exporter, "_post_json", post_json),
            mock.patch.object(exporter.time, "time", return_value=now),
        ):
            return exporter._run_post_tool_use("PostToolUse")

    def run_flush(
        self,
        snapshots: list[exporter.Snapshot],
        now: float,
        post_json: mock.Mock | None = None,
    ) -> int:
        if post_json is None:
            post_json = mock.Mock()
        with (
            mock.patch.object(exporter, "_find_snapshots_since", return_value=snapshots),
            mock.patch.object(exporter, "_post_json", post_json),
            mock.patch.object(exporter.time, "time", return_value=now),
        ):
            return exporter._run_flush("Stop")

    def test_post_tool_use_with_no_new_snapshots_does_not_write_throttle(self) -> None:
        rc = self.run_post_tool_use([], 100.0)

        self.assertEqual(rc, 0)
        self.assertFalse(self.state_path.exists())

    def test_post_tool_use_inside_session_window_does_not_flush(self) -> None:
        self.write_state(
            {
                "post_tool_use": {
                    "/session/a.jsonl": {
                        "last_attempted_at": 100.0,
                        "last_observed_at": 90.0,
                        "updated_at": 100.0,
                    }
                }
            }
        )
        post_json = mock.Mock()

        rc = self.run_post_tool_use([snapshot("/session/a.jsonl", 120.0)], 130.0, post_json)

        self.assertEqual(rc, 0)
        post_json.assert_not_called()
        state = self.read_state()
        self.assertEqual(state["post_tool_use"]["/session/a.jsonl"]["last_attempted_at"], 100.0)

    def test_post_tool_use_after_session_window_flushes(self) -> None:
        self.write_state(
            {
                "post_tool_use": {
                    "/session/a.jsonl": {
                        "last_attempted_at": 100.0,
                        "last_observed_at": 90.0,
                        "updated_at": 100.0,
                    }
                }
            }
        )
        post_json = mock.Mock()

        rc = self.run_post_tool_use([snapshot("/session/a.jsonl", 170.0)], 161.0, post_json)

        self.assertEqual(rc, 0)
        self.assertEqual(post_json.call_count, 1)
        state = self.read_state()
        self.assertEqual(state["last_exported_identity"], "/session/a.jsonl:0170.0")
        self.assertEqual(state["post_tool_use"]["/session/a.jsonl"]["last_attempted_at"], 161.0)

    def test_eligible_session_flushes_all_snapshots_in_chronological_order(self) -> None:
        self.write_state(
            {
                "post_tool_use": {
                    "/session/a.jsonl": {
                        "last_attempted_at": 100.0,
                        "last_observed_at": 90.0,
                        "updated_at": 100.0,
                    }
                }
            }
        )
        post_json = mock.Mock()
        snapshots = [
            snapshot("/session/a.jsonl", 120.0),
            snapshot("/session/b.jsonl", 121.0),
        ]

        rc = self.run_post_tool_use(snapshots, 130.0, post_json)

        self.assertEqual(rc, 0)
        exported = [call.args[1]["identity"] for call in post_json.call_args_list]
        self.assertEqual(exported, ["/session/a.jsonl:0120.0", "/session/b.jsonl:0121.0"])
        state = self.read_state()
        self.assertEqual(state["last_exported_identity"], "/session/b.jsonl:0121.0")
        self.assertEqual(state["post_tool_use"]["/session/a.jsonl"]["last_attempted_at"], 100.0)
        self.assertEqual(state["post_tool_use"]["/session/b.jsonl"]["last_attempted_at"], 130.0)

    def test_stop_bypasses_post_tool_use_throttle(self) -> None:
        self.write_state(
            {
                "post_tool_use": {
                    "/session/a.jsonl": {
                        "last_attempted_at": 100.0,
                        "last_observed_at": 90.0,
                        "updated_at": 100.0,
                    }
                }
            }
        )
        post_json = mock.Mock()

        rc = self.run_flush([snapshot("/session/a.jsonl", 120.0)], 130.0, post_json)

        self.assertEqual(rc, 0)
        self.assertEqual(post_json.call_count, 1)
        state = self.read_state()
        self.assertEqual(state["last_exported_identity"], "/session/a.jsonl:0120.0")
        self.assertEqual(state["post_tool_use"]["/session/a.jsonl"]["last_attempted_at"], 100.0)

    def test_failed_post_tool_use_export_keeps_cursor_and_retains_attempt(self) -> None:
        self.write_state(
            {
                "last_exported_identity": "/session/a.jsonl:00100.0",
                "last_exported_observed_at": 100.0,
                "last_session_path": "/session/a.jsonl",
                "last_limit_id": "codex",
                "updated_at": 100.0,
            }
        )
        post_json = mock.Mock(side_effect=RuntimeError("endpoint down"))

        rc = self.run_post_tool_use([snapshot("/session/a.jsonl", 130.0)], 140.0, post_json)

        self.assertEqual(rc, 1)
        state = self.read_state()
        self.assertEqual(state["last_exported_identity"], "/session/a.jsonl:00100.0")
        self.assertEqual(state["last_exported_observed_at"], 100.0)
        self.assertEqual(state["post_tool_use"]["/session/a.jsonl"]["last_attempted_at"], 140.0)

    def test_stale_throttle_entries_are_pruned_on_state_write(self) -> None:
        exporter._write_state_payload(
            {
                "post_tool_use": {
                    "/session/old.jsonl": {
                        "last_attempted_at": 1.0,
                        "last_observed_at": 1.0,
                        "updated_at": 1.0,
                    },
                    "/session/current.jsonl": {
                        "last_attempted_at": 100.0,
                        "last_observed_at": 100.0,
                        "updated_at": 100.0,
                    },
                }
            },
            now=100.0 + exporter.METRIC_LOOKBACK_SECONDS,
        )

        state = self.read_state()
        self.assertNotIn("/session/old.jsonl", state["post_tool_use"])
        self.assertIn("/session/current.jsonl", state["post_tool_use"])

    def test_run_locked_exports_advances_state_only_for_successful_snapshots(self) -> None:
        snapshots = [
            snapshot("/session/a.jsonl", 100.0),
            snapshot("/session/a.jsonl", 101.0),
            snapshot("/session/a.jsonl", 102.0),
        ]
        post_json = mock.Mock(side_effect=[None, None, RuntimeError("boom")])

        rc = self.run_flush(snapshots, 130.0, post_json)

        self.assertEqual(rc, 1)
        self.assertEqual(post_json.call_count, 3)
        state = self.read_state()
        self.assertEqual(state["last_exported_identity"], "/session/a.jsonl:0101.0")
        self.assertEqual(state["last_exported_observed_at"], 101.0)

    def test_run_locked_exports_exports_in_chronological_order(self) -> None:
        snapshots = [
            snapshot("/session/a.jsonl", 100.0),
            snapshot("/session/a.jsonl", 101.0),
        ]
        post_json = mock.Mock()

        rc = self.run_flush(snapshots, 130.0, post_json)

        self.assertEqual(rc, 0)
        exported = [call.args[1]["identity"] for call in post_json.call_args_list]
        self.assertEqual(exported, ["/session/a.jsonl:0100.0", "/session/a.jsonl:0101.0"])

    def test_run_locked_exports_is_silent_on_noop(self) -> None:
        post_log = mock.Mock()
        with (
            mock.patch.object(exporter, "_find_snapshots_since", return_value=[]),
            mock.patch.object(exporter, "_post_log", post_log),
            mock.patch.object(exporter.time, "time", return_value=130.0),
        ):
            rc = exporter._run_flush("Stop")

        self.assertEqual(rc, 0)
        post_log.assert_not_called()

    def test_main_dispatches_stop_to_flush(self) -> None:
        fake_stdin = type("FakeStdin", (), {"buffer": type("Buffer", (), {"read": lambda self: b'{"event_name":"Stop"}'})()})()
        flushes = []
        with (
            mock.patch.object(exporter.sys, "stdin", fake_stdin),
            mock.patch.object(exporter, "_run_flush", side_effect=lambda event_name: flushes.append(event_name) or 0),
        ):
            rc = exporter.main()

        self.assertEqual(rc, 0)
        self.assertEqual(flushes, ["Stop"])

    def test_main_dispatches_post_tool_use_to_gated_path(self) -> None:
        fake_stdin = type(
            "FakeStdin",
            (),
            {"buffer": type("Buffer", (), {"read": lambda self: b'{"event_name":"PostToolUse"}'})()},
        )()
        events = []
        with (
            mock.patch.object(exporter.sys, "stdin", fake_stdin),
            mock.patch.object(exporter, "_run_post_tool_use", side_effect=lambda event_name: events.append(event_name) or 0),
        ):
            rc = exporter.main()

        self.assertEqual(rc, 0)
        self.assertEqual(events, ["PostToolUse"])

    def test_parse_hook_payload_rejects_non_object(self) -> None:
        logs = []
        with mock.patch.object(exporter, "_post_log", side_effect=lambda level, message, attrs=None: logs.append((level, message, attrs))):
            got = exporter._parse_hook_payload(b'["not", "an", "object"]')

        self.assertEqual(got, {})
        self.assertEqual(logs, [("WARN", "codex hook input was not an object", {"type": "list"})])


if __name__ == "__main__":
    unittest.main()
