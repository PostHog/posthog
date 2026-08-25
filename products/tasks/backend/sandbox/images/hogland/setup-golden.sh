#!/usr/bin/env bash
# First-boot setup for the PostHog *tasks* golden snapshot.
#
# `hogland snapshot-build --setup-script` runs this once as root inside a fresh
# seed box, then snapshots the result and points an alias at it.
# `HoglandSandbox.create` restores every task sandbox from that alias, so a
# rebuild here is the hogland equivalent of publishing a new base image tag.
#
#   hogland snapshot-build \
#     --alias posthog-tasks-candidate \
#     --setup-script products/tasks/backend/sandbox/images/hogland/setup-golden.sh \
#     --inline-file products/tasks/backend/sandbox/images/git-guard.sh:/opt/posthog/bin/git:0755 \
#     --inline-file products/tasks/backend/sandbox/images/gh-guard.sh:/opt/posthog/bin/gh:0755 \
#     --inline-file products/tasks/backend/sandbox/images/cpu_billing_sampler.py:/usr/local/bin/posthog-cpu-billing-sampler:0755 \
#     --cpus 4 --memory-mib 16384 --disk-gib 64 --timeout 90m
#
# The steps here reconstruct products/tasks/backend/sandbox/images/Dockerfile.sandbox-base
# over exec. That Dockerfile stays the source of truth for what a task sandbox
# contains; keep the pins below in sync with its ARGs.
#
# Content delivery (the crux): snapshot-build has no file-push or exec API, only
# --inline-file (a heredoc capped at 256 KiB of bootstrap) and this script, which
# runs *inside* the box. So content arrives two ways:
#   * small, fixed posthog-owned files (the git/gh guards, the cpu sampler) ride
#     in as --inline-file, the way the devbox persona lays down its overlay units.
#   * the rendered skills and the @posthog/agent build both come from the already
#     published ghcr.io/posthog/posthog-sandbox-base image. The CD image build
#     renders the skill .md.j2 templates with a database (build:skills), merges in
#     the context-mill skills, and bakes the result at fixed paths; it also pins a
#     resolved @posthog/agent version. We `docker pull` that image inside the box
#     and `docker cp` those artifacts straight out, so the golden ships the SAME
#     rendered skills + agent the image ships. The image tag (templated in by the
#     workflow, default master) is the single knob for what the golden tracks.
#
# Do NOT write a success sentinel here: `hogland snapshot-build` appends
# `touch /var/lib/hog/snapshot-build-ok` as the final action and SSH-polls for it
# before snapshotting. `set -e` below is what makes that marker mean "every step
# passed" — a failing step aborts before the marker is written.

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

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

# Which posthog-sandbox-base image to source the rendered skills + the pinned
# @posthog/agent from. The workflow substitutes the tag at assembly time (default
# master; a workflow_dispatch input can override it); a hand run leaves the
# placeholder untouched and falls back to master. This tag is the single knob for
# what the golden tracks — bump it to move the golden to a different image build.
IMAGE_TAG="__SANDBOX_IMAGE_TAG__"
# Detect the un-substituted placeholder (a hand run that skipped the workflow's
# sed) and fall back to master. The sentinel is split so the workflow's global
# sed — which matches the contiguous token — replaces only the assignment above,
# never this comparison; bash concatenates the two literals back at runtime.
placeholder='__SANDBOX''_IMAGE_TAG__'
if [ -z "$IMAGE_TAG" ] || [ "$IMAGE_TAG" = "$placeholder" ]; then
    IMAGE_TAG="master"
fi
IMAGE_REF="ghcr.io/posthog/posthog-sandbox-base:${IMAGE_TAG}"

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
# services do not read /etc/environment. EnvironmentFile=-/etc/hogbox-env keeps
# the per-box create(env=...) values reaching exec processes on restore.
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
curl -fsSL --retry 5 --retry-all-errors --retry-max-time 60 --connect-timeout 10 \
    https://deb.nodesource.com/setup_24.x | bash -
