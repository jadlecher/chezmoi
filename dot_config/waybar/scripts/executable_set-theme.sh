#!/usr/bin/env bash
set -euo pipefail

theme="${1:-}"
case "$theme" in
  light | dark)
    ;;
  "")
    # Fallback for direct invocation without an explicit argument.
    theme="$(gsettings get org.gnome.desktop.interface color-scheme | grep -oE 'light|dark' || true)"
    theme="${theme:-dark}"
    ;;
  *)
    echo "Unknown theme '$theme'" >&2
    exit 1
    ;;
esac

config_dir="$HOME/.config/waybar"
theme_style="$config_dir/style-$theme.css"
current_style="$config_dir/style-current.css"

if [[ ! -f "$theme_style" ]]; then
  echo "missing style file: $theme_style" >&2
  exit 1
fi

ln -sfn "style-$theme.css" "$current_style"

start_waybar() {
  waybar -s "$current_style" >/dev/null 2>&1 &
}

mapfile -t pids < <(pgrep -x waybar || true)
if (( ${#pids[@]} == 0 )); then
  start_waybar
  exit 0
fi

# If Waybar wasn't launched with style-current.css, restart once so future
# theme switches can be handled by symlink updates + SIGUSR2 reload.
needs_restart=0
for pid in "${pids[@]}"; do
  cmdline="$(tr '\0' ' ' </proc/"$pid"/cmdline 2>/dev/null || true)"
  if [[ "$cmdline" != *"-s $current_style"* ]]; then
    needs_restart=1
    break
  fi
done

if (( needs_restart == 1 )); then
  pkill -x waybar || true
  sleep 0.1
  start_waybar
  exit 0
fi

for pid in "${pids[@]}"; do
  kill -SIGUSR2 "$pid" 2>/dev/null || true
done
