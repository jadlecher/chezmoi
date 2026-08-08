#!/bin/sh

set -eu

if ! command -v wt >/dev/null 2>&1 || ! command -v fish >/dev/null 2>&1; then
    exit 0
fi

wt config shell install fish
