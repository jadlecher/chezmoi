#!/bin/bash -e
config_dir="$HOME/.config/hypr"
wallpaper_conf="$config_dir/wallpapers.yaml"

"$config_dir/scripts/set-theme.py" \
  --wallpaper-only \
  --wallpaper-retries 10 \
  --wallpaper-retry-delay 0.2 \
  -w "$wallpaper_conf"
