#!/usr/bin/env bash
# Bakes a warm PostHog dev stack into a VM sandbox so its filesystem snapshot can be
# published as the default base image for PostHog-internal cloud task runs (see
# products/tasks/backend/logic/services/dev_stack_image.py).
#
# What ends up in the image:
#   - every docker-compose.dev.yml service image pre-pulled into /var/lib/docker
#   - Postgres (main + persons + product DBs, including the Rust-migrated cyclotron /
#     behavioral-cohorts / flags-read-store databases) and ClickHouse fully migrated,
#     with the data living in the compose project's volumes/containers under
#     /var/lib/docker
#   - the dev toolchain `hogli start` needs but the VM base image lacks: brotli
#     (bin/download-mmdb), phrocs (the process manager bin/start requires), Go and the
#     Rust toolchain with sqlx-cli (bin/start-go-service / bin/start-rust-service and
#     the rust/bin migrators), plus a warm cargo registry for the rust workspace
#   - a warm uv cache, so the task-time `uv sync` is a fast linking pass
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

# Toolchain pins — keep in sync with .flox/env/manifest.toml, which is what dev
# machines (and therefore `hogli start`) are built against.
GO_VERSION=1.25.5
RUST_TOOLCHAIN=1.91.1
SQLX_CLI_VERSION=0.8.3

export RUSTUP_HOME=/opt/rust/rustup
export CARGO_HOME=/opt/rust/cargo

log() { echo "[bake] $(date -u +%H:%M:%S) $*"; }

# Compose hostnames (db, clickhouse, ...) resolve to 127.0.0.1 on dev machines via
# /etc/hosts. The sandbox runtime rewrites /etc/hosts at boot, so this only serves the
# bake itself; task-time runs set these up on their own, as on any dev machine.
for host in db redis7 kafka clickhouse clickhouse-coordinator objectstorage seaweedfs temporal; do
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
apt-get install -y --no-install-recommends brotli
rm -rf /var/lib/apt/lists/*

# Prebuilt phrocs release binary into /usr/local/bin (bin/start falls back to PATH
# when there is no flox-built tools/phrocs/dist binary).
bash tools/phrocs/install.sh

case "$(uname -m)" in
    x86_64) GO_ARCH=amd64 ;;
    aarch64) GO_ARCH=arm64 ;;
    *)
        echo "unsupported architecture: $(uname -m)" >&2
        exit 1
        ;;
esac
curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${GO_ARCH}.tar.gz" | tar -xz -C /usr/local
ln -sf /usr/local/go/bin/go /usr/local/go/bin/gofmt /usr/local/bin/

# Rust under /opt/rust, exposed through env-setting shims so any task-time process
# finds the toolchain regardless of $HOME or login-shell profile handling.
curl -fsSL https://sh.rustup.rs | sh -s -- -y --no-modify-path --profile minimal --default-toolchain "$RUST_TOOLCHAIN"
for tool in cargo rustc rustup; do
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

log "warming python environment (uv sync)"
# The checkout's .venv is discarded with the checkout; the uv cache persists in the
# image and makes the task-time `uv sync` a fast linking pass.
uv sync --frozen

log "pulling dev stack images"
# Warm every service image `hogli start` would pull. --ignore-pull-failures: services
# whose image tag is momentarily unpublished fall back to task-time pull/build instead
# of failing the whole bake.
docker compose -f docker-compose.dev.yml pull --quiet --ignore-pull-failures

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
# Leftover runtime files would confuse the task-time start-dockerd.
rm -f /var/run/docker.pid /var/run/docker.sock

log "cleaning up"
cd /
rm -rf "$BAKE_ROOT"

mkdir -p "$(dirname "$BAKE_MANIFEST")"
printf '{"baked_at": "%s", "posthog_sha": "%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$BAKED_SHA" > "$BAKE_MANIFEST"
log "bake complete at $BAKED_SHA"
