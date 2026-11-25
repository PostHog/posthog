#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
cargo build --locked --release -p meep-server -p meep --bins
exec cargo run --locked --release -p meep -- "$@"
