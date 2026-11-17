#!/usr/bin/env bash
# Copy the PostHog repo into a fresh worktree, boot the dev stack there, log a
# browser in, and write a report that agents read before browsing.
#
# Usage: get-ready.sh [--from <posthog checkout>] [--ref <git ref>] [--name <dir name>] [--skip-stack]
#
# Every phase writes .getting-ready/status.json in the new worktree, so a
# caller polling that file sees progress. The last stdout line is the final
# status as JSON. Exit codes: 0 ready, 2 blocked by the host, 1 failed.

set -uo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FROM=""
REF="origin/master"
NAME=""
SKIP_STACK=false
BASE_URL="${GETTING_READY_BASE_URL:-http://localhost:8010}"
CLONE_URL="${GETTING_READY_CLONE_URL:-https://github.com/PostHog/posthog.git}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) FROM="$2"; shift 2 ;;
        --ref) REF="$2"; shift 2 ;;
        --name) NAME="$2"; shift 2 ;;
        --skip-stack) SKIP_STACK=true; shift ;;
        -h|--help) sed -n 2,9p "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done

STAMP="$(date +%Y%m%d-%H%M%S)"
NAME="${NAME:-getting-ready-${STAMP}}"
WORKTREE_BASE="${POSTHOG_WORKTREE_BASE:-${HOME}/.worktrees/posthog}"
WT="${WORKTREE_BASE}/${NAME}"
STATE_DIR="${WT}/.getting-ready"
PHASE="copy"

log() { printf '[getting-ready] %s\n' "$*" >&2; }

json_str() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }

write_status() {
    local state="$1" detail="$2"
    mkdir -p "${STATE_DIR}"
    # Keeps the state files out of `git status` without touching .git/info/exclude,
    # which every worktree of the main clone shares.
    echo '*' > "${STATE_DIR}/.gitignore"
    cat > "${STATE_DIR}/status.json" <<EOF
{"state": $(json_str "$state"), "phase": $(json_str "$PHASE"), "detail": $(json_str "$detail"), "worktree": $(json_str "$WT"), "base_url": $(json_str "$BASE_URL"), "updated_at": $(json_str "$(date -u +%FT%TZ)")}
EOF
}

finish() {
    local code="$1" state="$2" detail="$3"
    write_status "$state" "$detail"
    log "${state}: ${detail}"
    cat "${STATE_DIR}/status.json"
    exit "$code"
}

blocked() { finish 2 blocked "$1"; }
failed() { finish 1 failed "$1"; }

# Run a command inside the worktree's toolchain: flox when it exists, else the
# worktree's own virtualenv on PATH.
in_env() {
    if command -v flox >/dev/null 2>&1; then
        (cd "$WT" && flox activate -- bash -c "$*")
    else
        (cd "$WT" && PATH="$WT/.venv/bin:$PATH" bash -c "$*")
    fi
}

# --- Phase 1: copy the repo -------------------------------------------------

if [[ -z "$FROM" ]]; then
    top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    if [[ -n "$top" && -f "$top/hogli.yaml" && -d "$top/posthog" ]]; then
        # Use the main clone, not a linked worktree, so .env files come from it.
        FROM="$(git -C "$top" worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
    fi
fi

if [[ -n "$FROM" ]]; then
    log "copying ${FROM} at ${REF} into ${WT}"
    git -C "$FROM" fetch --quiet origin master || log "fetch failed, using the local copy of ${REF}"
    git -C "$FROM" worktree prune
    [[ -e "$WT" ]] && failed "${WT} already exists; pass --name to pick another directory"
    mkdir -p "$WORKTREE_BASE"
    git -C "$FROM" worktree add --quiet -b "getting-ready/${STAMP}" "$WT" "$REF" \
        || failed "git worktree add failed for ref ${REF}"
    # Untracked config the stack reads: .env, .env.local and friends.
    find "$FROM" -maxdepth 1 \( -name ".env" -o -name ".env.*" \) -type f -exec cp -a {} "$WT/" \;
else
    log "no PostHog checkout found, cloning ${CLONE_URL} into ${WT}"
    mkdir -p "$WORKTREE_BASE"
    git clone --quiet --filter=blob:none "$CLONE_URL" "$WT" || failed "git clone failed"
    if [[ "$REF" != "origin/master" ]]; then
        git -C "$WT" checkout --quiet "$REF" || failed "could not check out ${REF}"
    fi
fi
write_status running "repo copied"

# --- Phase 2: dependencies --------------------------------------------------

