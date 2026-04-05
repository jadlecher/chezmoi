import contextlib
import importlib.machinery
import importlib.util
import io
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PRIMARY_MODULE_PATH = _REPO_ROOT / "dot_local/bin/executable_agent-workflow"
HAS_PYTHON_IMPL = _PRIMARY_MODULE_PATH.exists() and _PRIMARY_MODULE_PATH.read_text(errors="ignore").startswith("#!/usr/bin/env python")
if HAS_PYTHON_IMPL:
    LOADER = importlib.machinery.SourceFileLoader("agent_workflow", str(_PRIMARY_MODULE_PATH))
    SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
    agent_workflow = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = agent_workflow
    LOADER.exec_module(agent_workflow)
else:
    agent_workflow = None


def proc_stat_line(pid: int, comm: str, ppid: int, pgrp: int, tty_nr: int, starttime: int) -> str:
    fields = ["0"] * 50
    fields[0] = str(ppid)
    fields[1] = str(pgrp)
    fields[4] = str(tty_nr)
    fields[19] = str(starttime)
    return f"{pid} ({comm}) S " + " ".join(fields) + "\n"


def write_proc_entry(root: pathlib.Path, *, pid: int, comm: str, cmdline: list[str], ppid: int, pgrp: int, cwd: pathlib.Path, starttime: int, tty: str = "/dev/pts/1") -> None:
    proc_dir = root / str(pid)
    (proc_dir / "fd").mkdir(parents=True)
    (proc_dir / "stat").write_text(proc_stat_line(pid, comm, ppid, pgrp, 34817, starttime))
    (proc_dir / "cmdline").write_bytes("\0".join(cmdline).encode() + b"\0")
    (proc_dir / "cwd").symlink_to(cwd)
    (proc_dir / "fd/0").symlink_to(tty)


@unittest.skipUnless(HAS_PYTHON_IMPL, "agent-workflow Python implementation is no longer vendored in this repo")
class RuntimeDetectionTests(unittest.TestCase):
    def test_wrapper_and_child_collapse_to_one_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "stat").write_text("btime 1000\n")
            repo = root / "repo"
            repo.mkdir()
            write_proc_entry(
                root,
                pid=101,
                comm="node",
                cmdline=["node", "/opt/codex"],
                ppid=1,
                pgrp=200,
                cwd=repo,
                starttime=100,
            )
            write_proc_entry(
                root,
                pid=102,
                comm="codex",
                cmdline=["codex"],
                ppid=101,
                pgrp=200,
                cwd=repo,
                starttime=120,
            )
            write_proc_entry(
                root,
                pid=103,
                comm="node",
                cmdline=["node", "/opt/other-tool"],
                ppid=1,
                pgrp=201,
                cwd=repo,
                starttime=140,
            )

            runtimes = agent_workflow.discover_active_runtimes(root)

            self.assertEqual(len(runtimes), 1)
            self.assertEqual(runtimes[0].tool, "codex")
            self.assertEqual(runtimes[0].pid, 102)
            self.assertEqual(runtimes[0].pgid, 200)

    def test_separate_process_groups_and_cwds_stay_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "stat").write_text("btime 1000\n")
            repo_a = root / "repo-a"
            repo_b = root / "repo-b"
            repo_a.mkdir()
            repo_b.mkdir()
            write_proc_entry(
                root,
                pid=201,
                comm="claude",
                cmdline=["claude"],
                ppid=1,
                pgrp=201,
                cwd=repo_a,
                starttime=100,
            )
            write_proc_entry(
                root,
                pid=301,
                comm="opencode",
                cmdline=["opencode"],
                ppid=1,
                pgrp=301,
                cwd=repo_b,
                starttime=110,
            )

            runtimes = agent_workflow.discover_active_runtimes(root)

            self.assertEqual([(runtime.tool, runtime.cwd) for runtime in runtimes], [("claude", str(repo_a.resolve())), ("opencode", str(repo_b.resolve()))])


