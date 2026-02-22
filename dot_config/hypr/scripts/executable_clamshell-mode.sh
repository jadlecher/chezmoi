#!/bin/sh -e
laptop_output="eDP-1"
output_count=$(hyprctl monitors -j | jq length)
lid_state_file=/proc/acpi/button/lid/LID0/state
read -r LS <"$lid_state_file"

enabled=$(hyprctl monitors -j | jq '.[] | select(.name=="'$laptop_output'") | .disabled == false') || false
enable=true
case "$LS" in
*open) ;;
*closed)
  # if lid closed and more than one output, disable laptop output
  if [ "$output_count" -gt 1 ]; then
    enable=false
  fi
  ;;
*)
  echo "Could not get lid state" >&2
  exit 1
  ;;
esac

if [ $enable != $enabled ]; then
  verb=Disabling
  if $enable; then verb=Enabling; fi
  notify-send "Clamshell Mode" "$verb laptop output"
  value=disable
  if $enable; then value="preferred, 0x0, 1.25"; fi
  hyprctl keyword monitor "$laptop_output, $value"
fi
