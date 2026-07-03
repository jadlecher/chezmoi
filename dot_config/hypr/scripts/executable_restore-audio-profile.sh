#!/usr/bin/env bash
set -euo pipefail

card="alsa_card.pci-0000_00_1f.3"
target_profile="output:hdmi-stereo+input:analog-stereo"
target_sink="alsa_output.pci-0000_00_1f.3.hdmi-stereo"
hdmi_port="hdmi-output-0"
retries=180
retry_interval=0.5

log() {
  printf 'restore-audio-profile: %s\n' "$*" >&2
}

card_json() {
  pactl -f json list cards | jq -c --arg card "$card" '.[] | select(.name == $card)'
}

hdmi_available=""
for ((i = 0; i < retries; i++)); do
  hdmi_available="$(card_json | jq -r --arg port "$hdmi_port" '.ports[$port].availability // "missing"')"
  if [ "$hdmi_available" = "available" ]; then
    break
  fi
  sleep "$retry_interval"
done

if [ "$hdmi_available" != "available" ]; then
  log "monitor audio port ($hdmi_port) not available after ${retries} retries, leaving profile alone"
  exit 0
fi

active_profile="$(card_json | jq -r '.active_profile')"
if [ "$active_profile" = "$target_profile" ]; then
  log "profile already $target_profile, nothing to do"
  exit 0
fi

log "switching $card from $active_profile to $target_profile"
pactl set-card-profile "$card" "$target_profile"
pactl set-default-sink "$target_sink"
pactl set-sink-mute "$target_sink" 0