@unittest.skipUnless(HAS_PYTHON_IMPL, "agent-workflow Python implementation is no longer vendored in this repo")
class ResolverTests(unittest.TestCase):
    def test_codex_runtime_resolves_single_matching_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            state_db = root / "state.sqlite"
            logs_db = root / "logs.sqlite"
            conn = sqlite3.connect(state_db)
            conn.execute("create table threads (id text, cwd text, title text, updated_at real, git_branch text, agent_role text, agent_nickname text, archived integer)")
            conn.execute("create table logs (id integer primary key, thread_id text, ts real, ts_nanos integer, level text, target text, message text)")
            now = agent_workflow.now_utc()
            updated_at = now.timestamp()
            conn.execute(
                "insert into threads values (?, ?, ?, ?, ?, ?, ?, 0)",
                ("thread-1", "/tmp/project", "Active Codex Session", updated_at, "main", "", ""),
            )
            conn.execute(
                "insert into logs (thread_id, ts, ts_nanos, level, target, message) values (?, ?, 0, 'INFO', '', ?)",
                ("thread-1", updated_at, "ToolCall: wait"),
            )
            conn.commit()
            conn.close()
            conn = sqlite3.connect(logs_db)
            conn.execute("create table logs (id integer primary key, thread_id text, ts real, level text, target text, feedback_log_body text)")
            conn.commit()
            conn.close()

            collector = agent_workflow.CodexCollector()
            collector.state_db = state_db
            collector.logs_db = logs_db
            runtime = agent_workflow.ActiveRuntime(
                tool="codex",
                pid=1,
                pgid=500,
                cwd="/tmp/project",
                started_at=(now - agent_workflow.dt.timedelta(minutes=5)).isoformat(),
                tty="",
            )

            result = collector.resolve_runtime(runtime)

            self.assertEqual(result["tool_session_id"], "thread-1")
            self.assertIn(result["state"], {"running", "ready_for_orders"})

    def test_claude_runtime_with_multiple_plausible_sessions_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            projects_dir = root / "projects"
            cwd = "/tmp/project"
            encoded = "-tmp-project"
            project_dir = projects_dir / encoded
            project_dir.mkdir(parents=True)
            modified = agent_workflow.now_utc().isoformat().replace("+00:00", "Z")
            entries = []
            for session_id in ("sess-1", "sess-2"):
                full_path = project_dir / f"{session_id}.jsonl"
                full_path.write_text("")
                entries.append(
                    {
                        "sessionId": session_id,
                        "fullPath": str(full_path),
                        "summary": f"Session {session_id}",
                        "modified": modified,
                        "projectPath": cwd,
                    }
                )
            (project_dir / "sessions-index.json").write_text(json.dumps({"entries": entries}))

            collector = agent_workflow.ClaudeCollector()
            collector.projects_dir = projects_dir
            runtime = agent_workflow.ActiveRuntime(
                tool="claude",
                pid=1,
                pgid=600,
                cwd=cwd,
                started_at=(agent_workflow.now_utc() - agent_workflow.dt.timedelta(minutes=10)).isoformat(),
                tty="",
            )

            result = collector.resolve_runtime(runtime)

            self.assertEqual(result["session_key"], "claude:pgid:600")
            self.assertIn("session ambiguous", result["state_reason"])

    def test_opencode_runtime_without_backend_session_is_synthetic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "opencode.db"
            conn = sqlite3.connect(db_path)
            conn.execute("create table session (id text, directory text, title text, permission text, time_created integer, time_updated integer, time_archived integer)")
            conn.execute("create table part (session_id text, time_created integer, time_updated integer, data text)")
            conn.commit()
            conn.close()

            collector = agent_workflow.OpencodeCollector()
            collector.db_path = db_path
            runtime = agent_workflow.ActiveRuntime(
                tool="opencode",
                pid=1,
                pgid=700,
                cwd="/tmp/project",
                started_at=agent_workflow.now_utc().isoformat(),
                tty="",
            )

            result = collector.resolve_runtime(runtime)

            self.assertEqual(result["session_key"], "opencode:pgid:700")
            self.assertIn("not yet resolved", result["state_reason"])


@unittest.skipUnless(HAS_PYTHON_IMPL, "agent-workflow Python implementation is no longer vendored in this repo")
class CliTests(unittest.TestCase):
    def test_scan_json_defaults_to_active_only(self) -> None:
        runtime = agent_workflow.ActiveRuntime(tool="codex", pid=1, pgid=800, cwd="/tmp/project", started_at=agent_workflow.now_utc().isoformat(), tty="")
        resolved = {
            "tool": "codex",
            "tool_session_id": "thread-1",
            "cwd": "/tmp/project",
            "worktree_root": "/tmp/project",
            "branch": "main",
            "title": "Active",
            "state": "running",
            "state_reason": "recent Codex activity",
            "last_activity_at": agent_workflow.now_utc().isoformat(),
            "kitty_target": None,
            "nvim_target": None,
        }
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(agent_workflow, "discover_active_runtimes", return_value=[runtime]))
            stack.enter_context(mock.patch.object(agent_workflow.CodexCollector, "resolve_runtime", return_value=resolved))
            stack.enter_context(mock.patch.object(agent_workflow, "load_nvim_registry", return_value=[]))
            stack.enter_context(mock.patch.object(agent_workflow, "load_kitty_targets", return_value=[]))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = agent_workflow.cmd_scan(SimpleNamespace(json=True, all=False))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "active")
        self.assertEqual(len(payload["sessions"]), 1)
        self.assertEqual(payload["sessions"][0]["session_key"], "codex:thread-1")

    def test_scan_json_all_preserves_historical_view(self) -> None:
        historical = {
            "tool": "codex",
            "tool_session_id": "thread-historical",
            "cwd": "/tmp/project",
            "worktree_root": "/tmp/project",
            "branch": "main",
            "title": "Historical",
            "state": "ready_for_orders",
            "state_reason": "last turn appears complete",
            "last_activity_at": agent_workflow.now_utc().isoformat(),
            "kitty_target": None,
            "nvim_target": None,
        }
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(agent_workflow.CodexCollector, "collect", return_value=[historical]))
            stack.enter_context(mock.patch.object(agent_workflow.ClaudeCollector, "collect", return_value=[]))
            stack.enter_context(mock.patch.object(agent_workflow.OpencodeCollector, "collect", return_value=[]))
            stack.enter_context(mock.patch.object(agent_workflow, "load_nvim_registry", return_value=[]))
            stack.enter_context(mock.patch.object(agent_workflow, "load_kitty_targets", return_value=[]))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = agent_workflow.cmd_scan(SimpleNamespace(json=True, all=True))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "all")
        self.assertEqual(len(payload["sessions"]), 1)
        self.assertEqual(payload["sessions"][0]["session_key"], "codex:thread-historical")

    def test_summary_counts_synthetic_running_rows_like_resolved_rows(self) -> None:
        snapshot = {
            "sessions": [
                {"state": "running"},
                {"state": "running"},
                {"state": "ready_for_orders"},
            ]
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            agent_workflow.print_summary(snapshot)
        self.assertEqual(stdout.getvalue().strip(), "attention=0 ready=1 running=2 stale=0 interrupted=0 error=0")


if __name__ == "__main__":
    unittest.main()
