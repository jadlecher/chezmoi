# AGENTS.md

This repository is a personal Linux configuration project managed with [ChezMoi](https://www.chezmoi.io/). The main workstation runs Gentoo Linux, but agents should treat this repo as Linux-generic first and call out any Gentoo-specific assumptions or commands they introduce. Current contents are focused on `dot_config/nvim` and `dot_config/kitty`, but do not assume the repo is permanently limited to those areas.

## Working In This Repo

- Edit files in this ChezMoi source tree, not the live files under `$HOME`.
- Prefer ChezMoi-native workflows/commands when useful for inspection or validation.
- Do not run `chezmoi apply` or other live-application steps unless explicitly requested.
- Keep changes targeted and preserve the existing style/structure of each config.

## Validation (Conservative by Default)

- Review the diff before finishing.
- Prefer non-destructive checks (for example, dry-run or diff-style checks) where applicable.
- Run tool-specific syntax/headless checks only when safe and relevant.
- Clearly state what you verified and what you did not run.

## Secrets and Sensitive Data

- Do not add plaintext secrets, tokens, private keys, or credentials.
- Ask before modifying any secret-management or encryption workflow.
- If sensitive material is encountered, do not print or expose secret values in output.

## Reporting Expectations

- Summarize what changed and why.
- Note portability caveats (especially Gentoo-specific assumptions).
- List validation performed and any skipped checks.

## Question Policy

- When asking the user questions, always use the `question` tool.
- All questions must be posed as multiple-choice questions with a clear recommendation.
- The recommended option should be listed first with "(Recommended)" appended to its label.
- Free-form/open-ended questions should only be used as a last-ditch fallback when the question explicitly cannot be rendered in a multiple-choice format.

## Worktree Validation

- This repo uses `go-task` as a frontend for `chezmoi` to simplify validation in `git worktree`.
- Instead of running `chezmoi diff`, use `task diff`. This automatically uses the current worktree as the source.
- For a comprehensive check, run `task validate`, which performs both a `diff` and a `verify`.
- All `task` commands pass extra arguments to `chezmoi`. For example: `task diff -- --refresh-externals`.
