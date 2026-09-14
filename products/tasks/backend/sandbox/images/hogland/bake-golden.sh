#!/usr/bin/env bash
# bake-golden.sh — bake the PostHog *tasks* golden snapshot from box primitives.
#
# This replaces `hogland snapshot-build`. snapshot-build can only deliver a
# <=256 KiB bootstrap (--setup-script + --inline-file heredocs), which cannot
# carry the multi-MB rendered-skills set. So we decompose the bake into the
# underlying primitives and stream the payload in over the box's own SSH:
#
#   1. `box create` a bare seed box from the base (cold boot, --no-connect).
#   2. Stream the payload into the box over SSH (cat > file): the git/gh guards,
#      the cpu sampler, the rendered-skills tarball, install-skills.sh, and
#      setup-golden.sh. Only `cat` is needed in the box, so this works without a
#      remote scp/sftp binary and without any public artifact host.
#   3. Run setup-golden.sh in the box over SSH. It installs node/uv/tools/agentsh
#      fresh, npm-installs @posthog/agent, and installs the delivered skills.
#   4. `box snapshot` the result and point the candidate alias at it.
#
# Success detection is ours now (snapshot-build appended /var/lib/hog/
# snapshot-build-ok and polled it; we do not). setup-golden.sh runs under
# `set -euo pipefail`, and we check its SSH exit code explicitly — a non-zero
# setup aborts the bake before `box snapshot`, so a broken build never promotes.
#
# Required env (set by the workflow):
#   ALIAS          — candidate alias to point at the new snapshot
#   SSH_KEY        — path to the PRIVATE key; the public half is at ${SSH_KEY}.pub
#   IMAGES_DIR     — path to products/tasks/backend/sandbox/images (payload source)
#   SKILLS_TARBALL — path to the runner-rendered skills tarball (.tar.gz)
# Optional env:
#   AGENT_VERSION  — @posthog/agent version to install in-box (default: latest)
#   BOX_CPUS / BOX_MEM_MIB / BOX_DISK_GIB — seed box shape (default 4 / 16384 / 64)
#
# On success prints a single parseable line to stdout:
#   BAKED_SNAPSHOT_ID=<id>

set -euo pipefail

: "${ALIAS:?ALIAS is required}"
: "${SSH_KEY:?SSH_KEY is required (private key path; pub at \${SSH_KEY}.pub)}"
: "${IMAGES_DIR:?IMAGES_DIR is required (path to sandbox/images)}"
: "${SKILLS_TARBALL:?SKILLS_TARBALL is required (path to rendered-skills tarball)}"
AGENT_VERSION="${AGENT_VERSION:-latest}"
BOX_CPUS="${BOX_CPUS:-4}"
BOX_MEM_MIB="${BOX_MEM_MIB:-16384}"
BOX_DISK_GIB="${BOX_DISK_GIB:-64}"

log() { printf '[tasks-bake] %s\n' "$*" >&2; }

GIT_GUARD="$IMAGES_DIR/git-guard.sh"
GH_GUARD="$IMAGES_DIR/gh-guard.sh"
CPU_SAMPLER="$IMAGES_DIR/cpu_billing_sampler.py"
SETUP_SCRIPT="$IMAGES_DIR/hogland/setup-golden.sh"
INSTALL_SKILLS="$IMAGES_DIR/install-skills.sh"

for f in "$GIT_GUARD" "$GH_GUARD" "$CPU_SAMPLER" "$SETUP_SCRIPT" "$INSTALL_SKILLS" "$SKILLS_TARBALL" "${SSH_KEY}.pub"; do
    test -f "$f" || { log "FAIL: required file missing: $f"; exit 1; }
done

# Fixed name so a killed prior run's leftover seed box is found and cleaned
# rather than leaking a node or colliding on the next create (hogplane 409s on a
# duplicate name — matches smoke-golden.sh's fixed-name teardown).
SEED_BOX_NAME=golden-seed-tasks
SEED_BOX_ID=""

# List across ALL kinds, not just ours: hogplane's name-uniqueness check
# (ensureBoxNameUnique) scans every kind, so a same-named box of another kind
# would wedge the create. Match by name only so the pre-clean finds it.
resolve_seed_box_id() {
    hogland box list 2>/dev/null \
        | jq -r --arg n "$SEED_BOX_NAME" 'map(select(.spec.name == $n)) | .[0].id // empty' 2>/dev/null \
        || true
}

