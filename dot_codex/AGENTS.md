# Code and documentation

- Follow DRY, KISS, and YAGNI.
- Prefer the smallest clear implementation that meets the stated requirements. Avoid speculative features, abstractions, duplication, and unnecessary dependencies.
- Treat every line of code and documentation as a maintenance burden. Prefer less when it achieves the goal without sacrificing correctness, security, readability, tests, or necessary error handling.
- Keep comments, docstrings, and documentation limited to behavior, constraints, decisions, or rationale that a senior developer could not infer from the code. Do not explain basic programming, software-engineering, or tooling concepts.

## Vikunja task tracking

Use vja only when the user explicitly asks to record or manage a task in Vikunja. Do not create tracker entries for ordinary conversation, trivial answers, or untracked implementation work.

- Resolve the command as `vja` first. If it is not available in the agent shell, use `uvx vja`; interactive shell aliases are not guaranteed to be loaded.
- Respect vja's configured default project. Do not invent a project, priority, label, or due date unless the user specifies one.
- Before creating a task, inspect active tasks with `vja ls --json`. Reuse a clearly matching task; if several tasks are plausible matches, ask the user before changing or creating one.
- Create a concise, actionable title and include relevant context, constraints, and acceptance details in the task note. Never put secrets, tokens, credentials, or private keys in a task.
- Treat requests such as "record this in Vikunja" as tracker-only requests. Do not implement the underlying work unless the user separately asks for it.
- For work on an existing task, inspect it with `vja show TASK_ID --json` and keep its ID in progress updates.
- Mark a task complete with `vja edit TASK_ID --done=true` only after the requested work and relevant validation succeed. Keep blocked or incomplete tasks open; do not use toggle-style completion commands when an idempotent edit is available.
- Do not delete or bulk-edit tasks without explicit authorization.
- If vja is unavailable, continue larger requested work with a clear warning. For tracker-only requests, report that recording failed; never invent a task ID or claim that Vikunja was updated.
- Report the task ID, title, and action taken in the final response.
