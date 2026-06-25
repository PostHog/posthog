#!/usr/bin/env bash
# Run the HogVM Rust↔Node parity harness (tests/parity.rs).
#
# Why the isolated crate: the full rust workspace pulls github.com git deps (via cymbal) that
# some sandboxes block, and cargo resolves every workspace member even for `-p hogvm`. hogvm
# itself only needs crates.io deps, so we build it in a throwaway crate that *symlinks the live
# src/ and tests/* — real source, real edits, no cymbal resolution. On a normal dev box / CI you
# don't need this; just run:
#   HOGVM_CORPUS_DIR=$PWD/common/hogvm/__tests__ cargo test -p hogvm --test parity -- --nocapture
set -euo pipefail

# Repo root: prefer git, fall back to walking up from this script.
if ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then :; else
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fi
HOGVM="$ROOT/rust/common/hogvm"
CORPUS="$ROOT/common/hogvm/__tests__"
ISO="${HOGVM_PARITY_BUILD_DIR:-${TMPDIR:-/tmp}/hogvm-parity-iso}"

mkdir -p "$ISO"
ln -sfn "$HOGVM/src" "$ISO/src"
ln -sfn "$HOGVM/tests" "$ISO/tests"
cat > "$ISO/Cargo.toml" <<'EOF'
[package]
name = "hogvm"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1.0", features = ["derive"] }
serde_json = { version = "1.0" }
thiserror = { version = "2.0" }
regex = "1.11.1"
rand = "0.8.5"
chrono = { version = "0.4.44", features = ["default", "serde"] }
chrono-tz = "0.10.1"
EOF

cd "$ISO"
# Corpus parity (whole programs) + per-STL parity (one case per STL function).
HOGVM_CORPUS_DIR="$CORPUS" cargo test --test parity --test stl_parity -- --nocapture "$@"
