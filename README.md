# My Dotfiles (chezmoi)

This is my personal Linux configuration repo, managed with [chezmoi](https://www.chezmoi.io/).

I use it to track and version the config files I keep on my machine, while editing everything from this chezmoi source tree (not the live files under `$HOME`).

## What's here

- `dot_config/nvim` - my Neovim config
- `dot_config/kitty` - my Kitty terminal config
- `dot_config/hypr` - my Hyprland / Hypridle config

## Chezmoi

- Website/docs: [chezmoi.io](https://www.chezmoi.io/)
- GitHub: [twpayne/chezmoi](https://github.com/twpayne/chezmoi)

## Useful commands

```bash
chezmoi diff
chezmoi apply --dry-run
```

## Notes

- I primarily use this on Gentoo Linux.
- I try to keep things Linux-friendly and reasonably portable, but some pieces may assume my setup.
