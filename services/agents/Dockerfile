# PostHog agent-platform runtime image.
#
# Single image, four entrypoints: ingress, runner, janitor, migrate.
# The deploy manifest picks which one runs in each replica / Job:
#
#   command: ["node", "dist/ingress.mjs"]
#   command: ["node", "dist/runner.mjs"]
#   command: ["node", "dist/janitor.mjs"]
#   command: ["node", "dist/migrate.mjs", "up"]
#
# Build from repo root so pnpm can resolve the workspace:
#
#   docker build -f services/agents/Dockerfile -t posthog-agents .
#
# Reference: services/mcp/Dockerfile (same bundling strategy — esbuild
# emits self-contained .mjs, runtime has no node_modules).

# Pinned to .nvmrc (24.13.0). The three runtime services declare
# `engines.node: ">=24 <25"` and import top-level await.
ARG NODE_VERSION=24.13.0
ARG NODE_IMAGE=node:${NODE_VERSION}-bookworm-slim

#
# Build stage — workspace install + esbuild bundling.
#
FROM ${NODE_IMAGE} AS build
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Build toolchain for `node-rdkafka`'s gyp + Confluent's librdkafka 2.10.1.
# Same package pins as Dockerfile.node so the agent stack stays on the
# same librdkafka as the rest of the PostHog node fleet (the runner can
# load KafkaLogSink the moment `KAFKA_BROKERS` is set — no rebuild).
# `BUILD_LIBRDKAFKA=0` tells node-rdkafka to skip its bundled build and
# link against the system one we just installed.
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget gnupg ca-certificates && \
    mkdir -p /etc/apt/keyrings && \
    wget -qO - https://packages.confluent.io/clients/deb/archive.key | \
        gpg --dearmor -o /etc/apt/keyrings/confluent-clients.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/confluent-clients.gpg] https://packages.confluent.io/clients/deb/ bookworm main" \
        > /etc/apt/sources.list.d/confluent-clients.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends --allow-downgrades \
        make g++ gcc python3 \
        "librdkafka1=2.10.1-1.cflt~deb12" \
        "librdkafka++1=2.10.1-1.cflt~deb12" \
        "librdkafka-dev=2.10.1-1.cflt~deb12" && \
    rm -rf /var/lib/apt/lists/*
ENV BUILD_LIBRDKAFKA=0

# `corepack enable` picks the pnpm version from `packageManager` in the
# root package.json. No `corepack prepare` — non-deterministic.
RUN corepack enable

# Manifests + lockfile first so the install layer caches across unrelated
# source edits. `patches/` is referenced from pnpm-lock.yaml.
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json tsconfig.json ./
COPY patches/ patches/

# pnpm reads every referenced workspace package.json BEFORE install to
# build the dep graph. Copy manifests separately from sources so source
# edits don't bust the install cache.
COPY services/agents/package.json services/agents/package.json
COPY services/agent-ingress/package.json services/agent-ingress/package.json
COPY services/agent-runner/package.json services/agent-runner/package.json
COPY services/agent-janitor/package.json services/agent-janitor/package.json
COPY services/agent-migrations/package.json services/agent-migrations/package.json
COPY services/agent-shared/package.json services/agent-shared/package.json
COPY services/agent-tools/package.json services/agent-tools/package.json

# Full install (no --ignore-scripts) so node-rdkafka's gyp build runs
# against the librdkafka we installed above. Without this, KafkaLogSink
# would fail at `await import('node-rdkafka')` the first time anyone
# sets `KAFKA_BROKERS` — the image would look healthy but silently lose
# the prod Kafka path. `pg-native` is marked external in the esbuild
# config (none of the services call `pg.native`).
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile \
        --filter '@posthog/agents-image...' \
        --filter '@posthog/agent-ingress...' \
        --filter '@posthog/agent-runner...' \
        --filter '@posthog/agent-janitor...' \
        --filter '@posthog/agent-migrations...'

# Sources. Ordered shared-first so a change to (say) ingress doesn't
# invalidate the shared layer.
COPY services/agent-shared/ services/agent-shared/
COPY services/agent-tools/ services/agent-tools/
COPY services/agent-migrations/ services/agent-migrations/
COPY services/agent-ingress/ services/agent-ingress/
COPY services/agent-runner/ services/agent-runner/
COPY services/agent-janitor/ services/agent-janitor/
COPY services/agents/ services/agents/

WORKDIR /code/services/agents
RUN pnpm run build

#
# Runtime stage — slim image with bundles + migration SQL + the one
# native dep (node-rdkafka) we left external in esbuild.
#
FROM ${NODE_IMAGE}
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]

# Runtime librdkafka 2.10.1 (matches Dockerfile.node). Only the runtime
# libs, not the dev headers — keeps the image lean.
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget gnupg ca-certificates && \
    mkdir -p /etc/apt/keyrings && \
    wget -qO - https://packages.confluent.io/clients/deb/archive.key | \
        gpg --dearmor -o /etc/apt/keyrings/confluent-clients.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/confluent-clients.gpg] https://packages.confluent.io/clients/deb/ bookworm main" \
        > /etc/apt/sources.list.d/confluent-clients.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends --allow-downgrades \
        "librdkafka1=2.10.1-1.cflt~deb12" \
        "librdkafka++1=2.10.1-1.cflt~deb12" && \
    apt-get purge -y wget gnupg && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Commit hash for incident triage. Matches the convention in
# Dockerfile.node and services/mcp/Dockerfile.
ARG COMMIT_HASH
RUN echo "${COMMIT_HASH:-unknown}" > /code/commit.txt

# Keep the bundles inside `services/agents/` so Node's module resolution
# walks up to `services/agents/node_modules/` (where pnpm symlinks
# `node-rdkafka` because @posthog/agents-image declares it as a direct
# dep) and then to `/code/node_modules/.pnpm/...` (the actual content).
# `dirname(import.meta.url)` for the migrate bundle becomes
# `/code/services/agents/dist`, so `../migrations` resolves to
# `/code/services/agents/migrations` — that's where the SQL goes.
COPY --from=build --chown=node:node /code/services/agents/dist/ ./services/agents/dist/
COPY --from=build --chown=node:node /code/services/agent-migrations/migrations/ ./services/agents/migrations/

# Workspace symlinks for the bundle's externals. `services/agents/node_modules/`
# is a pnpm symlink farm; the underlying `.pnpm` store at the workspace
# root holds the real content (notably node-rdkafka's compiled .node
# addon). Both have to be carried over.
COPY --from=build --chown=node:node /code/services/agents/node_modules/ /code/services/agents/node_modules/
COPY --from=build --chown=node:node /code/node_modules/.pnpm/ /code/node_modules/.pnpm/

ENV NODE_ENV=production

# 8080 = ingress default, 8082 = janitor default. The runner and the
# migration Job don't listen on a port. EXPOSE is documentation only —
# k8s ignores it; the deploy manifest sets containerPort per release.
EXPOSE 8080 8082

USER node

# No default CMD on purpose — every deploy must declare which entrypoint
# it runs. Locally: `docker run posthog-agents node dist/runner.mjs`.
