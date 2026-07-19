#!/usr/bin/env bash
set -euo pipefail

card="alsa_card.pci-0000_00_1f.3"
hdmi_profile="output:hdmi-stereo+input:analog-stereo"
hdmi_sink="alsa_output.pci-0000_00_1f.3.hdmi-stereo"
analog_profile="output:analog-stereo+input:analog-stereo"
analog_sink="alsa_output.pci-0000_00_1f.3.analog-stereo"
hdmi_port="hdmi-output-0"
retries=180
retry_interval=0.5
sink_retries=20

lock_file="${XDG_RUNTIME_DIR:-/tmp}/restore-audio-profile.lock"
exec 9>"$lock_file"
if ! flock -n 9; then
  printf 'restore-audio-profile: another reconciliation is already running\n' >&2
  exit 0
fi

log() {
  printf 'restore-audio-profile: %s\n' "$*" >&2
}

card_json() {
  pactl -f json list cards 2>/dev/null |
    jq -c --arg card "$card" '.[] | select(.name == $card)' 2>/dev/null || true
}

profile_exists() {
  local card_state="$1" profile="$2"
  jq -e --arg profile "$profile" '.profiles | has($profile)' <<<"$card_state" >/dev/null
}

sink_exists() {
  local sink="$1"
  pactl -f json list sinks 2>/dev/null |
    jq -e --arg sink "$sink" '.[] | select(.name == $sink)' >/dev/null 2>&1
}

move_playing_streams() {
  local sink="$1" stream
  while IFS= read -r stream; do
    [ -n "$stream" ] || continue
    pactl move-sink-input "$stream" "$sink" || log "unable to move stream $stream to $sink"
  done < <(
    pactl -f json list sink-inputs 2>/dev/null |
      jq -r '.[].index' 2>/dev/null || true
  )
}

select_route() {
  local card_state="$1" profile="$2" sink="$3" active_profile="" i

  if ! profile_exists "$card_state" "$profile"; then
    log "profile $profile is unavailable; leaving the current route unchanged"
    return 1
  fi

  active_profile="$(jq -r '.active_profile // ""' <<<"$card_state")"
  if [ "$active_profile" != "$profile" ]; then
    log "switching $card from $active_profile to $profile"
    if ! pactl set-card-profile "$card" "$profile"; then
      log "unable to select profile $profile"
      return 1
    fi
  fi

  for ((i = 0; i < sink_retries; i++)); do
    if sink_exists "$sink"; then
      if ! pactl set-default-sink "$sink"; then
        log "unable to set $sink as the default sink"
        return 1
      fi
      if ! pactl set-sink-mute "$sink" 0; then
        log "unable to unmute $sink"
        return 1
      fi
      move_playing_streams "$sink"
      return 0
    fi
    sleep "$retry_interval"
  done

  log "sink $sink did not appear after selecting $profile"
  return 1
}

analog_selected="false"
for ((i = 0; i < retries; i++)); do
  card_state="$(card_json)"
  if [ -z "$card_state" ]; then
    sleep "$retry_interval"
    continue
  fi

  hdmi_available="$(jq -r --arg port "$hdmi_port" '.ports[$port].availability // "missing"' <<<"$card_state")"
  if [ "$hdmi_available" = "available" ]; then
    if ! select_route "$card_state" "$hdmi_profile" "$hdmi_sink"; then
      select_route "$card_state" "$analog_profile" "$analog_sink" || true
    fi
    exit 0
  fi

  if [ "$analog_selected" != "true" ]; then
    select_route "$card_state" "$analog_profile" "$analog_sink" || true
    analog_selected="true"
  fi

  sleep "$retry_interval"
done

if [ "$analog_selected" = "true" ]; then
  log "monitor audio port ($hdmi_port) was not available after ${retries} retries; keeping onboard speakers selected"
else
  log "audio card $card was not available after ${retries} retries"
fi
