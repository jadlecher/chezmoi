#!/usr/bin/env bash
set -euo pipefail

action="${1:-}"

notify() {
  if command -v notify-send >/dev/null 2>&1; then
    notify-send "Screenshot" "$1"
  else
    printf 'Screenshot: %s\n' "$1" >&2
  fi
}

fail() {
  notify "Error: $1"
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "missing command: $1"
  fi
}

resolve_screenshot_dir() {
  if [ -n "${SCREENSHOT_DIR:-}" ]; then
    printf '%s\n' "$SCREENSHOT_DIR"
    return 0
  fi

  if [ -n "${XDG_PICTURES_DIR:-}" ]; then
    printf '%s/Screenshots\n' "$XDG_PICTURES_DIR"
    return 0
  fi

  printf '%s/Pictures/Screenshots\n' "$HOME"
}

timestamp() {
  date "+%Y-%m-%d_%H-%M-%S"
}

copy_file_to_clipboard() {
  local file="$1"
  wl-copy <"$file"
}

capture_with_hyprshot() {
  local mode="$1"
  local out_dir="$2"
  local file_name="$3"
  shift 3

  for mode in "$mode" "$@"; do
    if hyprshot -m "$mode" -o "$out_dir" -f "$file_name" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

capture_clipboard_only() {
  local mode="$1"
  hyprshot -m "$mode" --clipboard-only >/dev/null
}

annotate_region() {
  local final_path="$1"
  local tmp_file
  tmp_file="$(mktemp --tmpdir screenshot-region-XXXXXX.png)"
  trap 'rm -f "$tmp_file"' EXIT

  grim -g "$(slurp)" "$tmp_file"
  satty --filename "$tmp_file" --fullscreen --early-exit --output-filename "$final_path"

  if [ ! -s "$final_path" ]; then
    fail "annotation did not produce an output image"
  fi

  copy_file_to_clipboard "$final_path"
  notify "Annotated region saved to $final_path and copied"
}

case "$action" in
region | window | output)
  require_cmd hyprshot
  require_cmd wl-copy

  screenshot_dir="$(resolve_screenshot_dir)"
  mkdir -p "$screenshot_dir"
  file_name="screenshot_$(timestamp)_${action}.png"
  file_path="$screenshot_dir/$file_name"

  case "$action" in
  region)
    capture_with_hyprshot "region" "$screenshot_dir" "$file_name" || fail "capture failed for mode '$action'"
    ;;
  window)
    capture_with_hyprshot "window" "$screenshot_dir" "$file_name" "active" || fail "capture failed for mode '$action'"
    ;;
  output)
    capture_with_hyprshot "output" "$screenshot_dir" "$file_name" "monitor" || fail "capture failed for mode '$action'"
    ;;
  esac

  if [ ! -s "$file_path" ]; then
    fail "capture failed for mode '$action'"
  fi

  copy_file_to_clipboard "$file_path"
  notify "Saved $action capture to $file_path and copied"
  ;;
region-clipboard)
  require_cmd hyprshot
  capture_clipboard_only "region"
  notify "Region capture copied to clipboard"
  ;;
annotate-region)
  require_cmd grim
  require_cmd slurp
  require_cmd satty
  require_cmd wl-copy

  screenshot_dir="$(resolve_screenshot_dir)"
  mkdir -p "$screenshot_dir"
  file_path="$screenshot_dir/screenshot_$(timestamp)_annotated-region.png"
  annotate_region "$file_path"
  ;;
"" | -h | --help)
  cat <<'EOF'
Usage: screenshot.sh <action>
Actions:
  region            Save region screenshot and copy to clipboard.
  window            Save active-window screenshot and copy to clipboard.
  output            Save current output screenshot and copy to clipboard.
  region-clipboard  Capture region directly to clipboard only.
  annotate-region   Capture region, annotate in satty, save and copy.
EOF
  ;;
*)
  fail "unknown action: $action"
  ;;
esac
