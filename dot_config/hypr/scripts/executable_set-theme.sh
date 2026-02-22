#!/bin/bash -e
config_dir="$HOME/.config/hypr"
input_dir="$config_dir/conf-available"
output_dir="$config_dir/conf-enabled"
wallpaper_conf="$config_dir/wallpapers.yaml"
"$config_dir/scripts/set-theme.py" -i "$input_dir" -o "$output_dir" -w "$wallpaper_conf"
