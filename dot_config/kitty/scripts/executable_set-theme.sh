#!/bin/bash -e
theme=$(gsettings get org.gnome.desktop.interface color-scheme | grep -oE "light|dark")
case $theme in
light)
  theme="Catppuccin-Latte"
  ;;
dark)
  theme="Catppuccin-Mocha"
  ;;
*)
  echo "could not determine current theme"
  exit 1
  ;;
esac
echo setting kitty theme to $theme

# Generate pure theme contents and write only the include target file.
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/kitty"
config_file="$config_dir/current-theme.conf"
mkdir -p "$config_dir"
kitty +kitten themes --dump-theme "$theme" >"$config_file"

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
