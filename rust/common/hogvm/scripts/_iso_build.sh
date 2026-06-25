# Sourced by run_parity.sh / run_perf.sh — materializes an isolated crate that symlinks the
# live hogvm src/tests/benches and depends only on crates.io. This sidesteps the github git deps
# the full rust workspace pulls in (which some sandboxes block) while still building/editing the
# real source. On a normal dev box / CI you don't need this — build hogvm directly in the workspace.
#
# Exports: ROOT, HOGVM, CORPUS, ISO.
if ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then :; else
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fi
export ROOT
export HOGVM="$ROOT/rust/common/hogvm"
export CORPUS="$ROOT/common/hogvm/__tests__"
export ISO="${HOGVM_PARITY_BUILD_DIR:-${TMPDIR:-/tmp}/hogvm-parity-iso}"

mkdir -p "$ISO"
ln -sfn "$HOGVM/src" "$ISO/src"
ln -sfn "$HOGVM/tests" "$ISO/tests"
ln -sfn "$HOGVM/benches" "$ISO/benches"
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

[dev-dependencies]
rayon = "1.10"

[[bench]]
name = "ingestion"
harness = false
EOF
