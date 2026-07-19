#!/usr/bin/env bash
set -euo pipefail

clamshell_script="$HOME/.config/hypr/scripts/clamshell-mode.sh"
audio_script="$HOME/.config/hypr/scripts/restore-audio-profile.sh"
waybar_session_script="$HOME/.config/waybar/scripts/session.sh"
last_reconcile_ts=0

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
      if [[ -x "$audio_script" ]]; then
        "$audio_script" >/dev/null 2>&1 &
      fi
      if [[ -x "$waybar_session_script" ]]; then
        now_ts="$(date +%s)"
        if (( now_ts - last_reconcile_ts >= 1 )); then
          "$waybar_session_script" reconcile || true
          last_reconcile_ts="$now_ts"
        fi
      fi
      ;;
    esac
  done

  sleep 0.5
done
