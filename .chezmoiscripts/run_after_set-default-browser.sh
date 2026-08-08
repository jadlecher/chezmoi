#!/bin/sh

set -eu

if ! command -v xdg-settings >/dev/null 2>&1; then
    exit 0
fi

desktop_entry_for() {
    browser="$1"
    search_dirs="${XDG_DATA_HOME:-$HOME/.local/share}:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

    old_ifs=$IFS
    IFS=:
    set -- $search_dirs
    IFS=$old_ifs

    for data_dir do
        [ -n "$data_dir" ] || continue
        applications_dir="$data_dir/applications"
        [ -d "$applications_dir" ] || continue

        for desktop_path in "$applications_dir"/*.desktop; do
            [ -f "$desktop_path" ] || continue

            if awk -v browser="$browser" '
                function first_word(command, words) {
                    sub(/^[[:space:]]+/, "", command)
                    split(command, words, /[[:space:]]+/)
                    sub(/^.*\//, "", words[1])
                    return words[1]
                }

                $0 == "[Desktop Entry]" {
                    in_desktop_entry = 1
                    next
                }

                in_desktop_entry && /^\[/ {
                    in_desktop_entry = 0
                }

                in_desktop_entry && /^Type=/ {
                    type = substr($0, 6)
                }

                in_desktop_entry && /^Exec=/ && exec_line == "" {
                    exec_line = substr($0, 6)
                }

                in_desktop_entry && /^MimeType=/ {
                    mime_types = substr($0, 10)
                }

                in_desktop_entry && /^Hidden=/ {
                    hidden = substr($0, 8)
                }

                in_desktop_entry && /^NoDisplay=/ {
                    no_display = substr($0, 11)
                }

                END {
                    hidden = tolower(hidden)
                    no_display = tolower(no_display)
                    valid_mime_types = mime_types ~ /(^|;)x-scheme-handler\/http(;|$)/ &&
                        mime_types ~ /(^|;)x-scheme-handler\/https(;|$)/

                    if (type == "Application" &&
                        first_word(exec_line) == browser &&
                        valid_mime_types &&
                        hidden != "true" &&
                        no_display != "true") {
                        exit 0
                    }

                    exit 1
                }
            ' "$desktop_path"; then
                printf '%s\n' "${desktop_path##*/}"
                return 0
            fi
        done
    done

    return 1
}

desktop_id=""

if command -v qutebrowser >/dev/null 2>&1; then
    desktop_id="$(desktop_entry_for qutebrowser || true)"
fi

if [ -z "$desktop_id" ] && command -v firefox >/dev/null 2>&1; then
    desktop_id="$(desktop_entry_for firefox || true)"
fi

[ -n "$desktop_id" ] || exit 0

# xdg-settings refuses to change the setting when BROWSER is exported. The
# shell environment itself remains unchanged for applications that honor it.
env -u BROWSER xdg-settings set default-web-browser "$desktop_id" >/dev/null 2>&1 ||
    printf 'warning: unable to set default web browser to %s\n' "$desktop_id" >&2
