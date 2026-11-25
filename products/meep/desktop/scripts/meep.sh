#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec cargo run --locked --release -p meep -- "$@"
