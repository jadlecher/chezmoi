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
base_style="$config_dir/style.css"
theme_dir="$config_dir/themes"
case "$theme" in
  dark) palette_name="mocha.css" ;;
  light) palette_name="latte.css" ;;
esac
palette_style="$theme_dir/$palette_name"
current_palette="$theme_dir/current.css"
current_style="$config_dir/style-current.css"
legacy_cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/waybar"
legacy_style="$legacy_cache_dir/style-current.css"
session_script="$config_dir/scripts/session.sh"

if [[ ! -f "$palette_style" ]]; then
  echo "missing palette style file: $palette_style" >&2
  exit 1
fi

if [[ ! -f "$base_style" ]]; then
  echo "missing base style file: $base_style" >&2
  exit 1
fi

mkdir -p "$theme_dir"
ln -sfn "$palette_name" "$current_palette"

new_style="$(mktemp "$config_dir/style-current.css.tmp.XXXXXX")"
cat >"$new_style" <<EOF
@import "./themes/current.css";
@import "./style.css";
EOF
if [[ ! -f "$current_style" ]] || ! cmp -s "$new_style" "$current_style"; then
  mv "$new_style" "$current_style"
else
  rm -f "$new_style"
fi

# Backward compatibility for existing waybar processes launched with
# ~/.cache/waybar/style-current.css in older setups.
mkdir -p "$legacy_cache_dir"
legacy_new_style="$(mktemp "$legacy_cache_dir/style-current.css.tmp.XXXXXX")"
cat >"$legacy_new_style" <<EOF
@import "$current_palette";
@import "$base_style";
EOF
if [[ ! -f "$legacy_style" ]] || ! cmp -s "$legacy_new_style" "$legacy_style"; then
  mv "$legacy_new_style" "$legacy_style"
else
  rm -f "$legacy_new_style"
fi

if [[ ! -x "$session_script" ]]; then
  echo "missing session script: $session_script" >&2
  exit 1
fi

"$session_script" restart
