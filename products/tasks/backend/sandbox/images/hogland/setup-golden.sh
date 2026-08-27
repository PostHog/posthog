#!/usr/bin/env bash
# First-boot setup for the PostHog *tasks* golden snapshot.
#
# `bake-golden.sh` runs this once as root inside a fresh seed box (over SSH),
# then `box snapshot`s the result and points an alias at it.
# `HoglandSandbox.create` restores every task sandbox from that alias, so a
# rebuild here is the hogland equivalent of publishing a new base image tag.
#
# The steps here reconstruct products/tasks/backend/sandbox/images/Dockerfile.sandbox-base
# over exec. That Dockerfile stays the source of truth for what a task sandbox
# contains; keep the pins below in sync with its ARGs.
#
# Content delivery (the crux): the CI runner renders the skills itself with a
# database (the same `hogli build:skills` mechanism the Modal image build uses)
# and merges in the context-mill skills, then `bake-golden.sh` delivers the whole
# set into the box over SSH. Nothing is fished out of a published image. Content
# arrives two ways, both from `bake-golden.sh` before this script runs:
#   * small, fixed posthog-owned files (the git/gh guards, the cpu sampler) are
#     streamed to their target paths with mode 0755; this script only verifies
#     them (`test -x`), so they are ready before the checks below.
#   * the rendered skills tarball (SKILLS_TARBALL) and the shared installer
#     (INSTALL_SKILLS, the same install-skills.sh the image uses) are streamed in
#     too. This script extracts the tarball and runs the installer, so the golden
#     lands the SAME merged, rendered skills at the SAME paths the image uses.
# `@posthog/agent` is npm-installed here at AGENT_VERSION (default latest; the
# workflow resolves and pins an exact version), decoupled from any image.
#
# Success detection is the caller's: `bake-golden.sh` runs this over SSH and
# checks its exit code before snapshotting. `set -e` below makes a failing step
# abort with non-zero, so a broken bake never reaches `box snapshot`.
#
# Required env (set by bake-golden.sh over SSH):
#   SKILLS_TARBALL — path in the box to the rendered-skills tarball (.tar.gz)
#   INSTALL_SKILLS — path in the box to install-skills.sh
#   AGENT_VERSION  — @posthog/agent version to install (default: latest)

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

: "${SKILLS_TARBALL:?SKILLS_TARBALL is required (path in-box to the rendered-skills tarball)}"
: "${INSTALL_SKILLS:?INSTALL_SKILLS is required (path in-box to install-skills.sh)}"
AGENT_VERSION="${AGENT_VERSION:-latest}"

# --- Version pins, mirrored from Dockerfile.sandbox-base ARGs -----------------
GIT_VERSION=2.49.1
GIT_SHA256=310831de967f1c8c5e8ff55f92807dea89f83dc3d3d2a5d16c209bd01a31def1
UV_VERSION=0.11.15
RUFF_VERSION=0.14.11
TY_VERSION=0.0.29
GH_CLI_VERSION=2.97.0
AGENTSH_TAG=v0.18.3
AGENTSH_SHA256_AMD64=4ac486eea1e10600c29078a7a992d2067774edfb66be1318a2acf1fcf8b6d774
AGENTSH_SHA256_ARM64=d1393a27943d207442ea077b1d36d9561a8af5613e7b67d9f7d4fafd00626c6b
RTK_VERSION=0.43.0
RTK_SHA256_AMD64=ff8a1e7766496e175291a85aeca1dc97c9ff6df33e51e5893d1fbc78fea2a609
RTK_SHA256_ARM64=5519f7ca12e5c143a609f0d28a0a77b97413a8dce31c2681f1a41c24519a8731

APT_PACKAGES="curl wget git vim nano tree htop unzip zip jq \
build-essential pkg-config musl \
python3 python3-pip python3-venv python3-dev \
sqlite3 postgresql-client mysql-client redis-tools \
libssl-dev libcurl4-gnutls-dev libexpat1-dev libffi-dev libbz2-dev \
libreadline-dev libsqlite3-dev libncursesw5-dev xz-utils tk-dev \
libxml2-dev libxmlsec1-dev zlib1g-dev \
ca-certificates gnupg sudo"

# Dockerfile ENVs, made visible to every login/exec process. /etc/environment
# covers PAM sessions; the systemd drop-in covers the box's agent daemon, whose
# services do not read /etc/environment. Per-box create(env=...) values reach
# exec children through the adapter's per-exec env, not this drop-in.
STATIC_ENV_PATH="/opt/posthog/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

log() { printf '[setup-golden] %s\n' "$*" >&2; }

