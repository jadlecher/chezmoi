# Dotfiles

Personal Linux configuration managed with [chezmoi](https://www.chezmoi.io/). I use
this primarily on Gentoo, although most of the configuration is Linux-generic.

Edit files in this chezmoi source tree rather than the live files under `$HOME`.
Keep machine-local secrets and private assets untracked.

## Usage

## Default browser

- After each `chezmoi apply`, qutebrowser is selected when it is installed and
  has a usable XDG desktop entry; Firefox is used as the fallback.
- The selector uses `xdg-settings` to update the default HTML, HTTP, and HTTPS
  handlers. If neither supported browser is available, it skips quietly.
- This is Linux-generic and discovers distribution-specific desktop entry names.
  Because it runs after every apply, it intentionally re-enforces this choice
  over manual changes.

```bash
task --list
task diff
task apply-dry
task validate
```
