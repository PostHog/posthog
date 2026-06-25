#!/usr/bin/env bash
# Regenerate the committed oracle fixtures (tests/static/stl_oracle.json + perf_*.json) from the
# reference Python HogVM. Run after adding/altering STL cases in gen_stl_oracle.py or the perf
# workload. Provisions the oracle venv first (idempotent).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$DIR" rev-parse --show-toplevel 2>/dev/null || (cd "$DIR/../../../.." && pwd))"
VENV="${HOGVM_ORACLE_VENV:-$HOME/.hogvm-oracle-venv}"

"$DIR/setup_oracle.sh"

cd "$ROOT"
PYTHONPATH=.:common "$VENV/bin/python" rust/common/hogvm/scripts/gen_stl_oracle.py
PYTHONPATH=.:common "$VENV/bin/python" rust/common/hogvm/scripts/gen_perf_workload.py
