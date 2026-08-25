#!/usr/bin/env bash
# smoke-golden.sh — readiness gate for the tasks golden-snapshot rebuild.
#
# Boots a smoke box from the posthog-tasks-candidate alias, runs the task
# sandbox's readiness contract over SSH, and deletes the box. A non-zero exit
# tells the workflow to skip the promote step, which leaves the live
# posthog-tasks-default alias pointing at the previous known-good snapshot.
#
# The contract asserts the two things a task run depends on:
#   a. AGENT-SERVER — @posthog/agent's agent-server binary is present and starts
#      (a golden that baked a broken /scripts install must not promote).
#   b. CLONE + EXEC — a trivial `git clone` of a public repo and a command run
#      inside it work, i.e. the toolchain (git guard, network, exec) is live.
#
# Required env vars (set by the workflow):
#   ALIAS    — the posthog-tasks-candidate alias to boot from
#   SSH_KEY  — path to the PRIVATE key; the public half is at ${SSH_KEY}.pub
#
# On success prints a single parseable line to stdout:
#   SMOKE_HEALTHY_SECONDS=<n>   (create→contract-passed wall-clock)

set -euo pipefail

: "${ALIAS:?ALIAS is required}"
: "${SSH_KEY:?SSH_KEY is required (private key path; pub at \${SSH_KEY}.pub)}"

log() { printf '[tasks-smoke] %s\n' "$*" >&2; }

# Fixed name so a killed prior run's leftover box is found and cleaned rather
# than leaking a node or colliding on the next create (hogplane 409s on a
# duplicate name).
SMOKE_BOX_NAME=golden-smoke-tasks
SMOKE_BOX_ID=""

resolve_smoke_box_id() {
    hogland box list --kind posthog-tasks-smoke 2>/dev/null \
        | jq -r --arg n "$SMOKE_BOX_NAME" 'map(select(.spec.name == $n)) | .[0].id // empty' 2>/dev/null \
        || true
}

cleanup() {
    if [[ -z "$SMOKE_BOX_ID" ]]; then
        SMOKE_BOX_ID=$(resolve_smoke_box_id)
    fi
    if [[ -n "$SMOKE_BOX_ID" ]]; then
        log "deleting smoke box $SMOKE_BOX_ID"
        hogland box delete "$SMOKE_BOX_ID" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# Defensive pre-clean: a previous killed run may have leaked a box under our
# fixed name, and every subsequent create would 409 on it. Wait for the delete
# to land (it is async) before creating.
stale_id=$(resolve_smoke_box_id)
if [[ -n "$stale_id" ]]; then
    log "pre-cleaning stale smoke box $stale_id (name $SMOKE_BOX_NAME)"
    hogland box delete "$stale_id" >/dev/null 2>&1 || true
    gone_deadline=$(( $(date +%s) + 120 ))
    while [[ -n "$(resolve_smoke_box_id)" ]]; do
        if [[ "$(date +%s)" -ge "$gone_deadline" ]]; then
            log "FAIL: stale smoke box $stale_id still present 2m after delete"
            exit 1
        fi
        sleep 5
    done
    log "stale smoke box gone"
fi

log "creating smoke box from alias:$ALIAS"
create_t0=$(date +%s)
# Don't let `set -e` abort on a failed create: the box may still exist (a create
# that timed out waiting for ready left one behind), and the trap needs to run.
# --name gives teardown a handle that survives never learning the id. No sizing
# flags — restore inherits cpus/mem/disk from the snapshot.
create_rc=0
box_json=$(
    hogland box create \
        --snapshot-id "alias:$ALIAS" \
        --ssh-key "${SSH_KEY}.pub" \
        --name "$SMOKE_BOX_NAME" \
        --kind posthog-tasks-smoke \
        --no-connect \
        --timeout 15m
) || create_rc=$?
SMOKE_BOX_ID=$(printf '%s' "$box_json" | jq -r '.id // empty' 2>/dev/null || true)
if [[ "$create_rc" -ne 0 ]]; then
    log "FAIL: box create exited $create_rc"
    printf '%s\n' "$box_json" >&2
    exit 1
fi
ssh_cmd=$(printf '%s' "$box_json" | jq -r '.ssh_command // empty')
if [[ -z "$ssh_cmd" ]]; then
    log "box create returned no ssh_command; cannot reach box for smoke"
    printf '%s\n' "$box_json" >&2
    exit 1
fi
log "smoke box $SMOKE_BOX_ID ssh_command: $ssh_cmd"

# Rebuild the ssh invocation from the returned command, injecting our key +
# non-interactive options right after the `ssh` word. IdentitiesOnly pins the
# probe to our ephemeral key (a stray agent identity would burn MaxAuthTries
# first); BatchMode never prompts; accept-new trusts the fresh host key silently.
read -r -a ssh_parts <<<"$ssh_cmd"
ssh_opts=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o BatchMode=yes)
ssh_base=("${ssh_parts[0]}" "${ssh_opts[@]}" "${ssh_parts[@]:1}")

log "waiting for ssh reachability (up to 5m)"
ssh_deadline=$(( $(date +%s) + 300 ))
until "${ssh_base[@]}" -o ConnectTimeout=5 true 2>/dev/null; do
    if [[ "$(date +%s)" -ge "$ssh_deadline" ]]; then
        log "ssh never became reachable within 5m"
        exit 1
    fi
    sleep 5
done
log "ssh reachable"

# (a) agent-server: present and able to report its version. --help/--version
# exits cleanly without needing task credentials or a running control plane.
log "asserting agent-server present and starts"
if ! "${ssh_base[@]}" "test -x /scripts/node_modules/.bin/agent-server"; then
    log "FAIL: /scripts/node_modules/.bin/agent-server missing or not executable"
    exit 1
fi
if ! "${ssh_base[@]}" "/scripts/node_modules/.bin/agent-server --version >/dev/null 2>&1 || /scripts/node_modules/.bin/agent-server --help >/dev/null 2>&1"; then
    log "FAIL: agent-server did not start (neither --version nor --help succeeded)"
    exit 1
fi

# (b) clone + exec: the git guard passes through a real clone, network egress
# works, and a command runs inside the checkout. POSTHOG_ALLOW_UNSIGNED_GIT is
# irrelevant here (clone is never blocked); this exercises the everyday path.
log "asserting trivial clone + exec"
if ! "${ssh_base[@]}" "set -e; d=\$(mktemp -d); git clone --depth 1 https://github.com/octocat/Hello-World \"\$d/repo\"; test -f \"\$d/repo/README\"; ( cd \"\$d/repo\" && git rev-parse HEAD ); rm -rf \"\$d\""; then
    log "FAIL: trivial clone/exec did not complete"
    exit 1
fi

elapsed=$(( $(date +%s) - create_t0 ))
log "tasks golden contract passed after ${elapsed}s"
printf 'SMOKE_HEALTHY_SECONDS=%d\n' "$elapsed"