apt-get install -y --no-install-recommends nodejs
rm -rf /var/lib/apt/lists/*

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

# --- Image-sourced content: rendered skills + pinned @posthog/agent -----------
# The rendered skills need a database to expand their .md.j2 templates, which is
# only available in the CD image build. Rather than reproduce that here, pull the
# published image and copy the already-rendered artifacts straight out of it, so
# the golden is content-equivalent to the image. The image is public on ghcr.io,
# so an anonymous `docker pull` works — no registry login is needed in the box.
log "sandbox-base image: pull ${IMAGE_REF}"
command -v docker >/dev/null 2>&1 || {
    echo "docker is required in the seed box to source skills + agent from ${IMAGE_REF}" >&2
    exit 1
}
docker pull "$IMAGE_REF"
img_cid="$(docker create "$IMAGE_REF")"
cleanup_img_cid() { [ -n "${img_cid:-}" ] && docker rm -f "$img_cid" >/dev/null 2>&1 || true; }
trap cleanup_img_cid EXIT

log "@posthog/agent in /scripts (version pinned to ${IMAGE_REF})"
# Pin to the exact @posthog/agent the image baked so the golden's agent-server
# matches it. Reading the version from the image keeps the image tag the one knob
# rather than resolving @latest independently (which could drift from the image).
agent_pkg_dir="$(mktemp -d)"
docker cp "$img_cid:/scripts/node_modules/@posthog/agent/package.json" "$agent_pkg_dir/package.json"
AGENT_VERSION="$(jq -r '.version // empty' "$agent_pkg_dir/package.json")"
rm -rf "$agent_pkg_dir"
[ -n "$AGENT_VERSION" ] || { echo "could not read @posthog/agent version from ${IMAGE_REF}" >&2; exit 1; }
log "@posthog/agent@${AGENT_VERSION} in /scripts"
mkdir -p /scripts
(cd /scripts && npm init -y && npm install "@posthog/agent@${AGENT_VERSION}")
test -x /scripts/node_modules/.bin/agent-server

log "skills: copy rendered skills out of ${IMAGE_REF}"
# The image was built with the same install-skills.sh, which lands the rendered
# skills at these exact paths (running as root, so HOME=/root). Copy them
# byte-for-byte into the same paths here. This replaces both the old sparse-clone
# of the skill sources and the context-mill zip fetch: the image already merges
# PostHog + context-mill skills, rendered.
mkdir -p /scripts/plugins /root/.agents /root/.claude
docker cp "$img_cid:/scripts/plugins/posthog" /scripts/plugins/
docker cp "$img_cid:/root/.agents/skills" /root/.agents/
docker cp "$img_cid:/root/.claude/skills" /root/.claude/
docker rm -f "$img_cid" >/dev/null
img_cid=""
trap - EXIT
# Drop the pulled image so it does not bloat the snapshot; the box never runs it.
docker rmi -f "$IMAGE_REF" >/dev/null 2>&1 || true

# Fail closed: a broken pull or an empty skills copy must not ship a golden that
# silently lost its skills.
for skills_target in /scripts/plugins/posthog/skills /root/.agents/skills /root/.claude/skills; do
    find "$skills_target" -name 'SKILL.md' -type f 2>/dev/null | grep -q . || {
        echo "no SKILL.md found under ${skills_target} after copying from ${IMAGE_REF}" >&2
        exit 1
    }
done

log "guards + cpu sampler (delivered as --inline-file)"
# The git/gh guards and the cpu sampler arrive as --inline-file (see the header),
# so they already exist at their target paths with mode 0755. The final verify
# below fails the bake if a hand run omitted those flags.
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
# env plus the per-box /etc/hogbox-env, then restart the daemon so the snapshot
# captures a hogpanion already re-exec'd with the new env.
if [ -d /etc/systemd/system ]; then
    dropin_dir=/etc/systemd/system/hogpanion.service.d
    mkdir -p "$dropin_dir"
    cat > "$dropin_dir/posthog-env.conf" <<EOF
[Service]
Environment="DEBIAN_FRONTEND=noninteractive"
Environment="TZ=UTC"
Environment="GH_TELEMETRY=false"
Environment="AGENTSH_SERVER=http://127.0.0.1:18080"
Environment="IS_SANDBOX=1"
Environment="PYTHONPATH=/tmp/workspace"
Environment="PATH=${STATIC_ENV_PATH}"
EnvironmentFile=-/etc/hogbox-env
EOF
    systemctl daemon-reload
    # daemon-reload does NOT re-exec a running unit, so the drop-in's new
    # Environment= only reaches hogpanion on its next restart. Without a restart
    # the snapshot freezes the OLD env, and restored task boxes' hog-exec children
    # lack IS_SANDBOX=1, the /opt/posthog/bin-first PATH (git/gh guards), and
    # PYTHONPATH. This script runs under hogpanion's cgroup, so a direct restart
    # would kill it mid-bake; fire the restart from a detached transient unit and
    # then poll until the daemon is back with a NEW main pid before returning.
    if systemctl cat hogpanion.service >/dev/null 2>&1; then
        old_pid="$(systemctl show hogpanion.service -p MainPID --value 2>/dev/null || echo 0)"
        systemd-run --collect --unit=hogpanion-reload --on-active=2 \
            systemctl restart hogpanion.service
        restarted=0
        for _ in $(seq 1 60); do
            new_pid="$(systemctl show hogpanion.service -p MainPID --value 2>/dev/null || echo 0)"
            if systemctl is-active --quiet hogpanion.service \
                && [ -n "$new_pid" ] && [ "$new_pid" != "0" ] && [ "$new_pid" != "$old_pid" ]; then
                restarted=1
                break
            fi
            sleep 1
        done
        if [ "$restarted" != "1" ]; then
            echo "hogpanion did not restart with the env drop-in (old pid ${old_pid})" >&2
            systemctl status hogpanion.service --no-pager || true
            exit 1
        fi
        log "hogpanion restarted (pid ${old_pid} -> ${new_pid}) with the env drop-in"
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
log "setup-golden complete"
