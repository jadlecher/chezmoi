#!/usr/bin/env bash
set -euo pipefail

# Prefer in-process reload to avoid tearing down the bar surface/exclusive zone.
if pgrep -x waybar >/dev/null 2>&1; then
  pkill -x -SIGUSR2 waybar
else
  waybar >/dev/null 2>&1 &
fi
