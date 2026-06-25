#!/usr/bin/env bash
# Build the napi-rs FFI binding (Rust-from-Node) and run the FFI perf harness.
# Uses the isolated hogvm crate so it builds in sandboxes that block the workspace's github deps.
# In an unrestricted environment you can build the real crate directly:
#   (cd rust/common/hogvm/node && cargo build --release) && node rust/common/hogvm/benches/ingestion_ffi.js
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_iso_build.sh"  # sets ROOT, HOGVM, ISO (isolated hogvm crate)

ISONODE="${ISO}-node"
mkdir -p "$ISONODE/src"
ln -sfn "$HOGVM/node/src/lib.rs" "$ISONODE/src/lib.rs"
ln -sfn "$HOGVM/node/build.rs" "$ISONODE/build.rs"
cat > "$ISONODE/Cargo.toml" <<EOF
[package]
name = "hogvm-node"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
hogvm = { path = "$ISO" }
napi = { version = "2", default-features = false, features = ["napi8", "serde-json"] }
napi-derive = "2"
rayon = "1.10"
serde_json = "1.0"

[build-dependencies]
napi-build = "2"
EOF

cd "$ISONODE"
cargo build --release
so="$(ls target/release/libhogvm_node.so 2>/dev/null || ls target/release/*.so | head -1)"
cp "$so" "$HOGVM/node/hogvm-node.node"
echo "built binding -> $HOGVM/node/hogvm-node.node"
node "$HOGVM/benches/ingestion_ffi.js"