# --- curl with retries (transient reset must not fail the whole bake) ---------
fetch() {
    # fetch <url> <out>
    curl -fsSL --retry 5 --retry-all-errors --retry-max-time 60 --connect-timeout 10 -o "$2" "$1"
}

log "apt packages"
apt-get update
# shellcheck disable=SC2086 # word-splitting the package list is intended
apt-get install -y --no-install-recommends $APT_PACKAGES
rm -rf /var/lib/apt/lists/*

log "git ${GIT_VERSION} from source"
fetch "https://www.kernel.org/pub/software/scm/git/git-${GIT_VERSION}.tar.xz" /tmp/git.tar.xz
echo "${GIT_SHA256}  /tmp/git.tar.xz" | sha256sum -c -
mkdir /tmp/git
tar -xf /tmp/git.tar.xz -C /tmp/git --strip-components=1
make -C /tmp/git prefix=/usr NO_GETTEXT=YesPlease NO_TCLTK=YesPlease -j"$(nproc)" all
make -C /tmp/git prefix=/usr NO_GETTEXT=YesPlease NO_TCLTK=YesPlease install
rm -rf /tmp/git /tmp/git.tar.xz
git --version
git help -a | grep -q '[[:space:]]backfill'

log "node 24"
# The rootfs bakes node 22 into /usr/local/bin, which precedes /usr/bin (where
# nodesource installs 24) on STATIC_ENV_PATH and in sudo's secure_path. Remove
# the baked copy first, or `npm install @posthog/agent` and the runtime resolve
# node 22, not 24.
rm -f /usr/local/bin/node /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack
curl -fsSL --retry 5 --retry-all-errors --retry-max-time 60 --connect-timeout 10 \
    https://deb.nodesource.com/setup_24.x | bash -
apt-get install -y --no-install-recommends nodejs
rm -rf /var/lib/apt/lists/*
node_version="$(node -v)"
case "$node_version" in
    v24.*) log "node ${node_version}" ;;
    *) echo "expected node v24 after nodesource install, got ${node_version}" >&2; exit 1 ;;
esac

log "npm globals"
npm install -g yarn pnpm typescript ts-node nodemon

log "uv ${UV_VERSION} + ruff ${RUFF_VERSION} + ty ${TY_VERSION}"
# The Dockerfile takes uv from its pinned official image; without a container
# runtime we pin the same version's release tarball and verify its published
# checksum.
uv_arch="$(uname -m)"
uv_asset="uv-${uv_arch}-unknown-linux-gnu.tar.gz"
uv_base="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}"
fetch "${uv_base}/${uv_asset}" /tmp/uv.tar.gz
fetch "${uv_base}/${uv_asset}.sha256" /tmp/uv.tar.gz.sha256
(cd /tmp && echo "$(cut -d' ' -f1 uv.tar.gz.sha256)  uv.tar.gz" | sha256sum -c -)
tar -xzf /tmp/uv.tar.gz -C /tmp
install -m 755 "/tmp/uv-${uv_arch}-unknown-linux-gnu/uv" "/tmp/uv-${uv_arch}-unknown-linux-gnu/uvx" /usr/local/bin/
rm -rf /tmp/uv.tar.gz /tmp/uv.tar.gz.sha256 "/tmp/uv-${uv_arch}-unknown-linux-gnu"
UV_TOOL_BIN_DIR=/usr/local/bin uv tool install "ruff==${RUFF_VERSION}"
UV_TOOL_BIN_DIR=/usr/local/bin uv tool install "ty==${TY_VERSION}"
ruff --version
ty --version

log "gh CLI ${GH_CLI_VERSION}"
gh_arch="$(dpkg --print-architecture)"
fetch "https://github.com/cli/cli/releases/download/v${GH_CLI_VERSION}/gh_${GH_CLI_VERSION}_linux_${gh_arch}.deb" /tmp/gh.deb
dpkg -i /tmp/gh.deb
rm /tmp/gh.deb

log "agentsh ${AGENTSH_TAG}"
agentsh_version="${AGENTSH_TAG#v}"
agentsh_arch="$(dpkg --print-architecture)"
case "$agentsh_arch" in
    amd64) agentsh_sha256="$AGENTSH_SHA256_AMD64" ;;
    arm64) agentsh_sha256="$AGENTSH_SHA256_ARM64" ;;
    *) echo "Unsupported architecture for agentsh: $agentsh_arch" >&2; exit 1 ;;
esac
fetch "https://github.com/canyonroad/agentsh/releases/download/${AGENTSH_TAG}/agentsh_${agentsh_version}_linux_${agentsh_arch}.deb" /tmp/agentsh.deb
echo "${agentsh_sha256}  /tmp/agentsh.deb" | sha256sum -c -
dpkg -i /tmp/agentsh.deb
rm /tmp/agentsh.deb
agentsh --version
mkdir -p /var/lib/agentsh/sessions /var/lib/agentsh/quarantine /var/log/agentsh
chmod 777 /var/lib/agentsh /var/lib/agentsh/sessions /var/lib/agentsh/quarantine /var/log/agentsh

log "rtk ${RTK_VERSION}"
rtk_arch="$(dpkg --print-architecture)"
case "$rtk_arch" in
    amd64) rtk_asset="rtk-x86_64-unknown-linux-musl.tar.gz"; rtk_sha256="$RTK_SHA256_AMD64" ;;
    arm64) rtk_asset="rtk-aarch64-unknown-linux-gnu.tar.gz"; rtk_sha256="$RTK_SHA256_ARM64" ;;
    *) echo "Unsupported architecture for rtk: $rtk_arch" >&2; exit 1 ;;
esac
fetch "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/${rtk_asset}" /tmp/rtk.tar.gz
echo "${rtk_sha256}  /tmp/rtk.tar.gz" | sha256sum -c -
tar -xzf /tmp/rtk.tar.gz -C /usr/local/bin rtk
rm /tmp/rtk.tar.gz
rtk --version

# --- Agent SDK: @posthog/agent, npm-installed at AGENT_VERSION ----------------
# Mirrors Dockerfile.sandbox-base's `npm install @posthog/agent@${AGENT_VERSION}`
# into /scripts. The workflow resolves and pins an exact published version so the
# golden's agent-server is reproducible; a hand run defaults to latest.
log "@posthog/agent@${AGENT_VERSION} in /scripts"
mkdir -p /scripts
(cd /scripts && npm init -y && npm install "@posthog/agent@${AGENT_VERSION}")
test -x /scripts/node_modules/.bin/agent-server

# --- Skills: install the runner-rendered set from the delivered tarball -------
# The CI runner renders the skills with a database (hogli build:skills) and merges
# in the context-mill skills, exactly as the Modal image build does, then delivers
# the result as SKILLS_TARBALL. Extract it and run the SAME install-skills.sh the
# image uses (delivered as INSTALL_SKILLS), so the golden lands the merged, rendered
# skills at the SAME paths: /scripts/plugins/posthog/skills, /root/.agents/skills,
# /root/.claude/skills, plus /scripts/plugins/posthog/plugin.json. install-skills.sh
# keys off $HOME, so pin it to /root (this script runs as root in the box).
log "skills: install runner-rendered set from ${SKILLS_TARBALL}"
test -f "$SKILLS_TARBALL" || { echo "SKILLS_TARBALL ${SKILLS_TARBALL} not found in box" >&2; exit 1; }
test -f "$INSTALL_SKILLS" || { echo "INSTALL_SKILLS ${INSTALL_SKILLS} not found in box" >&2; exit 1; }
skills_extract_dir="$(mktemp -d)"
tar -xzf "$SKILLS_TARBALL" -C "$skills_extract_dir"
HOME=/root bash "$INSTALL_SKILLS" "$skills_extract_dir"
rm -rf "$skills_extract_dir"

# Fail closed: an empty tarball or a broken install must not ship a golden that
# silently lost its skills.
for skills_target in /scripts/plugins/posthog/skills /root/.agents/skills /root/.claude/skills; do
    find "$skills_target" -name 'SKILL.md' -type f 2>/dev/null | grep -q . || {
        echo "no SKILL.md found under ${skills_target} after installing ${SKILLS_TARBALL}" >&2
        exit 1
    }
done

log "guards + cpu sampler (delivered over ssh by bake-golden.sh)"
# The git/gh guards and the cpu sampler are streamed to their target paths with
# mode 0755 by bake-golden.sh before this script runs. The final verify below
# fails the bake if a hand run omitted them.
test -x /opt/posthog/bin/git
test -x /opt/posthog/bin/gh
test -x /usr/local/bin/posthog-cpu-billing-sampler

log "git identity"
git config --global user.email "code@posthog.com"
git config --global user.name "PostHog Desktop"

log "static env (/etc/environment + agent-daemon systemd drop-in)"
mkdir -p /tmp/workspace
cat > /etc/environment <<EOF
DEBIAN_FRONTEND="noninteractive"
TZ="UTC"
GH_TELEMETRY="false"
AGENTSH_SERVER="http://127.0.0.1:18080"
IS_SANDBOX="1"
PYTHONPATH="/tmp/workspace"
PATH="${STATIC_ENV_PATH}"
EOF
# Lay down the agent-daemon drop-in so exec processes inherit the container-style
# env, then restart the daemon so the snapshot captures a hogpanion already
# re-exec'd with the new env.
if [ -d /etc/systemd/system ]; then
    dropin_dir=/etc/systemd/system/hogpanion.service.d
    mkdir -p "$dropin_dir"
    # No EnvironmentFile= here. A per-box /etc/hogbox-env would let an unreserved
    # key such as PATH override these guard vars (EnvironmentFile settings win
    # over Environment= regardless of order), routing hog-exec children through
    # /usr/bin/git instead of the wrapped /opt/posthog/bin/git. Per-box env still
    # reaches exec children through the adapter's per-exec env, not this drop-in.
    # HOME/USER/LOGNAME: hogpanion runs as root with no User= and hands exec
    # children bare os.Environ(), so nothing sets HOME. Skills resolve
    # $HOME/.agents/skills and git reads /root/.gitconfig; without HOME a set -u
    # task step dies. Pin them to root so exec children inherit a usable home.
    cat > "$dropin_dir/posthog-env.conf" <<EOF
[Service]
Environment="DEBIAN_FRONTEND=noninteractive"
Environment="TZ=UTC"
Environment="GH_TELEMETRY=false"
Environment="AGENTSH_SERVER=http://127.0.0.1:18080"
Environment="IS_SANDBOX=1"
Environment="PYTHONPATH=/tmp/workspace"
Environment="PATH=${STATIC_ENV_PATH}"
Environment="HOME=/root"
Environment="USER=root"
Environment="LOGNAME=root"
EOF
    systemctl daemon-reload
    # daemon-reload does NOT re-exec a running unit, so the drop-in's new
    # Environment= only reaches hogpanion on its next restart. Without a restart
    # the snapshot freezes the OLD env, and restored task boxes' hog-exec children
    # lack IS_SANDBOX=1, the /opt/posthog/bin-first PATH (git/gh guards), and
    # PYTHONPATH. This script runs under hogpanion's cgroup, so a direct restart
    # would kill it mid-bake; fire the restart from a detached transient unit and
    # then poll until the daemon is back and reporting ready before returning.
    if systemctl cat hogpanion.service >/dev/null 2>&1; then
        old_pid="$(systemctl show hogpanion.service -p MainPID --value 2>/dev/null || echo 0)"
        systemd-run --collect --unit=hogpanion-reload --on-active=2 \
            systemctl restart hogpanion.service
        # Gate on hogpanion reporting READY, not just on a new MainPID. hogpanion
        # is Type=simple: the pid changes at execve, but `ready` only flips true
        # after runBoot finishes, so a pid-only wait can snapshot a half-booted
        # daemon. Require a NEW pid (proves the restart fired, not the old still-
        # ready daemon) AND the status endpoint reporting ready:true.
        ready=0
        for _ in $(seq 1 90); do
            new_pid="$(systemctl show hogpanion.service -p MainPID --value 2>/dev/null || echo 0)"
            if systemctl is-active --quiet hogpanion.service \
                && [ -n "$new_pid" ] && [ "$new_pid" != "0" ] && [ "$new_pid" != "$old_pid" ] \
                && curl -sf http://localhost:7682/status 2>/dev/null | jq -e '.ready == true' >/dev/null 2>&1; then
                ready=1
                break
            fi
            sleep 1
        done
        if [ "$ready" != "1" ]; then
            echo "hogpanion did not restart and report ready with the env drop-in (old pid ${old_pid})" >&2
            systemctl status hogpanion.service --no-pager || true
            exit 1
        fi
        log "hogpanion restarted (pid ${old_pid} -> ${new_pid}) and reported ready with the env drop-in"
    else
        log "hogpanion.service not present; skipping restart (drop-in applies on next start)"
    fi
fi

log "verify"
python3 --version
node --version
npm --version
gh --version
rtk --version
agentsh --version
test -x /scripts/node_modules/.bin/agent-server
test -x /opt/posthog/bin/git
test -x /opt/posthog/bin/gh

# LAST step: strip the ephemeral CI ssh key so it does not persist into the
# snapshot and therefore into every restored task box. Production restores with
# access_type: none, and hogpanion returns early on an empty key list, so a
# non-empty authorized_keys from the bake would survive into live boxes. Truncate
# every user's authorized_keys the bake could have populated. This is the final
# action: no SSH step runs after it (the current session stays open; box snapshot
# is driven over the hogplane API, not SSH).
for ak in /home/hog/.ssh/authorized_keys /root/.ssh/authorized_keys; do
    [ -f "$ak" ] && : >"$ak"
done
log "truncated CI ssh authorized_keys"
log "setup-golden complete"
