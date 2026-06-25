#!/usr/bin/env bash
# Idempotently provision the HogVM reference-oracle venv.
#
# The parity loop diffs the Rust VM against the *reference* Python HogVM, which needs two pypi
# packages (re2 + pytz) the bare interpreter lacks. This builds a tiny dedicated venv for them.
# Running the loop against the COMMITTED oracle fixtures does not need this — only (re)generating
# or expanding cases does (scripts/regen_oracles.sh). Safe to run repeatedly; exits fast if ready.
#
# Venv path: $HOGVM_ORACLE_VENV (default ~/.hogvm-oracle-venv). The reference VM is insensitive to
# the exact Python patch version, so we use whatever 3.13 is available rather than the project's pin.
set -euo pipefail

VENV="${HOGVM_ORACLE_VENV:-$HOME/.hogvm-oracle-venv}"
PY="$VENV/bin/python"

if [ -x "$PY" ] && "$PY" -c "import re2, pytz" >/dev/null 2>&1; then
  echo "hogvm oracle venv ready: $VENV"
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "WARN: uv not found; cannot provision hogvm oracle venv" >&2
  exit 1
fi

uv venv --python 3.13 "$VENV" >/dev/null 2>&1 || uv venv "$VENV" >/dev/null 2>&1
uv pip install --python "$PY" google-re2 pytz >/dev/null 2>&1 || true

if "$PY" -c "import re2, pytz" >/dev/null 2>&1; then
  echo "hogvm oracle venv provisioned: $VENV"
else
  echo "WARN: hogvm oracle venv setup failed (re2/pytz import)" >&2
  exit 1
fi
