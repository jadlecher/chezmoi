#!/usr/bin/env bash
set -euo pipefail

laptop_output="eDP-1"
enable_config="preferred, 0x0, 1.25"
reason="manual"
settle_seconds="2"
retry_interval="0.25"
dry_run="false"

log() {
  printf 'clamshell-mode[%s]: %s\n' "$reason" "$*" >&2
}

read_lid_state() {
  local lid_state_file state_line
  for lid_state_file in /proc/acpi/button/lid/*/state; do
    if [ -r "$lid_state_file" ]; then
      IFS= read -r state_line <"$lid_state_file" || true
      case "$state_line" in
      *open*)
        printf 'open\n'
        return 0
        ;;
      *closed*)
        printf 'closed\n'
        return 0
        ;;
      esac
    fi
  done
  return 1
}

get_monitors_json() {
  if hyprctl monitors all -j >/dev/null 2>&1; then
    hyprctl monitors all -j
  else
    hyprctl monitors -j
  fi
}

usage() {
  cat <<'EOF'
Usage: clamshell-mode.sh [options]
  --reason <startup|lid-open|lid-close|resume|hotplug|manual>
  --settle-seconds <float>
  --retry-interval <float>
  --laptop-output <name>
  --enable-config <hypr monitor value>
  --dry-run
EOF
}

while [ $# -gt 0 ]; do
  case "${1:-}" in
  --reason)
    reason="${2:-}"
    shift 2
    ;;
  --settle-seconds)
    settle_seconds="${2:-}"
    shift 2
    ;;
  --retry-interval)
    retry_interval="${2:-}"
    shift 2
    ;;
  --laptop-output)
    laptop_output="${2:-}"
    shift 2
    ;;
  --enable-config)
    enable_config="${2:-}"
    shift 2
    ;;
  --dry-run)
    dry_run="true"
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    log "unknown argument: $1"
    usage
    exit 2
    ;;
  esac
done

attempts="$(awk -v s="$settle_seconds" -v r="$retry_interval" 'BEGIN {
  if (s + 0 <= 0 || r + 0 <= 0) { print 1; exit }
  a = int((s / r) + 0.999999)
  if (a < 1) a = 1
  print a
}')"

lid_state=""
monitors_json=""
laptop_present="false"
laptop_enabled="false"
external_active_count="0"

attempt="1"
while [ "$attempt" -le "$attempts" ]; do
  lid_state="$(read_lid_state || true)"
  monitors_json="$(get_monitors_json 2>/dev/null || true)"
  if [ -n "$lid_state" ] && [ -n "$monitors_json" ]; then
    laptop_present="$(
      printf '%s\n' "$monitors_json" |
        jq -r --arg laptop_output "$laptop_output" \
          '[.[] | select(.name == $laptop_output)] | length > 0' 2>/dev/null || printf 'false\n'
    )"
    laptop_enabled="$(
      printf '%s\n' "$monitors_json" |
        jq -r --arg laptop_output "$laptop_output" \
          '[.[] | select(.name == $laptop_output) | (.disabled // false) == false] | first // false' 2>/dev/null || printf 'false\n'
    )"
    external_active_count="$(
      printf '%s\n' "$monitors_json" |
        jq -r --arg laptop_output "$laptop_output" \
          '[.[] | select(.name != $laptop_output and ((.disabled // false) == false))] | length' 2>/dev/null || printf '0\n'
    )"

    if [ "$lid_state" = "open" ] || [ "$external_active_count" -gt 0 ] || [ "$attempt" -ge "$attempts" ]; then
      break
    fi
  fi

  if [ "$attempt" -lt "$attempts" ]; then
    sleep "$retry_interval"
  fi
  attempt="$((attempt + 1))"
done

if [ -z "$lid_state" ]; then
  log "unable to read lid state from /proc/acpi/button/lid/*/state"
  exit 1
fi

if [ -z "$monitors_json" ]; then
  log "unable to read monitor state with hyprctl"
  exit 1
fi

if [ "$laptop_present" != "true" ]; then
  log "laptop output '$laptop_output' is not currently present; no action taken"
  exit 0
fi

# Lid closed with an external monitor present -> disable the panel; otherwise
# keep it enabled (lid open, or it's the only screen). Hyprland's headless
# fallback path is patched to survive reaching zero real monitors
# (findings/2026-06-20-hyprland-segv-resume-monitor-race.md), so disabling
# eDP-1 here no longer risks the resume SEGV.
desired_enabled="true"
if [ "$lid_state" = "closed" ] && [ "$external_active_count" -gt 0 ]; then
  desired_enabled="false"
fi

if [ "$desired_enabled" = "$laptop_enabled" ]; then
  log "no change (lid=$lid_state external_active=$external_active_count laptop_enabled=$laptop_enabled)"
  exit 0
fi

if [ "$desired_enabled" = "true" ]; then
  log "enable laptop output '$laptop_output' (lid=$lid_state external_active=$external_active_count)"
  monitor_value="$enable_config"
  verb="Enabling"
else
  log "disable laptop output '$laptop_output' (lid=$lid_state external_active=$external_active_count)"
  monitor_value="disable"
  verb="Disabling"
fi

if [ "$dry_run" = "true" ]; then
  exit 0
fi

command -v notify-send >/dev/null 2>&1 && notify-send "Clamshell Mode" "$verb laptop output" || true
hyprctl keyword monitor "$laptop_output, $monitor_value"
