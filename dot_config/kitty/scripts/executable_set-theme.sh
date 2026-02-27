#!/bin/bash -e
theme_variant=$(gsettings get org.gnome.desktop.interface color-scheme | grep -oE "light|dark")
case $theme_variant in
light)
  kitty_theme="Catppuccin-Latte"
  ;;
dark)
  kitty_theme="Catppuccin-Mocha"
  ;;
*)
  echo "could not determine current theme"
  exit 1
  ;;
esac
echo setting kitty theme to $kitty_theme

# Generate pure theme contents and write only the include target file.
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/kitty"
theme_config_file="$config_dir/current-theme.conf"
background_config_file="$config_dir/current-background.conf"
mkdir -p "$config_dir"
kitty +kitten themes --dump-theme "$kitty_theme" >"$theme_config_file"

kernel_release="$(uname -r 2>/dev/null || true)"
is_wsl=0
if [[ "${kernel_release,,}" == *microsoft* ]] || [[ "${kernel_release,,}" == *wsl* ]]; then
  is_wsl=1
fi

if (( is_wsl == 1 )); then
  media_dir="${XDG_CONFIG_HOME:-$HOME/.config}/media"
  consumer_file="$media_dir/consumers/kitty.yaml"
  resolver="$media_dir/scripts/image-resolve.py"
  catalog="$media_dir/image-catalog.yaml"
  local_catalog="$media_dir/image-catalog.local.yaml"
  asset="$(
    python3 - "$consumer_file" "$theme_variant" <<'PY'
import pathlib
import sys

import yaml

consumer_file = pathlib.Path(sys.argv[1]).expanduser()
variant = sys.argv[2]
if not consumer_file.is_file():
    raise SystemExit(0)
try:
    data = yaml.safe_load(consumer_file.read_text(encoding="utf-8")) or {}
except Exception:
    raise SystemExit(0)

if not data.get("enabled", False):
    raise SystemExit(0)

variants = data.get("variants", {})
asset = variants.get(variant)
if isinstance(asset, str):
    print(asset)
PY
  )"

  resolved_image=""
  if [[ -n "$asset" ]] && [[ -f "$resolver" ]]; then
    resolved_image="$(
      "$resolver" \
        --asset "$asset" \
        --variant "$theme_variant" \
        --fetch never \
        --catalog "$catalog" \
        --local-catalog "$local_catalog" \
        2>/dev/null || true
    )"
  fi

  if [[ -n "$resolved_image" ]] && [[ -f "$resolved_image" ]]; then
    escaped_image="${resolved_image//\\/\\\\}"
    escaped_image="${escaped_image//\"/\\\"}"
    {
      echo "background_opacity 1.0"
      echo "background_image \"$escaped_image\""
      echo "background_image_layout scaled"
    } >"$background_config_file"
  else
    {
      echo "background_opacity 1.0"
      echo "background_image none"
    } >"$background_config_file"
  fi
else
  {
    echo "background_opacity .80"
    echo "background_image none"
  } >"$background_config_file"
fi

# Reload kitty config so all dynamic theme settings are applied live.
remote_conf="$config_dir/conf.d/remote-control.conf"
configured_socket="$(awk '$1 == "listen_on" { print $2; exit }' "$remote_conf" 2>/dev/null || true)"
socket="${KITTY_LISTEN_ON:-${configured_socket:-unix:/tmp/kitty}}"

declare -A seen_targets
targets=("$socket")
for sock in /tmp/kitty /tmp/kitty-*; do
  if [[ -S "$sock" ]]; then
    targets+=("unix:$sock")
  fi
done

for target in "${targets[@]}"; do
  if [[ -n "${seen_targets[$target]:-}" ]]; then
    continue
  fi
  seen_targets["$target"]=1
  kitty @ --to "$target" load-config "$config_dir/kitty.conf" >/dev/null 2>&1 || true
done

# Fallback when running inside kitty without a usable socket target above.
kitty @ load-config "$config_dir/kitty.conf" >/dev/null 2>&1 || true