PHASE="deps"
write_status running "installing Python and Node dependencies"
if command -v flox >/dev/null 2>&1; then
    # The flox on-activate hook installs both the Python and Node dependencies.
    (cd "$WT" && unset VIRTUAL_ENV PYTHONPATH && flox activate --trust -- true) \
        || failed "flox activate failed while installing dependencies"
else
    command -v uv >/dev/null 2>&1 || blocked "neither flox nor uv is installed"
    command -v pnpm >/dev/null 2>&1 || blocked "neither flox nor pnpm is installed"
    (cd "$WT" && uv sync --frozen) || failed "uv sync failed (see the setup-web-tests skill for a Python version mismatch)"
    (cd "$WT" && pnpm install --frozen-lockfile --prefer-offline) || failed "pnpm install failed"
fi

if [[ "$SKIP_STACK" == true ]]; then
    finish 0 ready "repo copied and dependencies installed; stack not started (--skip-stack)"
fi

# --- Phase 3: preflight the host --------------------------------------------

PHASE="preflight"
docker info >/dev/null 2>&1 || blocked "Docker is not running. Start OrbStack or Docker Desktop, or use a devbox: hogli devbox:start --start-app"
if curl -s -o /dev/null --max-time 2 "${BASE_URL}/_health"; then
    blocked "something already serves ${BASE_URL}, probably another worktree's stack. Stop it there with 'hogli down -y', then rerun"
fi

# --- Phase 4: start the stack -----------------------------------------------

PHASE="stack"
write_status running "starting the dev stack (first boot takes several minutes)"
in_env "hogli up -d -y" || failed "hogli up -d failed"
in_env "hogli services:ready -y" || failed "Docker services did not become healthy"
in_env "hogli wait -y" || log "hogli wait reported a unit not ready, checking the app directly"

deadline=$(( $(date +%s) + ${GETTING_READY_BOOT_TIMEOUT:-900} ))
until curl -sf -o /dev/null --max-time 5 "${BASE_URL}/_health"; do
    [[ $(date +%s) -gt $deadline ]] && failed "${BASE_URL}/_health did not return 200 in time"
    sleep 5
done
until curl -sS --max-time 10 "${BASE_URL}/api/projects/@current" 2>/dev/null | grep -q not_authenticated; do
    [[ $(date +%s) -gt $deadline ]] && failed "the API at ${BASE_URL} never reached the database"
    sleep 5
done

# --- Phase 5: workspace, login and smoke screenshot -------------------------

PHASE="browser"
write_status running "creating a workspace and logging a browser in"

PW_DIR="$WT"
node -e "require.resolve('playwright', {paths: [process.argv[1]]})" "$PW_DIR" 2>/dev/null \
    || failed "playwright is not installed in ${WT}/node_modules"

run_smoke() { (cd "$WT" && node "$PLUGIN_DIR/scripts/smoke.mjs" "$BASE_URL" "$STATE_DIR"); }

smoke_out="$(run_smoke 2>&1)"; smoke_code=$?
if [[ $smoke_code -ne 0 ]] && grep -q "Executable doesn't exist" <<<"$smoke_out"; then
    log "installing the Playwright Chromium build"
    (cd "$WT" && pnpm exec playwright install chromium) || failed "playwright install chromium failed"
    smoke_out="$(run_smoke 2>&1)"; smoke_code=$?
fi
if [[ $smoke_code -ne 0 ]] && grep -q "does not exist" <<<"$smoke_out"; then
    # setup_test 500s with "Table posthog.person does not exist" when
    # migrate-clickhouse lost its startup race with migrate-postgres.
    log "ClickHouse tables missing, running migrate_clickhouse"
    in_env "set -a; source .env.services; set +a; python manage.py migrate_clickhouse" \
        || failed "migrate_clickhouse failed"
    smoke_out="$(run_smoke 2>&1)"; smoke_code=$?
fi
printf '%s\n' "$smoke_out" > "${STATE_DIR}/smoke.log"
[[ $smoke_code -eq 0 ]] || failed "browser smoke test failed, see ${STATE_DIR}/smoke.log"

# --- Phase 6: report --------------------------------------------------------

PHASE="done"
team_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["team_id"])' "${STATE_DIR}/workspace.json")"
cat > "${STATE_DIR}/READY.md" <<EOF
# PostHog is ready

- Worktree: ${WT}
- App: ${BASE_URL}/project/${team_id}
- Login: see workspace.json (password 12345678)
- Logged-in Playwright storage state: ${STATE_DIR}/storage-state.json
- Smoke screenshot: ${STATE_DIR}/smoke.png
- Stop the stack: cd ${WT} && hogli down -y
EOF
finish 0 ready "stack up, workspace created, browser logged in at ${BASE_URL}/project/${team_id}"
