#!/bin/sh
# Ensure the Hyprland wayland session uses dbus-run-session.
# On OpenRC (no systemd --user), DBUS_SESSION_BUS_ADDRESS is not set
# automatically. This wraps start-hyprland with dbus-run-session so that all
# Hyprland child processes get a proper session bus.
#
# This must be run_always because portage can overwrite the desktop file on
# gui-wm/hyprland upgrades.
set -eu

DESKTOP=/usr/share/wayland-sessions/hyprland.desktop
WANT='Exec=dbus-run-session -- /usr/bin/start-hyprland'

if ! grep -qF "$WANT" "$DESKTOP" 2>/dev/null; then
    sudo sed -i 's|^Exec=.*|'"$WANT"'|' "$DESKTOP"
fi
