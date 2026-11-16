#!/usr/bin/env bash
# Tests for write-sqlx-requirements and sqlx-schema-check. A fake psql on PATH returns the
# rows of _sqlx_migrations from a fixture file, so no database is needed.
set -euo pipefail

BIN_DIR=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/fakebin" "$WORK/migrations/persons_migrations" "$WORK/migrations/behavioral_cohorts_migrations"
cat > "$WORK/fakebin/psql" <<'EOF'
#!/bin/bash
# The URL names the fixture: postgres://fixture/<name>
fixture="$FAKE_PSQL_DIR/${1##*/}"
case "${1##*/}" in
    down) echo "psql: error: connection to server failed" >&2; exit 2 ;;
    fresh) echo 'ERROR:  relation "_sqlx_migrations" does not exist' >&2; exit 1 ;;
esac
cat "$fixture"
EOF
chmod +x "$WORK/fakebin/psql"
export PATH="$WORK/fakebin:$PATH"
export FAKE_PSQL_DIR="$WORK"

touch "$WORK/migrations/persons_migrations/20250101000001_initial.sql"
touch "$WORK/migrations/persons_migrations/20250201000001_add_column.sql"
touch "$WORK/migrations/persons_migrations/20250201000001_add_column.down.sql"
touch "$WORK/migrations/behavioral_cohorts_migrations/20250301000001_cohorts.sql"

failures=0

assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        echo "ok   $name"
    else
        echo "FAIL $name: expected [$expected], got [$actual]"
        failures=$((failures + 1))
    fi
}

# Runs the check with a short wait and prints "<exit code> <result>".
run_check() {
    local output code
    set +e
    output=$(SQLX_SCHEMA_CHECK_WAIT_SECONDS=0 SQLX_SCHEMA_CHECK_INTERVAL_SECONDS=1 "$BIN_DIR/sqlx-schema-check" 2>&1)
    code=$?
    set -e
    echo "$code $(echo "$output" | sed -n 's/.*"result":"\([a-z_]*\)".*/\1/p')"
}

# The writer lists every up migration of the declared databases and skips .down.sql twins.
"$BIN_DIR/write-sqlx-requirements" "persons behavioral-cohorts" "$WORK/req.json" "$WORK/migrations"
assert_eq "writer writes the Node manifest shape with sqlx requirements" \
    '{"schema_version":1,"requirements":[{"kind":"sqlx","database":"persons","versions":[20250101000001,20250201000001]},{"kind":"sqlx","database":"behavioral-cohorts","versions":[20250301000001]}]}' \
    "$(jq -c '{schema_version, requirements}' "$WORK/req.json")"

# The Node writer computes the digest as sha256(JSON.stringify(requirements)), first 12 hex.
expected_digest=$(jq -c '.requirements' "$WORK/req.json" | tr -d '\n' | { sha256sum 2>/dev/null || shasum -a 256; } | cut -c1-12)
assert_eq "writer digest matches the Node formula" "$expected_digest" "$(jq -r '.digest' "$WORK/req.json")"

"$BIN_DIR/write-sqlx-requirements" "" "$WORK/empty.json" "$WORK/migrations"
assert_eq "writer with no database writes no requirements" "[]" "$(jq -c '.requirements' "$WORK/empty.json")"

set +e
"$BIN_DIR/write-sqlx-requirements" "personz" "$WORK/bad.json" "$WORK/migrations" 2>/dev/null
assert_eq "writer fails on an unknown database" "1" "$?"
set -e

export SQLX_SCHEMA_CHECK_REQUIREMENTS="$WORK/req.json"
export SQLX_SCHEMA_CHECK_MODE=enforce
export BEHAVIORAL_COHORTS_DATABASE_URL="postgres://fixture/cohorts"
printf '20250301000001 t\n' > "$WORK/cohorts"

printf '20250101000001 t\n20250201000001 t\n20251201000001 t\n' > "$WORK/persons"
export PERSONS_DATABASE_URL="postgres://fixture/persons"
assert_eq "all applied, newer versions allowed" "0 satisfied" "$(run_check)"

printf '20250101000001 t\n' > "$WORK/persons"
assert_eq "a missing version holds" "1 missing" "$(run_check)"

printf '20250101000001 t\n20250201000001 f\n' > "$WORK/persons"
assert_eq "a failed required version holds" "1 missing" "$(run_check)"

export PERSONS_DATABASE_URL="postgres://fixture/fresh"
assert_eq "a database without the sqlx table holds" "1 missing" "$(run_check)"

export PERSONS_DATABASE_URL="postgres://fixture/down"
assert_eq "a connection error is an error, not a hold" "2 error" "$(run_check)"

unset PERSONS_DATABASE_URL
assert_eq "a declared database without a URL is an error" "2 error" "$(run_check)"

export PERSONS_DATABASE_URL="postgres://fixture/persons"
printf '20250101000001 t\n' > "$WORK/persons"
assert_eq "shadow mode logs the hold and exits 0" "0 missing" "$(SQLX_SCHEMA_CHECK_MODE=shadow run_check)"

assert_eq "no manifest passes (image older than the check)" "0 no_requirements_file" \
    "$(SQLX_SCHEMA_CHECK_REQUIREMENTS="$WORK/none.json" run_check)"

printf 'persons 20250101000001\n' > "$WORK/malformed.json"
assert_eq "a file that is not a manifest is an error" "2 error" \
    "$(SQLX_SCHEMA_CHECK_REQUIREMENTS="$WORK/malformed.json" run_check)"

printf '{"schema_version":1,"requirements":[{"kind":"django","database":"default","app":"posthog","migration":"0001"}]}\n' > "$WORK/django.json"
assert_eq "an unknown requirement kind is an error, not a pass" "2 error" \
    "$(SQLX_SCHEMA_CHECK_REQUIREMENTS="$WORK/django.json" run_check)"

printf '{"schema_version":2,"requirements":[]}\n' > "$WORK/v2.json"
assert_eq "an unknown schema version is an error" "2 error" "$(SQLX_SCHEMA_CHECK_REQUIREMENTS="$WORK/v2.json" run_check)"

assert_eq "an image without sqlx databases passes" "0 satisfied" \
    "$(SQLX_SCHEMA_CHECK_REQUIREMENTS="$WORK/empty.json" run_check)"

# Shadow mode must not wait for a pending migration, or it delays the rollout it must not hold.
printf '20250101000001 t\n' > "$WORK/persons"
shadow_output=$(SQLX_SCHEMA_CHECK_MODE=shadow SQLX_SCHEMA_CHECK_INTERVAL_SECONDS=30 "$BIN_DIR/sqlx-schema-check")
assert_eq "shadow mode checks once without waiting" "0" \
    "$(echo "$shadow_output" | sed -n 's/.*"elapsed_seconds":\([0-9]*\).*/\1/p')"

if [ "$failures" -gt 0 ]; then
    echo "$failures test(s) failed"
    exit 1
fi
echo "all tests passed"
