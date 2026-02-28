#!/usr/bin/env bash
set -euo pipefail

# Avoid forced reloads to minimize visible flicker during theme changes.
# Waybar can switch between style-light.css / style-dark.css based on system theme.
if ! pgrep -x waybar >/dev/null 2>&1; then
  waybar >/dev/null 2>&1 &
fi
