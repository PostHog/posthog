#!/usr/bin/env bash
# Run the HogVM correctness parity harnesses: whole-program corpus parity + per-STL parity.
# In an unrestricted environment you can skip the isolated build and run directly:
#   HOGVM_CORPUS_DIR=$PWD/common/hogvm/__tests__ cargo test -p hogvm --test parity --test stl_parity -- --nocapture
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_iso_build.sh"
cd "$ISO"
HOGVM_CORPUS_DIR="$CORPUS" cargo test --test parity --test stl_parity -- --nocapture "$@"
