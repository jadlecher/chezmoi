# Code and documentation

- Follow DRY, KISS, and YAGNI.
- Prefer the smallest clear implementation that meets the stated requirements. Avoid speculative features, abstractions, duplication, and unnecessary dependencies.
- Treat every line of code and documentation as a maintenance burden. Prefer less when it achieves the goal without sacrificing correctness, security, readability, tests, or necessary error handling.
- Keep comments, docstrings, and documentation limited to behavior, constraints, decisions, or rationale that a senior developer could not infer from the code. Do not explain basic programming, software-engineering, or tooling concepts.

## Project-external identifiers

- Never include project-external identifiers, such as Vikunja task IDs or tracker URLs, in Git branch names or commit messages, code comments, documentation, merge-request titles or descriptions, or other project artifacts.
- Keep project artifacts self-contained and describe changes with project-local terminology. Track external references in the external system instead of copying them into the repository or its Git/MR metadata.

## Git worktree workflow

- Treat the primary checkout on `main` as a baseline, not an implementation workspace. Do not create a topic branch there or switch it away from `main`.
- Before creating a new worktree, ensure `origin/main` is current by running `git fetch origin main`. If the fetch fails, do not create the worktree from a potentially stale ref; report the failure instead.
- Before starting implementation, inspect `git worktree list`. If the current directory is already a linked worktree, continue there. Otherwise reuse a suitable existing linked worktree for the task; if none exists, create one under the repo's `.worktrees/` directory from the latest fetched `origin/main`:
  ```bash
  git worktree add -b <topic-branch> .worktrees/<topic-branch> origin/main
  ```
- If `main` has uncommitted changes, leave them untouched and create the implementation worktree from `origin/main`, not `main`'s current `HEAD`. Do not reset, stash, move, or copy those changes unless explicitly requested.
- Make all edits, tests, validation, and commits in the linked worktree. Use the worktree's branch and path when reporting the result, and do not remove existing worktrees or branches without explicit authorization.

## Vikunja task tracking

Use Vikunja only when explicitly asked to record, plan, or work on tracked tasks. Check for an existing task before creating one, and treat capture requests as planning only. Keep tasks in the appropriate repository project with concise context and completion criteria sufficient for another agent to resume; use parent/subtask relations for multi-MR epics.

Invoke `vja` directly; it is installed as a persistent uv tool in `$HOME/.local/bin`. If command lookup unexpectedly fails, try `$HOME/.local/bin/vja`. Do not fall back to `uvx vja`: agent sandboxes cannot write uv's default cache and tool directories and may not have package-index access. If neither executable path works, report a host provisioning problem and do not claim the Vikunja operation succeeded.

For an implementation request, check the existing task's status first. If it is in `Backlog`, move it to `Ready` automatically; do not ask for permission. Pull implementation work only from `Ready`, then move it through `In Progress` and `Under Review`. Return review changes to `In Progress`, and keep blocked work open in `Blocked` with a brief explanation.

Use a GitLab merge request as the preferred delivery mechanism for code changes and create it without asking for permission. Never merge an MR yourself; leave approval and merging to the user. Unless a task says otherwise, mark development work `Done` only after the user approves its MR and the MR is merged. Report the task ID, MR, and every state change made.
