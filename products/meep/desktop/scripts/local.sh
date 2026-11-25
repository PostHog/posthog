#!/bin/sh
# Run the native desktop against the Meep API in this PostHog checkout.
set -eu
cd "$(dirname "$0")/.."
export MEEP_DEV_DIR="${MEEP_DEV_DIR:-$PWD/.local/meep-dev}"
export MEEP_POSTHOG_LOCAL=1
cargo build --locked --manifest-path ../domain/Cargo.toml
case "${1:-}" in
    --hot) shift; exec sh scripts/dev.sh --local "$@" ;;
    "") exec cargo run --locked -p meep -- --posthog local ;;
    *) echo 'Usage: sh scripts/local.sh [--hot]' >&2; exit 2 ;;
esac