cleanup() {
    if [[ -z "$SEED_BOX_ID" ]]; then
        SEED_BOX_ID=$(resolve_seed_box_id)
    fi
    if [[ -n "$SEED_BOX_ID" ]]; then
        log "deleting seed box $SEED_BOX_ID"
        hogland box delete "$SEED_BOX_ID" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# Defensive pre-clean: a previous killed run may have leaked a box under our
# fixed name, and every subsequent create would 409 on it. Wait for the delete
# to land (it is async) before creating.
stale_id=$(resolve_seed_box_id)
if [[ -n "$stale_id" ]]; then
    log "pre-cleaning stale seed box $stale_id (name $SEED_BOX_NAME)"
    hogland box delete "$stale_id" >/dev/null 2>&1 || true
    gone_deadline=$(( $(date +%s) + 120 ))
    while [[ -n "$(resolve_seed_box_id)" ]]; do
        if [[ "$(date +%s)" -ge "$gone_deadline" ]]; then
            log "FAIL: stale seed box $stale_id still present 2m after delete"
            exit 1
        fi
        sleep 5
    done
    log "stale seed box gone"
fi

# Cold boot from the base (no --snapshot-id), so cpus/mem/disk are required and
# fix the snapshot's machine shape to the task sandbox shape. --no-connect keeps
# create non-interactive. --name gives teardown a handle that survives never
# learning the id.
log "creating seed box (cold boot, $BOX_CPUS cpu / $BOX_MEM_MIB MiB / $BOX_DISK_GIB GiB)"
create_rc=0
# --kind posthog-tasks-golden: an UNREGISTERED kind carries no server-side idle
#   TTL, so the box is never reaped mid-bake. A registered kind like `ci` expires
#   at max(LastUsedAt, CreatedAt)+2h, and only API calls bump LastUsedAt — this
#   bake is all SSH, so a 30m-create + 90m-bake would exceed 2h and get reaped.
#   The leak-on-cancel that no-TTL reintroduces is covered by the workflow's
#   always() teardown step, which deletes both boxes by name.
# --access-type ssh-private: keep the box off the public internet; the runner
#   reaches it over the tailnet (default ssh-public DNATs a public port).
# --disk-mbps 0 --disk-iops 0: match hogland's own bakes (CLI defaults 125MB/s /
#   3000 IOPS otherwise).
# --timeout 30m: a cold 64 GiB box may wait on Karpenter to provision a node.
box_json=$(
    hogland box create \
        --ssh-key "${SSH_KEY}.pub" \
        --name "$SEED_BOX_NAME" \
        --kind posthog-tasks-golden \
        --access-type ssh-private \
        --cpus "$BOX_CPUS" \
        --memory-mib "$BOX_MEM_MIB" \
        --disk-gib "$BOX_DISK_GIB" \
        --disk-mbps 0 \
        --disk-iops 0 \
        --no-connect \
        --timeout 30m
) || create_rc=$?
SEED_BOX_ID=$(printf '%s' "$box_json" | jq -r '.id // empty' 2>/dev/null || true)
if [[ "$create_rc" -ne 0 ]]; then
    log "FAIL: box create exited $create_rc"
    printf '%s\n' "$box_json" >&2
    exit 1
fi
ssh_cmd=$(printf '%s' "$box_json" | jq -r '.ssh_command // empty')
if [[ -z "$ssh_cmd" ]]; then
    log "FAIL: box create returned no ssh_command; cannot reach seed box"
    printf '%s\n' "$box_json" >&2
    exit 1
fi
log "seed box $SEED_BOX_ID ssh_command: $ssh_cmd"

# Rebuild the ssh invocation from the returned command, injecting our key +
# non-interactive options right after the `ssh` word (mirrors smoke-golden.sh).
# IdentitiesOnly pins to our ephemeral key; BatchMode never prompts; accept-new
# trusts the fresh host key silently. ServerAlive* guards the ONE long-lived
# session the whole bake runs over: at 30s x 10 it tolerates a ~5m stall before
# dropping. A loaded 4-vCPU box building git from source can stall well past the
# old 15s x 3 (45s) window, which would drop the entire bake mid-step.
read -r -a ssh_parts <<<"$ssh_cmd"
ssh_opts=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=10)
ssh_base=("${ssh_parts[0]}" "${ssh_opts[@]}" "${ssh_parts[@]:1}")

log "waiting for ssh reachability (up to 5m)"
ssh_deadline=$(( $(date +%s) + 300 ))
until timeout 20 "${ssh_base[@]}" -o ConnectTimeout=5 true 2>/dev/null; do
    if [[ "$(date +%s)" -ge "$ssh_deadline" ]]; then
        log "FAIL: ssh never became reachable within 5m"
        exit 1
    fi
    sleep 5
