#!/bin/sh
set -eu

cfg="${HOME}/.codex/config.toml"
cfg_dir="$(dirname "$cfg")"
tmp="$(mktemp "${cfg}.tmp.XXXXXX")"

mkdir -p "$cfg_dir"
[ -f "$cfg" ] || : >"$cfg"

awk '
  BEGIN {
    in_tui = 0
    saw_tui = 0
    saw_notifications = 0
    saw_min_timeout = 0
  }

  function emit_missing_tui_keys() {
    if (!saw_notifications) {
      print "notifications = [\"approval-requested\"]"
    }
    if (!saw_min_timeout) {
      print "notifications_min_timeout_ms = 0"
    }
  }

  /^\[[^]]+\][[:space:]]*$/ {
    if (in_tui) {
      emit_missing_tui_keys()
      in_tui = 0
    }
    if ($0 == "[tui]") {
      saw_tui = 1
      in_tui = 1
      print
      next
    }
    print
    next
  }

  {
    if (in_tui && $0 ~ /^[[:space:]]*notifications[[:space:]]*=/) {
      print "notifications = [\"approval-requested\"]"
      saw_notifications = 1
      next
    }
    if (in_tui && $0 ~ /^[[:space:]]*notifications_min_timeout_ms[[:space:]]*=/) {
      print "notifications_min_timeout_ms = 0"
      saw_min_timeout = 1
      next
    }
    print
  }

  END {
    if (in_tui) {
      emit_missing_tui_keys()
    } else if (!saw_tui) {
      if (NR > 0) {
        print ""
      }
      print "[tui]"
      print "notifications = [\"approval-requested\"]"
      print "notifications_min_timeout_ms = 0"
    }
  }
' "$cfg" >"$tmp"

mv "$tmp" "$cfg"
