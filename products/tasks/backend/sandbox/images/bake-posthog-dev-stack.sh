#!/usr/bin/env bash
# Bakes a warm PostHog dev stack into a VM sandbox so its filesystem snapshot can be
# published as the default base image for PostHog-internal cloud task runs (see
# products/tasks/backend/logic/services/dev_stack_image.py).
#
# What ends up in the image:
#   - every default-profile docker-compose.dev.yml service image pre-pulled into
#     /var/lib/docker (profile-gated services are not warmed: the default task intent
#     activates no compose profiles, so task runs never pull them)
#   - Postgres (main + persons + product DBs, including the Rust-migrated cyclotron /
#     behavioral-cohorts / flags-read-store databases) and ClickHouse fully migrated,
#     with the data living in the compose project's volumes/containers under
#     /var/lib/docker
#   - the dev toolchain `hogli start` needs but the VM base image lacks: brotli
#     (bin/download-mmdb), phrocs (the process manager bin/start requires), Go and the
#     Rust toolchain — with rustfmt/clippy (hogli format:rust, CI-parity cargo clippy)
#     and sqlx-cli (bin/start-go-service / bin/start-rust-service and the rust/bin
#     migrators) — plus warm cargo-registry and Go-module caches for the workspaces
#   - a warm uv cache, so the task-time `uv sync` is a fast linking pass
#   - a warm pnpm content-addressed store, so the task-time `pnpm install` is a fast
#     linking pass, plus Playwright's Chromium (and its system libraries) for
#     Storybook builds and screenshot runs
#   - /usr/local/bin/bootstrap-dev-stack, the one-shot task-time bootstrap (restores
#     the compose /etc/hosts aliases the sandbox boot wiped, starts dockerd)
#
# Build outputs are deliberately NOT baked: the checkout — node_modules, Storybook
# dist, Vite/Turbo caches — is deleted before the snapshot, so frontend builds always
# run from the task's own source instead of silently reflecting the baked commit.
#
# `hogli start` on a task VM then skips the multi-gigabyte image pulls and runs only
# the migrations that landed after the bake, instead of the full history from scratch.
#
# The toolchain lives here rather than in Dockerfile.sandbox-vm on purpose: the plain
# VM base serves every org's VM runs and stays lean; only the PostHog-internal prebaked
# image needs a full dev toolchain.
#
# Runs as root inside a Modal VM sandbox created from SandboxTemplate.VM_BASE.
set -euo pipefail

BAKE_ROOT=/tmp/posthog-dev-stack-bake
REPO_DIR="$BAKE_ROOT/posthog"
BAKE_MANIFEST=/opt/posthog/dev-stack-bake.json

# Toolchain pins — versions in sync with .flox/env/manifest.toml, which is what dev
# machines (and therefore `hogli start`) are built against. The sha256 pins come from
# the vendors' published manifests (go.dev/dl, static.rust-lang.org/rustup/archive) and
# guard the privileged downloads below: a tampered artifact fails the bake instead of
# being published into the shared internal image. Bump them together with the versions.
GO_VERSION=1.25.5
GO_SHA256_AMD64=9e9b755d63b36acf30c12a9a3fc379243714c1c6d3dd72861da637f336ebb35b
GO_SHA256_ARM64=b00b694903d126c588c378e72d3545549935d3982635ba3f7a964c9fa23fe3b9
RUSTUP_VERSION=1.29.0
RUSTUP_SHA256_AMD64=4acc9acc76d5079515b46346a485974457b5a79893cfb01112423c89aeb5aa10
RUSTUP_SHA256_ARM64=9732d6c5e2a098d3521fca8145d826ae0aaa067ef2385ead08e6feac88fa5792
RUST_TOOLCHAIN=1.91.1
SQLX_CLI_VERSION=0.8.3

export RUSTUP_HOME=/opt/rust/rustup
export CARGO_HOME=/opt/rust/cargo

log() { echo "[bake] $(date -u +%H:%M:%S) $*"; }

# Compose hostnames (db, clickhouse, ...) that resolve to 127.0.0.1 on dev machines via
# /etc/hosts. Needed twice: during the bake itself, and again at task time — the sandbox
# runtime rewrites /etc/hosts at boot, so the baked bootstrap-dev-stack helper (installed
# below) restores them for the run.
COMPOSE_HOSTS=(db redis7 kafka clickhouse clickhouse-coordinator objectstorage seaweedfs temporal)
for host in "${COMPOSE_HOSTS[@]}"; do
    grep -qE "127\.0\.0\.1[[:space:]].*\b${host}\b" /etc/hosts || echo "127.0.0.1 ${host}" >> /etc/hosts
