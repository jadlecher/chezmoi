# My Dotfiles (chezmoi)

This is my personal Linux configuration repo, managed with [chezmoi](https://www.chezmoi.io/).

I use it to track and version the config files I keep on my machine, while editing everything from this chezmoi source tree (not the live files under `$HOME`).

## What's here

- `dot_config/nvim` - my Neovim config
- `dot_config/kitty` - my Kitty terminal config
- `dot_config/hypr` - my Hyprland / Hypridle config
- `dot_config/waybar` - my Waybar config
- `dot_config/media` - shared theme image catalog and helper scripts
- `dot_local/share/wayland-sessions` - custom user session entries

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
- `build-kernel` installs with `SYSTEMD_KERNEL_INSTALL=1` (modern `kernel-install` flow) even on OpenRC hosts.
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

## AI CLI telemetry

- AI CLI OTel ingest uses the unmanaged local shell secret `AI_CLI_OTEL_INGEST_TOKEN` in `~/.config/shell/secrets.local`.
- Claude Code telemetry is configured from `~/.bashrc` and enables OTLP metrics and logs only when that token is set.
- Codex telemetry is rendered into `~/.codex/config.toml` from the same local token and only enables OTLP log export.
- Codex quota metrics are activated through `~/.codex/hooks.json`; the managed local plugin packages the exporter and is reinstalled after managed Codex files are written when the plugin bundle changes during `chezmoi apply`.
- `PostToolUse` now acts as a fast notifier only: it records session activity and starts or reuses a detached worker so tool-use hooks return immediately.
- The detached worker debounces active sessions to roughly every 10 seconds, scans Codex session files incrementally, and exports only the newest unseen quota snapshot because the OTel series are gauges.
- `Stop`, `StopFailure`, and `SubagentStop` still flush synchronously, but with a bounded metrics timeout so the final export remains prompt.
- That plugin reinstall verifies the installed cache version against the rendered live manifest, retries with a remove/re-add when Codex keeps a stale cache, and remains best-effort so top-level hooks stay the active runtime path if Codex is unavailable or still stale.
- The Kubernetes secret fetch command is environment-specific to the lab cluster, but the resulting shell and Codex config are Linux-generic.
- The literal bearer token is not committed in this repo.

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

## Hyprland session wrapper

- `~/.local/bin/start-hyprland-dbus` wraps `/usr/bin/start-hyprland` in `dbus-run-session`.
- `hypridle` is started directly by Hyprland and must inherit the graphical session bus; `~/.local/bin/start-hypridle` is only a strict diagnostic wrapper and refuses to start without `DBUS_SESSION_BUS_ADDRESS`.
- `~/.local/share/wayland-sessions/hyprland.desktop` intentionally shadows the packaged `Hyprland` entry by launching `~/.local/bin/start-hyprland-dbus`.
- `~/.local/share/wayland-sessions/hyprland-dbus.desktop` provides an explicit `Hyprland (D-Bus)` entry for diagnostics or fallback selection.
- This is Linux-generic and avoids patching packaged session files under `/usr/share`.
- `run_onchange_after_fix-hyprland-session-dbus.sh.tmpl` mirrors both desktop entries into `/usr/local/share/wayland-sessions/` so `greetd`/`regreet` can see them without modifying package-owned files, and only re-runs when either source desktop entry changes.
- Gentoo caveat: this repo uses `sudo install` into `/usr/local/share/wayland-sessions/`, which is Gentoo-safe and Linux-generic, but still depends on local privilege policy during `chezmoi apply`.

## Kvantum Catppuccin themes (Qt apps, including wpa_gui)

- Qt theming is switched by `~/.local/bin/set-theme` via `~/.config/kvantum/scripts/set-theme.sh`.
- The selector prefers Catppuccin Lavender variants for each flavor:
  - `dark` -> Mocha + Lavender
  - `light` -> Latte + Lavender
- Linux-generic behavior: if Kvantum or Catppuccin Kvantum themes are unavailable, the step is skipped with a warning.
- Gentoo caveat: current ebuilds are not stable on `amd64` and require keyword acceptance before install:
  - `x11-themes/kvantum` (`~amd64` in Gentoo tree)
  - `x11-themes/catppuccin-kvantum` (`~amd64`/masked in guru)

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
