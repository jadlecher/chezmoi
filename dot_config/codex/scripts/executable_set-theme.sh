#!/usr/bin/env bash
set -euo pipefail

theme="${1:-}"
case "$theme" in
  light)
    codex_theme="catppuccin-latte"
    ;;
  dark)
    codex_theme="catppuccin-mocha"
    ;;
  *)
    echo "Unknown theme '$theme'" >&2
    exit 1
    ;;
esac

if ! command -v codex >/dev/null 2>&1; then
  echo "warning: codex not installed; skipping codex theme update" >&2
  exit 0
fi

cfg="${HOME}/.codex/config.toml"
cfg_dir="$(dirname "$cfg")"
tmp="$(mktemp "${cfg}.tmp.XXXXXX")"

mkdir -p "$cfg_dir"
[ -f "$cfg" ] || : >"$cfg"

awk -v codex_theme="$codex_theme" '
  BEGIN {
    in_tui = 0
    saw_tui = 0
    saw_theme = 0
  }

  function emit_missing_tui_keys() {
    if (!saw_theme) {
      print "theme = \"" codex_theme "\""
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
    if (in_tui && $0 ~ /^[[:space:]]*theme[[:space:]]*=/) {
      print "theme = \"" codex_theme "\""
      saw_theme = 1
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
      print "theme = \"" codex_theme "\""
    }
  }
' "$cfg" >"$tmp"

mv "$tmp" "$cfg"
