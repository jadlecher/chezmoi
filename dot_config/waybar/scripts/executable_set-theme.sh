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
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/waybar"
current_style="$cache_dir/style-current.css"

if [[ ! -f "$theme_style" ]]; then
  echo "missing style file: $theme_style" >&2
  exit 1
fi

mkdir -p "$cache_dir"

if [[ ! -f "$current_style" ]] || ! cmp -s "$theme_style" "$current_style"; then
  cp "$theme_style" "$current_style"
fi

start_waybar() {
  waybar -s "$current_style" >/dev/null 2>&1 &
}

mapfile -t pids < <(pgrep -x waybar || true)
if (( ${#pids[@]} == 0 )); then
  start_waybar
else
  for pid in "${pids[@]}"; do
    kill -SIGUSR2 "$pid" 2>/dev/null || true
  done
fi