done

log "starting dockerd"
# The first invocation's exec can be reaped while dockerd brings up its bridge
# (see Dockerfile.sandbox-vm) — the helper is idempotent, so just run it again.
start-dockerd || start-dockerd
docker info > /dev/null

log "cloning posthog/posthog"
rm -rf "$BAKE_ROOT"
mkdir -p "$BAKE_ROOT"
# The directory basename must be "posthog": docker compose derives the project name
# (and therefore volume/container names) from it, and it has to match the project name
# task-time runs get from their /tmp/workspace/repos/posthog/posthog checkout.
git clone --depth 1 https://github.com/posthog/posthog.git "$REPO_DIR"
cd "$REPO_DIR"
BAKED_SHA=$(git rev-parse HEAD)
export COMPOSE_PROJECT_NAME=posthog

log "installing dev toolchain (brotli, phrocs, go, rust)"
# On dev machines flox provides these; the sandbox has no flox, so `hogli start`
# dead-ends without them: bin/start fails at bin/download-mmdb (brotli) and then at
# process-manager resolution (phrocs), and the Go/Rust procs and rust/bin migrators
# need their toolchains.
apt-get update
apt-get install -y --no-install-recommends brotli make
rm -rf /var/lib/apt/lists/*

case "$(uname -m)" in
    x86_64)
        GO_ARCH=amd64
        GO_SHA256="$GO_SHA256_AMD64"
        RUSTUP_TARGET=x86_64-unknown-linux-gnu
        RUSTUP_SHA256="$RUSTUP_SHA256_AMD64"
        ;;
    aarch64)
        GO_ARCH=arm64
        GO_SHA256="$GO_SHA256_ARM64"
        RUSTUP_TARGET=aarch64-unknown-linux-gnu
        RUSTUP_SHA256="$RUSTUP_SHA256_ARM64"
        ;;
    *)
        echo "unsupported architecture: $(uname -m)" >&2
        exit 1
        ;;
esac
curl -fsSL -o /tmp/go.tar.gz "https://go.dev/dl/go${GO_VERSION}.linux-${GO_ARCH}.tar.gz"
echo "${GO_SHA256}  /tmp/go.tar.gz" | sha256sum -c -
tar -xzf /tmp/go.tar.gz -C /usr/local
rm /tmp/go.tar.gz
ln -sf /usr/local/go/bin/go /usr/local/go/bin/gofmt /usr/local/bin/

# phrocs is built from this checkout rather than downloaded via tools/phrocs/install.sh:
# the phrocs-latest release that installer trusts is mutable and ships checksums.txt
# next to its binaries, so verifying one against the other proves nothing an attacker
# altering the release could not fake. The source build (with go.sum-pinned deps)
# derives from the same HTTPS-cloned commit the rest of the bake already executes as
# root — and is what bin/start treats as canonical anyway; task-time checkouts have no
# flox-built dist binary and resolve phrocs from PATH.
make -C tools/phrocs build
install -m 0755 tools/phrocs/dist/phrocs /usr/local/bin/phrocs
phrocs --version

# Rust under /opt/rust, exposed through env-setting shims so any task-time process
# finds the toolchain regardless of $HOME or login-shell profile handling. A pinned,
# checksum-verified rustup-init binary instead of piping sh.rustup.rs into sh; rustup
# itself then verifies the toolchain components against the channel manifest.
curl -fsSL -o /tmp/rustup-init "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/${RUSTUP_TARGET}/rustup-init"
echo "${RUSTUP_SHA256}  /tmp/rustup-init" | sha256sum -c -
chmod +x /tmp/rustup-init
# minimal profile plus the two components the repo's standard Rust workflows need on
# top of it: hogli format:rust runs rustfmt directly, and reproducing ci-rust locally
# runs cargo clippy — both are in .flox/env/manifest.toml for dev machines too.
/tmp/rustup-init -y --no-modify-path --profile minimal --component rustfmt --component clippy \
    --default-toolchain "$RUST_TOOLCHAIN"
rm /tmp/rustup-init
for tool in cargo rustc rustup rustfmt cargo-fmt cargo-clippy clippy-driver; do
    printf '%s\n' \
        '#!/bin/sh' \
        'export RUSTUP_HOME="${RUSTUP_HOME:-/opt/rust/rustup}" CARGO_HOME="${CARGO_HOME:-/opt/rust/cargo}"' \
        "exec /opt/rust/cargo/bin/$tool \"\$@\"" > "/usr/local/bin/$tool"
    chmod +x "/usr/local/bin/$tool"
done

log "installing sqlx-cli (rust/bin migrators)"
cargo install sqlx-cli --version "$SQLX_CLI_VERSION" --locked --no-default-features --features native-tls,postgres
ln -sf /opt/rust/cargo/bin/sqlx /usr/local/bin/sqlx

log "warming cargo registry for the rust workspace"
# Download-only: task-time `cargo run` in bin/start-rust-service still compiles, but
# skips fetching the whole dependency graph. The compiled target/ dir lives inside the
# checkout and is discarded with it, so it cannot be warmed here.
(cd rust && cargo fetch)

log "warming go module cache (livestream)"
# Mirrors the cargo fetch above: GOMODCACHE defaults to /root/go/pkg/mod, outside the
# checkout, so a task-time bin/start-go-service skips the cold module download.
(cd livestream && go mod download)

log "warming python environment (uv sync)"
# The checkout's .venv is discarded with the checkout; the uv cache persists in the
# image and makes the task-time `uv sync` a fast linking pass.
uv sync --frozen

log "warming pnpm store"
# pnpm fetch downloads every package in pnpm-lock.yaml into the content-addressed
# store (under ~/.local/share/pnpm), which lives outside the checkout and survives the
# cleanup below — the task-time `pnpm install` becomes mostly a linking pass. Bake and
# task time run the same image's pnpm, so the store layout always matches.
pnpm fetch --frozen-lockfile
# Link a full node_modules once: it backfills anything fetch skipped (git/tarball
# resolutions) and provides the workspace-pinned playwright CLI for the browser
# install below. --ignore-scripts keeps third-party postinstall hooks from failing
# the bake — the deliberate cost is that native-addon builds (node-rdkafka's node-gyp
# compile, chiefly) are not warmed and still compile during the task-time install,
# which runs scripts as usual. node_modules itself is discarded with the checkout.
pnpm install --prefer-offline --frozen-lockfile --ignore-scripts

log "installing playwright chromium (+ system deps)"
# Storybook builds and screenshot runs drive Playwright's Chromium. Browsers land in
# ~/.cache/ms-playwright, outside the checkout; --with-deps apt-installs the shared
# libraries Chromium needs. The version follows the workspace's @playwright/test pin —
# if a task's checkout bumps the pin, playwright just downloads the newer build then.
node_modules/.bin/playwright install --with-deps chromium
rm -rf /var/lib/apt/lists/*

log "pulling dev stack images"
# Warm every service image a default-intent `hogli start` would pull (profile-gated
# services are deliberately left cold — see the header). --ignore-pull-failures: services
# whose image tag is momentarily unpublished fall back to task-time pull/build instead
# of failing the whole bake.
docker compose -f docker-compose.dev.yml pull --quiet --ignore-pull-failures
# --ignore-pull-failures exits 0 no matter how many pulls failed, and a silently-cold
# image costs every task run the multi-gigabyte pull this bake exists to remove — so
# name anything missing from the warm set where bake logs are read.
while read -r image; do
    docker image inspect "$image" > /dev/null 2>&1 || log "WARNING: image not warmed (pull failed): ${image}"
done < <(docker compose -f docker-compose.dev.yml config --images | sort -u)

log "starting datastores"
# Only what migrations need. --no-build so a service whose pull failed above can never
# trigger a from-source image build during the bake; everything else starts at task time.
docker compose -f docker-compose.dev.yml up -d --no-build db redis7 zookeeper kafka clickhouse objectstorage
bin/wait-for-docker

log "running migrations"
# Mirror the env bin/start assembles for the migrate-* units: committed defaults from
# the checked-in env files (loaded with the same skip-if-set, skip-comments semantics),
# plus the derived persons URL. DEBUG=1 from .env.development keeps Django's insecure
# dev SECRET_KEY default acceptable.
load_env_defaults() {
    while IFS='=' read -r name value; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        # op:// refs only resolve under `op run` (see bin/start); exporting the literal
        # would bake a garbage value into the image.
        [[ "$value" == *op://* ]] && continue
        if [[ -z "${!name:-}" ]]; then
            export "$name=$value"
        fi
    done < "$1"
}
load_env_defaults .env.development
load_env_defaults .env.services
export PERSONS_DB_WRITER_URL="${PERSONS_DB_WRITER_URL:-postgres://posthog:posthog@db:5432/posthog_persons}"

# shellcheck disable=SC1091
source .venv/bin/activate
# ClickHouse runs strictly after Postgres: bin/migrate parallelizes the two scopes when
# both are requested, but on a fresh database migrate_clickhouse crashes until Postgres
# migrations have created posthog_instancesetting (the same race bin/mprocs.yaml gates
# with wait-for-postgres-tables).
bin/migrate --scope=postgres --scope=persons
bin/migrate --scope=clickhouse

log "running rust-driven migrations"
# Same connection URLs bin/start derives for these scopes; the rust/bin migrators
# otherwise default to localhost with per-store host/user envs.
export CYCLOTRON_DATABASE_URL="${CYCLOTRON_DATABASE_URL:-postgres://posthog:posthog@db:5432/cyclotron}"
export CYCLOTRON_NODE_DATABASE_URL="${CYCLOTRON_NODE_DATABASE_URL:-postgres://posthog:posthog@db:5432/cyclotron_node}"
export BEHAVIORAL_COHORTS_DATABASE_URL="${BEHAVIORAL_COHORTS_DATABASE_URL:-postgres://posthog:posthog@db:5432/behavioral_cohorts}"
export FLAGS_READ_STORE_DATABASE_URL="${FLAGS_READ_STORE_DATABASE_URL:-postgres://posthog:posthog@db:5432/flags_read_store}"
bin/migrate --scope=cyclotron --scope=behavioral-cohorts --scope=flags-read-store

log "stopping dev stack"
# stop (not down): the stopped containers keep their anonymous volumes — ClickHouse
# keeps its data in one — and `docker compose up` at task time reuses them as long as
# the compose config still matches.
docker compose -f docker-compose.dev.yml stop --timeout 120

log "stopping dockerd"
if [[ -f /var/run/docker.pid ]]; then
    kill "$(cat /var/run/docker.pid)" 2> /dev/null || true
    for _ in $(seq 1 120); do
        docker info > /dev/null 2>&1 || break
        sleep 1
    done
fi
# Fail closed rather than snapshot with a live daemon: the loop above swallows the
# did-it-exit signal, and this image is shared fleet-wide — a bake with a wedged
# dockerd is not a state worth publishing.
if docker info > /dev/null 2>&1; then
    echo "dockerd still running after 120s; refusing to snapshot" >&2
    exit 1
fi
# Leftover runtime files would confuse the task-time start-dockerd.
rm -f /var/run/docker.pid /var/run/docker.sock

log "cleaning up"
# The checkout goes away — node_modules, Storybook dist, Vite/Turbo caches included.
# Deliberate: baked build output would reflect the baked commit, not the task's
# checkout, so e.g. Storybook screenshots would silently miss the agent's edits.
# The warmed stores above keep the task-time installs that precede a rebuild cheap.
cd /
rm -rf "$BAKE_ROOT"

log "installing task-time bootstrap helper"
# A restored sandbox is not self-starting: the sandbox runtime rewrites /etc/hosts at
# boot and dockerd does not autostart. This one-shot, idempotent helper restores both
# so a task-time `hogli start` finds the baked docker state. It lives in the image (not
# the checkout) because it configures the VM itself, independent of any clone.
cat > /usr/local/bin/bootstrap-dev-stack << EOF
#!/usr/bin/env bash
# Task-time bootstrap for the prebaked PostHog dev stack (written by
# bake-posthog-dev-stack.sh). Idempotent — safe to re-run.
set -euo pipefail
# Pin PATH to system dirs: a directory resume can mount an untrusted workspace and a
# poisoned PATH could otherwise resolve start-dockerd/docker/grep to attacker binaries.
# The provisioning-side launcher already scrubs the environment, but harden the helper
# itself so it is safe however it is invoked. start-dockerd lives in /usr/local/bin.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
for host in ${COMPOSE_HOSTS[*]}; do
    grep -qE "127\\.0\\.0\\.1[[:space:]].*\\b\${host}\\b" /etc/hosts || echo "127.0.0.1 \${host}" >> /etc/hosts
done
/usr/local/bin/start-dockerd || /usr/local/bin/start-dockerd
docker info > /dev/null
echo "dev stack ready — from the posthog checkout: uv sync && source .venv/bin/activate && hogli start -y -d && hogli wait"
EOF
chmod +x /usr/local/bin/bootstrap-dev-stack

mkdir -p "$(dirname "$BAKE_MANIFEST")"
printf '{"baked_at": "%s", "posthog_sha": "%s", "bootstrap": "bootstrap-dev-stack"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$BAKED_SHA" > "$BAKE_MANIFEST"
log "bake complete at $BAKED_SHA"
