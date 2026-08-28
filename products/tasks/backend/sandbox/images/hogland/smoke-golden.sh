#!/usr/bin/env bash
# smoke-golden.sh — readiness gate for the tasks golden-snapshot rebuild.
#
# Boots a smoke box from the posthog-tasks-candidate alias, runs the task
# sandbox's readiness contract over SSH, and deletes the box. A non-zero exit
# tells the workflow to skip the promote step, which leaves the live
# posthog-tasks-default alias pointing at the previous known-good snapshot.
#
# The contract asserts the things a task run depends on:
#   a. AGENT-SERVER — @posthog/agent's agent-server binary is present and starts
#      (a golden that baked a broken /scripts install must not promote).
#   b. CLONE + EXEC — a trivial `git clone` of a public repo and a command run
#      inside it work, i.e. the toolchain (git guard, network, exec) is live.
#   c. EXEC-DAEMON ENV — the running hogpanion daemon (whose env hog-exec children
#      inherit) carries the container-style env: IS_SANDBOX=1, a PATH with
#      /opt/posthog/bin first (the git/gh guards), and PYTHONPATH. This reads the
#      daemon's live /proc environ, NOT an SSH login shell — a login shell reads
#      /etc/environment via PAM and would look correct even if the daemon env
#      never picked up the drop-in, certifying a broken golden green.
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

