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

    def test_find_newest_snapshot_prefers_codex_limit(self) -> None:
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
            state = {}
            with (
                mock.patch.object(exporter.Path, "home", return_value=root),
                mock.patch.object(exporter, "_post_log"),
                mock.patch.object(exporter.time, "time", return_value=1714522000.0),
            ):
                got = exporter._find_newest_snapshot(state, 1714522000.0)

        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.limit_id, "codex")


class ExporterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.state_path = root / "state.json"
        self.state_lock_path = root / "state.lock"
        self.export_lock_path = root / "export.lock"
        self.session_root = root / ".codex" / "sessions"
        self.log_path = root / "exporter.log"
        self.patches = [
            mock.patch.object(exporter, "DEFAULT_STATE_PATH", self.state_path),
            mock.patch.object(exporter, "DEFAULT_STATE_LOCK_PATH", self.state_lock_path),
            mock.patch.object(exporter, "DEFAULT_EXPORT_LOCK_PATH", self.export_lock_path),
            mock.patch.object(exporter, "DEFAULT_LOG_FILE", self.log_path),
            mock.patch.object(exporter.Path, "home", return_value=root),
            mock.patch.object(exporter, "_load_endpoint_and_headers", return_value=("http://otel", {})),
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

    def write_session(self, relpath: str, lines: list[str]) -> Path:
        path = self.session_root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def run_post_tool_use(self, now: float, spawn_worker: mock.Mock | None = None) -> int:
        if spawn_worker is None:
            spawn_worker = mock.Mock(return_value=12345)
        with (
            mock.patch.object(exporter.time, "time", return_value=now),
            mock.patch.object(exporter, "_spawn_worker", spawn_worker),
        ):
            return exporter._run_post_tool_use("PostToolUse")

    def run_flush(self, now: float, post_json: mock.Mock | None = None) -> int:
        if post_json is None:
            post_json = mock.Mock()
        with (
            mock.patch.object(exporter.time, "time", side_effect=[now, now, now, now, now, now]),
            mock.patch.object(exporter, "_post_json", post_json),
            mock.patch.object(exporter, "_post_log"),
        ):
            return exporter._run_flush("Stop")

    def test_post_tool_use_records_activity_and_spawns_worker(self) -> None:
        spawn_worker = mock.Mock(return_value=4242)

        rc = self.run_post_tool_use(100.0, spawn_worker)

        self.assertEqual(rc, 0)
        spawn_worker.assert_called_once_with()
        state = self.read_state()
        self.assertEqual(state["last_activity_at"], 100.0)
        self.assertEqual(state["worker_pid"], 4242)

    def test_post_tool_use_skips_spawn_when_worker_is_alive(self) -> None:
        self.write_state({"worker_pid": 333, "worker_started_at": 90.0, "last_activity_at": 90.0})
        spawn_worker = mock.Mock()
        with mock.patch.object(exporter, "_pid_is_running", return_value=True):
            rc = self.run_post_tool_use(100.0, spawn_worker)

        self.assertEqual(rc, 0)
        spawn_worker.assert_not_called()
        state = self.read_state()
        self.assertEqual(state["last_activity_at"], 100.0)
        self.assertEqual(state["worker_pid"], 333)

    def test_post_tool_use_spawn_failure_is_non_blocking(self) -> None:
        spawn_worker = mock.Mock(side_effect=RuntimeError("boom"))
        post_log = mock.Mock()
        with mock.patch.object(exporter, "_post_log", post_log):
            rc = self.run_post_tool_use(100.0, spawn_worker)

        self.assertEqual(rc, 0)
        state = self.read_state()
        self.assertEqual(state["last_activity_at"], 100.0)
        self.assertNotIn("worker_pid", state)
        self.assertIn("codex quota worker spawn failed", post_log.call_args.args)

    def test_find_newest_snapshot_updates_cursor_incrementally(self) -> None:
        session = self.write_session(
            "2026/06/01/session.jsonl",
            [
                '{"type":"event_msg","timestamp":"2026-06-01T00:00:00Z","payload":{"type":"token_count","rate_limits":{"plan_type":"pro","limit_id":"codex","primary":{"used_percent":1,"resets_at":1},"secondary":{"used_percent":2,"resets_at":2}}}}',
            ],
        )
        state: dict[str, object] = {}
        with mock.patch.object(exporter.time, "time", return_value=1780272000.0):
            first = exporter._find_newest_snapshot(state, 1780272000.0)
        assert first is not None
        first_cursor = dict(state[exporter.SESSION_CURSOR_STATE_KEY][str(session)])

        with session.open("a", encoding="utf-8") as handle:
            handle.write('{"type":"event_msg","timestamp":"2026-06-01T00:01:00Z","payload":{"type":"token_count","rate_limits":{"plan_type":"pro","limit_id":"codex","primary":{"used_percent":3,"resets_at":3},"secondary":{"used_percent":4,"resets_at":4}}}}\n')
        state["last_exported_identity"] = first.identity
        state["last_exported_observed_at"] = first.observed_at
        with mock.patch.object(exporter.time, "time", return_value=1780272060.0):
            second = exporter._find_newest_snapshot(state, 1780272060.0)

        assert second is not None
        second_cursor = dict(state[exporter.SESSION_CURSOR_STATE_KEY][str(session)])
        self.assertGreater(second_cursor["offset"], first_cursor["offset"])
        self.assertEqual(second.observed_at, 1780272060.0)

    def test_flush_exports_only_newest_snapshot(self) -> None:
        self.write_session(
            "2026/06/01/session.jsonl",
            [
                '{"type":"event_msg","timestamp":"2026-06-01T00:00:00Z","payload":{"type":"token_count","rate_limits":{"plan_type":"pro","limit_id":"codex","primary":{"used_percent":1,"resets_at":1},"secondary":{"used_percent":2,"resets_at":2}}}}',
                '{"type":"event_msg","timestamp":"2026-06-01T00:01:00Z","payload":{"type":"token_count","rate_limits":{"plan_type":"codex-pro","limit_id":"codex","primary":{"used_percent":3,"resets_at":3},"secondary":{"used_percent":4,"resets_at":4}}}}',
            ],
        )
        post_json = mock.Mock()

        rc = self.run_flush(1780272100.0, post_json)

        self.assertEqual(rc, 0)
        self.assertEqual(post_json.call_count, 1)
        payload = post_json.call_args.args[1]
        state = self.read_state()
        self.assertEqual(state["last_exported_observed_at"], 1780272060.0)
        self.assertEqual(
            payload["resourceMetrics"][0]["resource"]["attributes"][-1]["value"]["stringValue"],
            "codex-pro",
        )

    def test_flush_uses_bounded_timeout(self) -> None:
        self.write_session(
            "2026/06/01/session.jsonl",
            [
                '{"type":"event_msg","timestamp":"2026-06-01T00:01:00Z","payload":{"type":"token_count","rate_limits":{"plan_type":"pro","limit_id":"codex","primary":{"used_percent":3,"resets_at":3},"secondary":{"used_percent":4,"resets_at":4}}}}',
            ],
        )
        post_json = mock.Mock()
        with (
            mock.patch.object(exporter.time, "time", side_effect=[1780272100.0, 1780272100.0, 1780272100.0, 1780272100.0, 1780272100.0, 1780272100.0]),
            mock.patch.object(exporter, "_post_json", post_json),
            mock.patch.object(exporter, "_post_log"),
        ):
            exporter._run_flush("Stop")

        self.assertEqual(post_json.call_args.kwargs["timeout"], exporter.FLUSH_TIMEOUT_SECONDS)

    def test_success_log_stays_local_only(self) -> None:
        post_json = mock.Mock()
        with (
            mock.patch.object(exporter, "_post_json", post_json),
            mock.patch.object(exporter, "_log_local"),
        ):
            exporter._post_log("INFO", "ok")

        post_json.assert_not_called()

    def test_main_dispatches_flush_now_flag(self) -> None:
        with (
            mock.patch.object(exporter.sys, "argv", [str(SCRIPT_PATH), "--flush-now"]),
            mock.patch.object(exporter, "_run_flush", return_value=0) as run_flush,
        ):
            rc = exporter.main()

        self.assertEqual(rc, 0)
        run_flush.assert_called_once_with("flush-now")

    def test_main_dispatches_post_tool_use_to_notifier(self) -> None:
        fake_stdin = type(
            "FakeStdin",
            (),
            {"buffer": type("Buffer", (), {"read": lambda self: b'{"event_name":"PostToolUse"}'})()},
        )()
        with (
            mock.patch.object(exporter.sys, "argv", [str(SCRIPT_PATH)]),
            mock.patch.object(exporter.sys, "stdin", fake_stdin),
            mock.patch.object(exporter, "_run_post_tool_use", return_value=0) as run_post,
        ):
            rc = exporter.main()

        self.assertEqual(rc, 0)
        run_post.assert_called_once_with("PostToolUse")

    def test_parse_hook_payload_rejects_non_object(self) -> None:
        logs = []
        with mock.patch.object(exporter, "_post_log", side_effect=lambda level, message, attrs=None: logs.append((level, message, attrs))):
            got = exporter._parse_hook_payload(b'["not", "an", "object"]')

        self.assertEqual(got, {})
        self.assertEqual(logs, [("WARN", "codex hook input was not an object", {"type": "list"})])


if __name__ == "__main__":
    unittest.main()
