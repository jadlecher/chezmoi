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

## Kernel build helper

- Run `build-kernel` as your normal user. The script self-elevates with `sudo` only for privileged steps.
- Avoid `sudo build-kernel`: many systems use a restricted `sudo` PATH that excludes `~/.local/bin`.
- Config source behavior:
  - If `/proc/config.gz` is readable, it is imported into `.config`.
  - If `/proc/config.gz` is unavailable, an existing `/usr/src/linux/.config` is used.
  - If neither source exists, the script exits with an error.
- `make oldconfig` runs before `make -s kernelrelease` so generated config state exists for release detection.
- Optional overrides: `KERNEL_DIR`, `INSTALLKERNEL_LOG`, and `BUILD_JOBS`.

## Codex notifications

- Codex TUI notifications for permission prompts are managed via `.chezmoiscripts/run_onchange_codex-notifications.sh`.
- The script updates only `[tui]` notification keys in `~/.codex/config.toml` and preserves host-local settings such as project trust entries.
- `notifications = ["approval-requested"]` and `notifications_min_timeout_ms = 0` are enforced.
- This is Linux-generic and not Gentoo-specific; visible desktop popup behavior depends on terminal support for notifications.

## Backlight permissions

- `dot_etc/...` in this repo maps to `~/.etc/...`, not system `/etc/...`.
- To grant non-root backlight writes, install a root-managed udev rule at `/etc/udev/rules.d/backlight.rules`:
  ```udev
  ACTION=="add", SUBSYSTEM=="backlight", TEST=="/sys/class/backlight/%k/brightness", RUN+="/bin/chgrp video /sys/class/backlight/%k/brightness"
  ACTION=="add", SUBSYSTEM=="backlight", TEST=="/sys/class/backlight/%k/brightness", RUN+="/bin/chmod g+w /sys/class/backlight/%k/brightness"
  ```
- The `%k` token keeps this device-name agnostic (for example, `intel_backlight` or `nvidia_0`).
- Portability note: Linux-generic approach, but group conventions can vary by distro.

## Waybar Catppuccin themes

- Waybar Catppuccin theme files are fetched via `.chezmoiexternal.toml.tmpl`, not vendored in this repo.
- Only `latte.css` and `mocha.css` are managed externally.
- To update, bump the pinned Catppuccin commit in `.chezmoiexternal.toml.tmpl` and update checksums.

## Hyprland Catppuccin themes

- Hyprland Catppuccin theme files are fetched via `.chezmoiexternal.toml.tmpl`, not vendored in this repo.
- Only `latte.conf` and `mocha.conf` are managed externally.
- To update, bump the pinned Catppuccin Hyprland commit in `.chezmoiexternal.toml.tmpl` and update checksums.

## WSL behavior

- WSL is auto-detected from the Linux kernel release string (looking for `microsoft` or `wsl`).
- On WSL, ChezMoi excludes `~/.config/hypr/**` and `~/.config/waybar/**`.
- On WSL, Waybar Catppuccin externals are not fetched.
- `~/.local/bin/set-theme` skips Hyprland and Waybar targets on WSL, while keeping the rest of the theme updates.
- On WSL, kitty uses an opaque background and resolves its `background_image` from `~/.config/media/consumers/kitty.yaml` via shared media assets.

## Shared theme images

- Shared asset IDs and variants live in `~/.config/media/image-catalog.yaml`.
- The tracked catalog intentionally omits concrete image paths and URLs.
- Hyprland monitor wallpaper assignments reference shared asset IDs from that catalog.
- Machine-local/private image mappings belong in `~/.config/media/image-catalog.local.yaml` (not tracked).
- Start from `~/.config/media/image-catalog.local.example.yaml` and copy it to `~/.config/media/image-catalog.local.yaml`.
- Validate a mapping with:
  `~/.config/media/scripts/image-resolve.py --asset asset.hypr.eDP-1 --variant light --fetch never`.
- Licensed or unredistributable image identifiers must not be committed to tracked catalog files.

## Notes

- I primarily use this on Gentoo Linux.
- I try to keep things Linux-friendly and reasonably portable, but some pieces may assume my setup.
