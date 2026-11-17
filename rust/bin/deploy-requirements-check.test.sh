#!/usr/bin/env bash
# Tests for write-deploy-requirements and deploy-requirements-check. Fakes on PATH replace psql, sleep and
# timeout: psql returns the rows of _sqlx_migrations from a fixture file, sleep records its
# argument instead of waiting, so no database and no real wait is needed.
set -euo pipefail

BIN_DIR=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/fakebin" "$WORK/migrations/persons_migrations" "$WORK/migrations/behavioral_cohorts_migrations"
cat > "$WORK/fakebin/psql" <<'EOF'
#!/bin/bash
# PgBouncer refuses statement_timeout as a startup parameter, so the check must not send it there.
if [[ "${PGOPTIONS:-}" == *statement_timeout* ]]; then
    echo 'psql: error: FATAL:  unsupported startup parameter: options' >&2
    exit 2
fi
# The URL names the fixture: postgres://fixture/<name>
fixture="$FAKE_PSQL_DIR/${1##*/}"
case "${1##*/}" in
    down) echo "psql: error: connection to server failed" >&2; exit 2 ;;
    fresh) echo 'ERROR:  relation "_sqlx_migrations" does not exist' >&2; exit 1 ;;
    badpass) echo 'psql: error: invalid percent-encoded token: "%secret"' >&2; exit 2 ;;
esac
cat "$fixture"
EOF
# Records each pause. When FAKE_SLEEP_APPLIES is set, the migration "finishes" during the pause.
cat > "$WORK/fakebin/sleep" <<'EOF'
#!/bin/bash
echo "$1" >> "$FAKE_PSQL_DIR/sleeps"
if [ -n "${FAKE_SLEEP_APPLIES:-}" ]; then
    cp "$FAKE_SLEEP_APPLIES" "$FAKE_PSQL_DIR/persons"
fi
EOF
cat > "$WORK/fakebin/timeout" <<'EOF'
#!/bin/bash
shift
exec "$@"
EOF
chmod +x "$WORK/fakebin/psql" "$WORK/fakebin/sleep" "$WORK/fakebin/timeout"
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
    output=$(SCHEMA_CHECK_WAIT_SECONDS=0 SCHEMA_CHECK_INTERVAL_SECONDS=1 "$BIN_DIR/deploy-requirements-check" 2>&1)
    code=$?
    set -e
    echo "$code $(echo "$output" | sed -n 's/.*"result":"\([a-z_]*\)".*/\1/p')"
}

# The writer lists every up migration of the declared databases and skips .down.sql twins.
"$BIN_DIR/write-deploy-requirements" "persons behavioral-cohorts" "$WORK/req.json" "$WORK/migrations"
assert_eq "writer writes a deploy requirements manifest with sqlx requirements" \
    '{"schema_version":1,"requirements":[{"kind":"sqlx","database":"persons","versions":[20250101000001,20250201000001]},{"kind":"sqlx","database":"behavioral-cohorts","versions":[20250301000001]}]}' \
    "$(jq -c '{schema_version, requirements}' "$WORK/req.json")"

"$BIN_DIR/write-deploy-requirements" "" "$WORK/empty.json" "$WORK/migrations"
assert_eq "writer with no database writes no requirements" "[]" "$(jq -c '.requirements' "$WORK/empty.json")"

set +e
"$BIN_DIR/write-deploy-requirements" "personz" "$WORK/bad.json" "$WORK/migrations" 2>/dev/null
assert_eq "writer fails on an unknown database" "1" "$?"
set -e

export SCHEMA_CHECK_REQUIREMENTS="$WORK/req.json"
export SCHEMA_CHECK_MODE=enforce
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
assert_eq "shadow mode logs the hold and exits 0" "0 missing" "$(SCHEMA_CHECK_MODE=shadow run_check)"

assert_eq "no manifest passes (image older than the check)" "0 no_requirements_file" \
    "$(SCHEMA_CHECK_REQUIREMENTS="$WORK/none.json" run_check)"

printf 'persons 20250101000001\n' > "$WORK/malformed.json"
assert_eq "a file that is not a manifest is an error" "2 error" \
    "$(SCHEMA_CHECK_REQUIREMENTS="$WORK/malformed.json" run_check)"

printf '{"schema_version":1,"requirements":[{"kind":"django","database":"default","app":"posthog","migration":"0001"}]}\n' > "$WORK/django.json"
assert_eq "an unknown requirement kind is an error, not a pass" "2 error" \
    "$(SCHEMA_CHECK_REQUIREMENTS="$WORK/django.json" run_check)"

printf '{"schema_version":2,"requirements":[]}\n' > "$WORK/v2.json"
assert_eq "an unknown schema version is an error" "2 error" "$(SCHEMA_CHECK_REQUIREMENTS="$WORK/v2.json" run_check)"

assert_eq "an image without sqlx databases passes" "0 satisfied" \
    "$(SCHEMA_CHECK_REQUIREMENTS="$WORK/empty.json" run_check)"

# Shadow mode must not wait for a pending migration, or it delays the rollout it must not hold.
printf '20250101000001 t\n' > "$WORK/persons"
rm -f "$WORK/sleeps"
SCHEMA_CHECK_MODE=shadow "$BIN_DIR/deploy-requirements-check" > /dev/null
assert_eq "shadow mode checks once without waiting" "no pause" "$([ -f "$WORK/sleeps" ] && echo paused || echo "no pause")"

# A wait shorter than the interval still checks again at the deadline. The migration finishes
# during the only pause, so the check passes.
printf '20250101000001 t\n' > "$WORK/persons"
printf '20250101000001 t\n20250201000001 t\n' > "$WORK/applied"
rm -f "$WORK/sleeps"
set +e
deadline_output=$(FAKE_SLEEP_APPLIES="$WORK/applied" SCHEMA_CHECK_WAIT_SECONDS=5 SCHEMA_CHECK_INTERVAL_SECONDS=15 "$BIN_DIR/deploy-requirements-check")
deadline_code=$?
set -e
assert_eq "a short wait checks again at the deadline" "0 satisfied" \
    "$deadline_code $(echo "$deadline_output" | sed -n 's/.*"result":"\([a-z_]*\)".*/\1/p')"
assert_eq "the last pause ends at the deadline" "yes" "$([ "$(head -1 "$WORK/sleeps")" -le 5 ] && echo yes || echo no)"

# libpq can echo part of a malformed password. The log must not carry it.
export PERSONS_DATABASE_URL="postgres://fixture/badpass"
badpass_output=$(SCHEMA_CHECK_MODE=shadow "$BIN_DIR/deploy-requirements-check")
assert_eq "a psql error does not log quoted credentials" "no secret" \
    "$(echo "$badpass_output" | grep -q secret && echo "secret leaked" || echo "no secret")"
export PERSONS_DATABASE_URL="postgres://fixture/persons"

if [ "$failures" -gt 0 ]; then
    echo "$failures test(s) failed"
    exit 1
fi
echo "all tests passed"
