#!/bin/sh
# Clean only this checkout's disposable files. Apps are installed beside Cargo profiles.
set -eu
cd "$(dirname "$0")/.."

case "$#:${1:-}" in
    0:|1:--build) ;;
    *) echo 'Usage: sh scripts/clean.sh [--build]' >&2; exit 2 ;;
esac

if [ "${1:-}" = --build ] && [ -L target ]; then
    echo 'Skipping cleanup because target is a symlink.' >&2
    exit 1
fi

rm -rf -- .scratch
if [ "${1:-}" = --build ]; then
    # Cargo puts .fingerprint in each compiled profile, including cross-target profiles.
    for profile in target/debug target/release target/*/debug target/*/release; do
        [ ! -L "${profile%/*}" ] && [ ! -L "$profile" ] && [ -d "$profile/.fingerprint" ] || continue
        echo "Removing $profile"
        rm -rf -- "$profile"
    done
fi
