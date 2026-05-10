#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: session.sh <ensure|reload|reconcile|restart>
EOF
}

command_name="${1:-}"
case "$command_name" in
  ensure | reload | reconcile | restart)
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

runtime_dir="${XDG_RUNTIME_DIR:-/tmp}"
lock_file="$runtime_dir/waybar-session.lock"
signature_file="$runtime_dir/waybar-session.outputs"
config_dir="$HOME/.config/waybar"
theme_dir="$config_dir/themes"
palette_link="$theme_dir/current.css"
style_file="$config_dir/style-current.css"
default_palette="mocha.css"

ensure_style_files() {
  mkdir -p "$theme_dir"

  if [[ ! -e "$palette_link" ]]; then
    ln -s "$default_palette" "$palette_link"
  fi

  if [[ ! -f "$style_file" ]]; then
    cat >"$style_file" <<'EOF'
@import "./themes/current.css";
@import "./style.css";
EOF
  fi
}

start_waybar() {
  waybar -s "$style_file" 9>&- >/dev/null 2>&1 &
}

restart_waybar() {
  pkill -x waybar || true
  sleep 0.1
  start_waybar
}

collect_waybar_pids() {
  mapfile -t waybar_pids < <(pgrep -x waybar || true)
}

send_reload() {
  local pid
  for pid in "${waybar_pids[@]}"; do
    kill -SIGUSR2 "$pid" 2>/dev/null || true
  done
}

get_output_signature() {
  local monitors_json=""

  if ! command -v hyprctl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
    return 0
  fi

  if monitors_json="$(hyprctl monitors all -j 2>/dev/null)"; then
    :
  elif monitors_json="$(hyprctl monitors -j 2>/dev/null)"; then
    :
  else
    return 0
  fi

  printf '%s\n' "$monitors_json" |
    jq -r '[.[] | select((.disabled // false) == false) | .name] | sort | join(",")' 2>/dev/null || true
}

read_stored_signature() {
  if [[ -f "$signature_file" ]]; then
    cat "$signature_file"
  fi
}

write_signature() {
  local signature="${1:-}"
  printf '%s\n' "$signature" >"$signature_file"
}

exec 9>"$lock_file"
flock -x 9

ensure_style_files
collect_waybar_pids
current_signature="$(get_output_signature)"
stored_signature="$(read_stored_signature)"

case "$command_name" in
  ensure)
    if (( ${#waybar_pids[@]} == 0 )); then
      start_waybar
    fi
    write_signature "$current_signature"
    ;;
  reload)
    if (( ${#waybar_pids[@]} == 0 )); then
      start_waybar
    elif (( ${#waybar_pids[@]} == 1 )); then
      send_reload
    else
      restart_waybar
    fi
    write_signature "$current_signature"
    ;;
  restart)
    restart_waybar
    write_signature "$current_signature"
    ;;
  reconcile)
    if (( ${#waybar_pids[@]} == 0 )); then
      start_waybar
    elif (( ${#waybar_pids[@]} == 1 )); then
      if [[ -n "$current_signature" ]] && [[ -n "$stored_signature" ]] && [[ "$current_signature" != "$stored_signature" ]]; then
        restart_waybar
      else
        send_reload
      fi
    else
      restart_waybar
    fi
    write_signature "$current_signature"
    ;;
esac
