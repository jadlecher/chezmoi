# Dotfiles

Personal Linux configuration managed with [chezmoi](https://www.chezmoi.io/).
Edit files in this source tree rather than the live files under `$HOME`, and
keep machine-local secrets and private assets untracked.

## Usage

See chezmoi's [quick start](https://www.chezmoi.io/quick-start/) for setup and
the [command overview](https://www.chezmoi.io/user-guide/command-overview/)
for day-to-day use.

From this source tree:

```sh
chezmoi diff       # Preview changes
chezmoi apply      # Apply changes to $HOME
task apply-dry     # Preview an apply without changing $HOME
task validate      # Run the full repository validation
```

Run `task --list` to see the available project commands.
