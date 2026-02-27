# My Dotfiles (chezmoi)

This is my personal Linux configuration repo, managed with [chezmoi](https://www.chezmoi.io/).

I use it to track and version the config files I keep on my machine, while editing everything from this chezmoi source tree (not the live files under `$HOME`).

## What's here

- `dot_config/nvim` - my Neovim config
- `dot_config/kitty` - my Kitty terminal config
- `dot_config/hypr` - my Hyprland / Hypridle config
- `dot_config/waybar` - my Waybar config
- `dot_config/media` - shared theme image catalog and helper scripts

## Chezmoi

- Website/docs: [chezmoi.io](https://www.chezmoi.io/)
- GitHub: [twpayne/chezmoi](https://github.com/twpayne/chezmoi)

## Useful commands

```bash
chezmoi diff
chezmoi apply --dry-run
chezmoi apply --dry-run --refresh-externals
~/.config/media/scripts/sync-images.py
```

## Waybar Catppuccin themes

- Waybar Catppuccin theme files are fetched via `.chezmoiexternal.toml`, not vendored in this repo.
- Only `latte.css` and `mocha.css` are managed externally.
- To update, bump the pinned Catppuccin commit in `.chezmoiexternal.toml` and update checksums.

## Shared theme images

- Shared image definitions live in `~/.config/media/image-catalog.yaml`.
- Hyprland monitor wallpaper assignments reference shared asset IDs from that catalog.
- Local/private image overrides can be set in `~/.config/media/image-catalog.local.yaml` (not tracked).
- No unknown-license binary wallpaper files are committed; remote sources should include checksum and attribution metadata.

## Notes

- I primarily use this on Gentoo Linux.
- I try to keep things Linux-friendly and reasonably portable, but some pieces may assume my setup.
