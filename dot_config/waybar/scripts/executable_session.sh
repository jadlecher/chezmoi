#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: session.sh <ensure|reload|reconcile>
EOF
}

command_name="${1:-}"
case "$command_name" in
  ensure | reload | reconcile)
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
  waybar -s "$style_file" >/dev/null 2>&1 &
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

exec 9>"$lock_file"
flock -x 9

ensure_style_files
collect_waybar_pids

case "$command_name" in
  ensure)
    if (( ${#waybar_pids[@]} == 0 )); then
      start_waybar
    fi
    ;;
  reload)
    if (( ${#waybar_pids[@]} == 0 )); then
      start_waybar
    elif (( ${#waybar_pids[@]} == 1 )); then
      send_reload
    else
      pkill -x waybar || true
      sleep 0.1
      start_waybar
    fi
    ;;
  reconcile)
    if (( ${#waybar_pids[@]} == 0 )); then
      start_waybar
    elif (( ${#waybar_pids[@]} == 1 )); then
      send_reload
    else
      pkill -x waybar || true
      sleep 0.1
      start_waybar
    fi
    ;;
esac
