#!/usr/bin/env bash
# Run the HogVM ingestion-batch perf harness (pure-Rust single vs rayon-parallel).
# In an unrestricted environment: cargo bench -p hogvm --bench ingestion
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_iso_build.sh"
cd "$ISO"
cargo bench --bench ingestion "$@"
