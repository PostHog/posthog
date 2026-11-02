#!/usr/bin/env bash
# Builds rust/hogql/parser-wasm and writes it to internal/hogqlparser/hogql_parser.wasm, where the Go build embeds it.
set -euo pipefail

service_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rust_dir="$(cd "$service_dir/../../rust" && pwd)"
target=wasm32-wasip1

if command -v rustup >/dev/null 2>&1 && ! rustup target list --installed | grep -qx "$target"; then
    rustup target add "$target"
fi

# An empty RUSTFLAGS overrides rust/.cargo/config.toml, which links macOS build scripts with lld from flox.
# The profile overrides apply only to this build: LTO makes the parser faster, and debug info only adds size.
RUSTFLAGS='' cargo build \
    --manifest-path "$rust_dir/Cargo.toml" \
    --package hogql_parser_wasm \
    --release \
    --target "$target" \
    --config profile.release.lto=true \
    --config profile.release.codegen-units=1 \
    --config profile.release.debug=false \
    --config profile.release.strip=true

cp "$rust_dir/target/$target/release/hogql_parser_wasm.wasm" "$service_dir/internal/hogqlparser/hogql_parser.wasm"
