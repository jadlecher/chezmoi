#!/usr/bin/env fish

set -l theme "$argv[1]"
if not contains -- "$theme" light dark
    echo "Unknown theme '$theme'" >&2
    exit 1
end

fish_config theme choose catppuccin-mocha --color-theme="$theme" >/dev/null
or exit 1

set -U fish_catppuccin_theme "$theme"
