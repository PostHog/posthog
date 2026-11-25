#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ "${1:-}" = "--legacy" ]; then cargo build --locked --release -p meep-server; fi
exec cargo run --locked --release -p meep -- "$@"