# List across ALL kinds, not just ours: hogplane's name-uniqueness check
# (ensureBoxNameUnique) scans every kind, so match by name only.
resolve_smoke_box_id() {
    hogland box list 2>/dev/null \
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
# --kind posthog-tasks-golden: an UNREGISTERED kind carries no server-side idle
#   TTL, so an all-SSH smoke run is never reaped mid-check. The workflow's
#   always() teardown deletes this box by name on cancel. --access-type
#   ssh-private: keep the box off the public internet; the runner reaches it over
#   the tailnet. --disk-mbps 0 --disk-iops 0: the bake baked the snapshot with
#   uncapped disk, and production restores inherit that — but the CLI applies its
#   own 125MB/s / 3000-IOPS defaults on restore rather than inheriting, so pass 0
#   here too or the smoke measures a throttle production never sees.
#   --timeout 30m: a 64 GiB restore may wait on Karpenter for a node.
box_json=$(
    hogland box create \
        --snapshot-id "alias:$ALIAS" \
        --ssh-key "${SSH_KEY}.pub" \
        --name "$SMOKE_BOX_NAME" \
        --kind posthog-tasks-golden \
        --access-type ssh-private \
        --disk-mbps 0 \
        --disk-iops 0 \
        --no-connect \
        --timeout 30m
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
# ServerAlive* turns a wedged binary or dead session on the box into a dropped
# connection in ~45s, instead of hanging an assert until the job's 150m ceiling.
ssh_opts=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
ssh_base=("${ssh_parts[0]}" "${ssh_opts[@]}" "${ssh_parts[@]:1}")

# Run one SSH assertion under a hard local ceiling, so neither a hung binary nor
# a stuck TCP session can wedge the job. Usage: ssh_assert <remote-command...>
ssh_assert() {
    timeout 60 "${ssh_base[@]}" "$@"
}

log "waiting for ssh reachability (up to 5m)"
ssh_deadline=$(( $(date +%s) + 300 ))
until timeout 20 "${ssh_base[@]}" -o ConnectTimeout=5 true 2>/dev/null; do
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
if ! ssh_assert "test -x /scripts/node_modules/.bin/agent-server"; then
    log "FAIL: /scripts/node_modules/.bin/agent-server missing or not executable"
    exit 1
fi
if ! ssh_assert "/scripts/node_modules/.bin/agent-server --version >/dev/null 2>&1 || /scripts/node_modules/.bin/agent-server --help >/dev/null 2>&1"; then
    log "FAIL: agent-server did not start (neither --version nor --help succeeded)"
    exit 1
fi

# (b) clone + exec: the git guard passes through a real clone, network egress
# works, and a command runs inside the checkout. POSTHOG_ALLOW_UNSIGNED_GIT is
# irrelevant here (clone is never blocked); this exercises the everyday path.
log "asserting trivial clone + exec"
if ! ssh_assert "set -e; d=\$(mktemp -d); git clone --depth 1 https://github.com/octocat/Hello-World \"\$d/repo\"; test -f \"\$d/repo/README\"; ( cd \"\$d/repo\" && git rev-parse HEAD ); rm -rf \"\$d\""; then
    log "FAIL: trivial clone/exec did not complete"
    exit 1
fi

# (c) exec-daemon env: the golden must promote only if hogpanion — the daemon
# whose env hog-exec children inherit — is running with the container-style env
# from setup-golden.sh's drop-in. We read the DAEMON's live /proc environ, not a
# login shell: PAM feeds an SSH shell /etc/environment, so a shell would look
# correct even when the daemon never re-exec'd with the drop-in (the exact bug a
# missing hogpanion restart causes). Reading another process's /proc/<pid>/environ
# needs root; the box's ssh user is `hog`, which has passwordless sudo, so the
# environ read goes through sudo. `systemctl show` of the unit config is the
# secondary, weaker signal (config loaded, not necessarily applied to the live
# process). Reaching a real hog-exec child through hogpanion's exec API is the
# ideal upgrade — see GOLDEN_CI_RUNBOOK.md's known-gaps.
log "asserting exec-daemon (hogpanion) env carries the container-style env"
# shellcheck disable=SC2016 # $pid/$environ must expand on the box, not locally
daemon_env_probe='set -eu
pid=$(systemctl show hogpanion.service -p MainPID --value 2>/dev/null || echo 0)
if [ -z "$pid" ] || [ "$pid" = "0" ]; then
    echo "hogpanion has no running MainPID" >&2; exit 1
fi
environ=$(sudo cat "/proc/$pid/environ" | tr "\0" "\n")
printf "%s\n" "$environ" | grep -qx "IS_SANDBOX=1" || { echo "daemon env missing IS_SANDBOX=1" >&2; exit 1; }
printf "%s\n" "$environ" | grep -q "^PATH=/opt/posthog/bin:" || { echo "daemon PATH does not start with /opt/posthog/bin" >&2; exit 1; }
printf "%s\n" "$environ" | grep -q "^PYTHONPATH=" || { echo "daemon env missing PYTHONPATH" >&2; exit 1; }
# HOME must be set: hogpanion hands exec children bare os.Environ(), and skills
# resolve $HOME/.agents/skills while git reads /root/.gitconfig. Without HOME a
# set -u task step dies. The drop-in sets HOME=/root.
printf "%s\n" "$environ" | grep -qx "HOME=/root" || { echo "daemon env missing HOME=/root" >&2; exit 1; }
# The /opt/posthog/bin-first PATH is what makes git resolve to the guard; confirm
# the guard is actually there so the guarded path the daemon exposes is real.
test -x /opt/posthog/bin/git || { echo "/opt/posthog/bin/git missing" >&2; exit 1; }
grep -q POSTHOG_ALLOW_UNSIGNED_GIT /opt/posthog/bin/git || { echo "/opt/posthog/bin/git is not the git guard" >&2; exit 1; }
systemctl show hogpanion.service -p Environment -p EnvironmentFiles --no-pager >&2'
if ! ssh_assert "$daemon_env_probe"; then
    log "FAIL: hogpanion daemon env is not the container-style env (restart likely did not take before snapshot)"
    exit 1
fi

# (d) exec API: production reaches a task box only through hogpanion's exec API
# (POST /v1/hogboxes/{id}/exec), never SSH. Assert a trivial command round-trips
# through it so a golden that works over SSH but not via exec is caught. HOG_HOST
# + HOG_TOKEN_COMMAND come from the workflow's bake-job env. The request body is
# {argv, timeout_seconds} — the schema requires `argv` (not `command`). Fail OPEN
# only when the endpoint is genuinely unreachable (000) — a 404 is what a missing
# box or a non-owner gets, i.e. a real regression that must not pass green.
if [[ -n "${HOG_HOST:-}" && -n "${HOG_TOKEN_COMMAND:-}" ]]; then
    log "asserting box reachable via hogpanion exec API"
    exec_token=$(eval "$HOG_TOKEN_COMMAND" 2>/dev/null || true)
    if [[ -z "$exec_token" ]]; then
        log "WARN: could not mint bearer for the exec assertion; relying on SSH assertions"
    else
        exec_out=$(mktemp)
        exec_body='{"argv":["/bin/sh","-c","echo golden-exec-ok"],"timeout_seconds":30}'
        # hogplane matches the auth scheme case-sensitively — "Bearer" (capital
        # B), unlike the lowercase "bearer" GitHub's OIDC token endpoint wants in
        # HOG_TOKEN_COMMAND. A lowercase scheme here gets a 401, which the case
        # below treats as a hard failure.
        # curl already prints "000" via -w on a connection failure, so append
        # nothing on its non-zero exit — `|| echo 000` would concatenate to
        # "000000" and never match the 000) arm below. --max-time caps a hung
        # request so a wedged endpoint can't stall the job. -w also prints
        # num_connects so a 000 can be routed by whether a connection was ever
        # made: 0 => the endpoint was unreachable (a tailnet/infra blip, not the
        # golden's fault) => fail open and rely on the SSH assertions; >=1 with a
        # 000 => we connected but the request hung or was reset (a --max-time
        # stall) => a real failure. So a box that stalls the exec cannot promote
        # itself by forcing a fail-open.
        read -r http_code num_connects <<<"$(curl -sS --connect-timeout 10 --max-time 60 \
            -o "$exec_out" -w '%{http_code} %{num_connects}' \
            -X POST "$HOG_HOST/v1/hogboxes/$SMOKE_BOX_ID/exec" \
            -H "Authorization: Bearer $exec_token" \
            -H 'Content-Type: application/json' \
            -d "$exec_body" 2>/dev/null || true)"
        case "$http_code" in
            2*)
                if grep -q 'golden-exec-ok' "$exec_out"; then
                    log "exec API round-trip ok"
                else
                    log "FAIL: exec API returned $http_code but its output lacked the marker"
                    cat "$exec_out" >&2 || true
                    rm -f "$exec_out"
                    exit 1
                fi
                ;;
            000)
                if [[ "${num_connects:-0}" != "0" ]]; then
                    log "FAIL: exec API connected but the request did not complete (num_connects=${num_connects}) — a stall or reset, not fail-open"
                    cat "$exec_out" >&2 || true
                    rm -f "$exec_out"
                    exit 1
                fi
                log "WARN: exec API unreachable (never connected); relying on SSH assertions. Enable once the exec contract is confirmed (see runbook)."
                ;;
            *)
                log "FAIL: exec API POST returned HTTP $http_code"
                cat "$exec_out" >&2 || true
                rm -f "$exec_out"
                exit 1
                ;;
        esac
        rm -f "$exec_out"
    fi
fi

elapsed=$(( $(date +%s) - create_t0 ))
log "tasks golden contract passed after ${elapsed}s"
printf 'SMOKE_HEALTHY_SECONDS=%d\n' "$elapsed"
