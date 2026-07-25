#!/usr/bin/env bash

set -euo pipefail

theme="${1:-}"
case "$theme" in
  light)
    skin="catppuccin-latte"
    ;;
  dark)
    skin="catppuccin-mocha"
    ;;
  *)
    echo "Unknown theme '$theme'" >&2
    exit 1
    ;;
esac

if ! command -v k9s >/dev/null 2>&1; then
  echo "warning: k9s not installed; skipping k9s theme update" >&2
  exit 0
fi

config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/k9s"
config_file="$config_dir/config.yaml"
skin_file="$config_dir/skins/$skin.yaml"

if [[ ! -f "$skin_file" ]]; then
  echo "missing k9s skin file: $skin_file" >&2
  exit 1
fi

mkdir -p "$config_dir"
tmp="$(mktemp "$config_file.tmp.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

if [[ ! -f "$config_file" ]]; then
  cat >"$tmp" <<EOF
k9s:
  ui:
    skin: $skin
EOF
else
  awk -v skin="$skin" '
    function indent(line,    match_length) {
      match(line, /^[[:space:]]*/)
      return RLENGTH
    }

    function emit_skin() {
      if (!saw_skin) {
        printf "%*s%s\n", ui_indent + 2, "", "skin: " skin
        saw_skin = 1
      }
    }

    BEGIN {
      in_k9s = 0
      in_ui = 0
      saw_k9s = 0
      saw_ui = 0
      saw_skin = 0
      ui_indent = 0
    }

    {
      line_indent = indent($0)

      if (in_ui && $0 !~ /^[[:space:]]*($|#)/ && line_indent <= ui_indent) {
        emit_skin()
        in_ui = 0
      }

      if (in_k9s && $0 !~ /^[[:space:]]*($|#)/ && line_indent == 0 && $0 !~ /^k9s:[[:space:]]*/) {
        if (!saw_ui) {
          print "  ui:"
          print "    skin: " skin
          saw_ui = 1
          saw_skin = 1
        }
        in_k9s = 0
      }

      if ($0 ~ /^k9s:[[:space:]]*(#.*)?$/) {
        in_k9s = 1
        saw_k9s = 1
        print
        next
      }

      if (in_k9s && $0 ~ /^[[:space:]]{2}ui:[[:space:]]*(#.*)?$/) {
        in_ui = 1
        saw_ui = 1
        ui_indent = line_indent
        print
        next
      }

      if (in_ui && line_indent > ui_indent && $0 ~ /^[[:space:]]*skin:[[:space:]]*/) {
        printf "%*sskin: %s\n", line_indent, "", skin
        saw_skin = 1
        next
      }

      print
    }

    END {
      if (in_ui) {
        emit_skin()
      } else if (in_k9s && !saw_ui) {
        print "  ui:"
        print "    skin: " skin
        saw_ui = 1
      } else if (!saw_k9s) {
        if (NR > 0) {
          print ""
        }
        print "k9s:"
        print "  ui:"
        print "    skin: " skin
      }
    }
  ' "$config_file" >"$tmp"
fi

mv "$tmp" "$config_file"
trap - EXIT
echo "setting k9s skin to $skin"
