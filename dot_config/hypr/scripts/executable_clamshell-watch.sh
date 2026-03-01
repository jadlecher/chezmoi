#!/usr/bin/env bash
set -euo pipefail

clamshell_script="$HOME/.config/hypr/scripts/clamshell-mode.sh"

while true; do
  runtime_dir="${XDG_RUNTIME_DIR:-}"
  signature="${HYPRLAND_INSTANCE_SIGNATURE:-}"
  socket_path="$runtime_dir/hypr/$signature/.socket2.sock"

  if [ -z "$runtime_dir" ] || [ -z "$signature" ] || [ ! -S "$socket_path" ]; then
    sleep 1
    continue
  fi

  nc -U "$socket_path" | while IFS= read -r event_line; do
    case "$event_line" in
    monitoradded* | monitorremoved* | monitoraddedv2* | monitorremovedv2*)
      "$clamshell_script" --reason hotplug --settle-seconds 4 --retry-interval 0.25 || true
      ;;
    esac
  done

  sleep 0.5
done
