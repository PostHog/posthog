#!/usr/bin/env bash
# HogVM parity-loop dashboard: runs both correctness harnesses (corpus parity + per-STL parity)
# and prints the current pass/fail counts and the backlog. This is the "where are we / what's next"
# command for the loop — run it, pick the top failing item, implement it in src/stl.rs (or fix the
# value-model bug), re-run. Uses committed oracle fixtures, so no venv needed just to check status.
#
# Iteration procedure (also in PARITY_LOOP.md §5):
#   1. ./scripts/loop.sh                  # see the backlog
#   2. implement the next STL fn / fix    # src/stl.rs etc., matching the reference
#   3. ./scripts/loop.sh                  # confirm the count climbed, no regressions
#   4. commit + push the increment
# To add NEW test cases first: edit gen_stl_oracle.py, then ./scripts/regen_oracles.sh.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/run_parity.sh" "$@"
