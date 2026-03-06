#!/bin/bash -e
config_dir="$HOME/.config/hypr"
input_dir="$config_dir/conf-available"
output_dir="$config_dir/conf-enabled"
wallpaper_conf="$config_dir/wallpapers.yaml"
"$config_dir/scripts/set-theme.py" -i "$input_dir" -o "$output_dir" -w "$wallpaper_conf"
# The config sync above may trigger a Hyprland config reload that re-enables eDP-1
# via monitor.conf, overriding clamshell-mode. Re-apply clamshell state to correct this.
"$config_dir/scripts/clamshell-mode.sh" --reason set-theme --settle-seconds 2 --retry-interval 0.5 || true
