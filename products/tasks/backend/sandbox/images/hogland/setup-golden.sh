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
# runs *inside* the box. So the same split the two existing hogland personas use:
#   * small, fixed posthog-owned files (the git/gh guards, the cpu sampler) ride
#     in as --inline-file, the way the devbox persona lays down its overlay units.
#   * the skills payload is multi-MB and cannot fit the bootstrap, so this script
#     fetches it over the network from inside the box, the way the preview persona
#     clones posthog and pulls its image. We sparse-clone PostHog/posthog for the
#     skill sources plus install-skills.sh, and pull the context-mill skills from
#     their public release zip — the same two sources the CD image build merges.
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

# @posthog/agent version to install into /scripts. The CD image resolves the
# latest published version on npm; the workflow passes the same value through
# POSTHOG_AGENT_VERSION so the golden tracks the same release.
AGENT_VERSION="${POSTHOG_AGENT_VERSION:-latest}"

# Ref of PostHog/posthog to source skills + install-skills.sh from. The workflow
# sets it to the commit it ran against; default to master for a hand-run bake.
POSTHOG_REF="${POSTHOG_REF:-master}"
CONTEXT_MILL_ZIP_URL="https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip"

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

log "@posthog/agent@${AGENT_VERSION} in /scripts"
mkdir -p /scripts
(cd /scripts && npm init -y && npm install "@posthog/agent@${AGENT_VERSION}")
test -x /scripts/node_modules/.bin/agent-server

log "skills: clone posthog@${POSTHOG_REF} (sources + install-skills.sh) + context-mill zip"
# Mirror of the preview persona's in-box clone. A blob-filtered sparse checkout
# keeps only the skill sources and the sandbox image scripts, so the clone stays
# small and the golden carries no posthog source once we remove it below.
clone_dir="$(mktemp -d)"
git clone --filter=blob:none --sparse --depth 1 --branch "$POSTHOG_REF" \
    https://github.com/PostHog/posthog "$clone_dir"
git -C "$clone_dir" sparse-checkout set \
    products/tasks/backend/sandbox/images \
    products

# Flatten every products/*/skills/<skill>/ into one staging dir, the layout
# install-skills.sh expects. Skills are plain SKILL.md today, so this copy
# matches what the CD build ships; a future Jinja-templated skill (SKILL.md.j2)
# would need the CD renderer and is not handled here.
skills_stage="$(mktemp -d)"
for skills_dir in "$clone_dir"/products/*/skills; do
    [ -d "$skills_dir" ] || continue
    for skill in "$skills_dir"/*/; do
        [ -d "$skill" ] || continue
        cp -r "$skill" "$skills_stage/$(basename "$skill")"
    done
done

# Context-mill skills from their public release zip (the exact source the CD
# image build merges in). Strip the omnibus- name prefix the same way.
cm_tmp="$(mktemp -d)"
fetch "$CONTEXT_MILL_ZIP_URL" "$cm_tmp/cm.zip"
unzip -q -o "$cm_tmp/cm.zip" -d "$cm_tmp/outer"
while IFS= read -r inner_zip; do
    skill_name="$(basename "$inner_zip" .zip)"
    skill_name="${skill_name#omnibus-}"
    mkdir -p "$skills_stage/$skill_name"
    unzip -q -o "$inner_zip" -d "$skills_stage/$skill_name"
    find "$skills_stage/$skill_name" -name 'SKILL.md' -type f -exec sed -i 's/^\(name: *\)omnibus-/\1/' {} +
done < <(find "$cm_tmp/outer" -name 'omnibus-*.zip' -type f)

bash "$clone_dir/products/tasks/backend/sandbox/images/install-skills.sh" "$skills_stage"

log "guards + cpu sampler into place"
# The git/gh guards and the cpu sampler arrive as --inline-file (see the header),
# so they already exist at their target paths. Fall back to the clone if a hand
# run omitted the --inline-file flags, so the script is self-contained either way.
mkdir -p /opt/posthog/bin
images_dir="$clone_dir/products/tasks/backend/sandbox/images"
[ -f /opt/posthog/bin/git ] || cp "$images_dir/git-guard.sh" /opt/posthog/bin/git
[ -f /opt/posthog/bin/gh ] || cp "$images_dir/gh-guard.sh" /opt/posthog/bin/gh
[ -f /usr/local/bin/posthog-cpu-billing-sampler ] || cp "$images_dir/cpu_billing_sampler.py" /usr/local/bin/posthog-cpu-billing-sampler
chmod +x /opt/posthog/bin/git /opt/posthog/bin/gh /usr/local/bin/posthog-cpu-billing-sampler

rm -rf "$clone_dir" "$skills_stage" "$cm_tmp"

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
# env plus the per-box /etc/hogbox-env. We do NOT restart the daemon in-bootstrap:
# this script runs under that daemon's cgroup, so restarting it here would kill
# the script before snapshot-build's success marker is written. The drop-in
# applies on the daemon's next (re)start. Validating that exec processes see this
# env after a real restore is a live-cluster check (see GOLDEN_CI_RUNBOOK.md).
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
    systemctl daemon-reload || true
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
