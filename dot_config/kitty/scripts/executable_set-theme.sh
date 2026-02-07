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
kitty +kitten themes --reload-in=all $theme
