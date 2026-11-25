#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

if ! command -v cargo >/dev/null 2>&1; then
    cargo_home=${CARGO_HOME:-${HOME:+$HOME/.cargo}}
    if [ -z "$cargo_home" ] || [ ! -x "$cargo_home/bin/cargo" ]; then
        printf '%s\n' 'Cargo is required to run the checks. Install the Rust toolchain or add Cargo to PATH.' >&2
        exit 127
    fi
    export PATH="$cargo_home/bin:$PATH"
fi

cargo fmt --all -- --check
cargo clippy --locked --workspace --all-targets --features meep-render/ui-tests --no-deps -- -D warnings
cargo test --locked --workspace --features meep-render/ui-tests