done
log "ssh reachable"

# Stream one local file to a path in the box over SSH, chmod it, and verify the
# byte count landed. The box's ssh user is `hog` (not root), so the write goes
# through passwordless sudo — target paths like /opt/posthog/bin are root-owned.
# `sudo tee` is the delivery primitive; no scp/sftp, no public host. Usage:
# deliver <local-path> <box-path> <mode>
deliver() {
    local src="$1" dst="$2" mode="$3" dir size remote_size
    dir=$(dirname "$dst")
    if ! "${ssh_base[@]}" "sudo mkdir -p '$dir' && sudo tee '$dst' >/dev/null && sudo chmod '$mode' '$dst'" < "$src"; then
        log "FAIL: could not deliver $src -> $dst"
        exit 1
    fi
    size=$(wc -c < "$src" | tr -d '[:space:]')
    remote_size=$("${ssh_base[@]}" "wc -c < '$dst' | tr -d '[:space:]'" 2>/dev/null || echo "")
    if [[ "$size" != "$remote_size" ]]; then
        log "FAIL: $dst is $remote_size bytes in box, expected $size"
        exit 1
    fi
    log "delivered $dst ($size bytes, mode $mode)"
}

# Guards + cpu sampler land at their final paths with mode 0755, so setup-golden.sh
# only has to `test -x` them. The skills tarball, installer, and setup script stage
# under /tmp for setup-golden.sh to consume.
deliver "$GIT_GUARD"      /opt/posthog/bin/git                        0755
deliver "$GH_GUARD"       /opt/posthog/bin/gh                         0755
deliver "$CPU_SAMPLER"    /usr/local/bin/posthog-cpu-billing-sampler  0755
deliver "$SKILLS_TARBALL" /tmp/golden-skills.tar.gz                   0644
deliver "$INSTALL_SKILLS" /tmp/install-skills.sh                      0755
deliver "$SETUP_SCRIPT"   /tmp/setup-golden.sh                        0755

# Run setup-golden.sh in the box. Its `set -euo pipefail` plus this explicit exit
# check are our success gate: a failing step returns non-zero and we never reach
# `box snapshot`. AGENT_VERSION / SKILLS_TARBALL / INSTALL_SKILLS reach it as env.
log "running setup-golden.sh in the box"
# %q-escape AGENT_VERSION before splicing it into the remote command string --
# it comes from an npm registry response (see the workflow's "Resolve
# published agent version" step), and unescaped single-quote interpolation
# would let a value containing a quote break out of the assignment and run
# arbitrary commands in the box.
printf -v agent_version_escaped '%q' "$AGENT_VERSION"
setup_rc=0
# The ssh user is `hog`; setup-golden.sh installs apt packages, writes
# /etc/environment and the systemd drop-in, and restarts hogpanion — all root
# work — so run it through passwordless sudo. `sudo env VAR=...` sets the child
# env explicitly rather than relying on sudo's implied SETENV for leading
# assignments (which a stricter sudoers policy would strip).
"${ssh_base[@]}" \
    "sudo env AGENT_VERSION=$agent_version_escaped SKILLS_TARBALL=/tmp/golden-skills.tar.gz INSTALL_SKILLS=/tmp/install-skills.sh bash /tmp/setup-golden.sh" \
    || setup_rc=$?
if [[ "$setup_rc" -ne 0 ]]; then
    log "FAIL: setup-golden.sh exited $setup_rc in the box; not snapshotting"
    exit 1
fi
log "setup-golden.sh completed in the box"

# Snapshot the seed box, then point the candidate alias at the new snapshot id.
# `box snapshot` pauses the box and persists it to S3, emitting the record JSON.
log "snapshotting seed box $SEED_BOX_ID"
snap_json=$(hogland box snapshot "$SEED_BOX_ID")
SNAP_ID=$(printf '%s' "$snap_json" | jq -r '.id // empty')
if [[ -z "$SNAP_ID" ]]; then
    log "FAIL: box snapshot returned no id"
    printf '%s\n' "$snap_json" >&2
    exit 1
fi
log "pointing alias $ALIAS at snapshot $SNAP_ID"
hogland snapshot alias "$SNAP_ID" "$ALIAS"

log "bake complete: $SNAP_ID -> alias $ALIAS"
printf 'BAKED_SNAPSHOT_ID=%s\n' "$SNAP_ID"
