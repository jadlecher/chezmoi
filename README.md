# Dotfiles

Personal Linux configuration managed with [chezmoi](https://www.chezmoi.io/). I use
this primarily on Gentoo, although most of the configuration is Linux-generic.

Edit files in this chezmoi source tree rather than the live files under `$HOME`.
Keep machine-local secrets and private assets untracked.

## Usage

```bash
task --list
task diff
task apply-dry
task validate
```
