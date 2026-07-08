# PostHog agent-proxy server (Hono / Node.js).
#
# Standalone SSE streaming and NDJSON ingest service — a pure streaming plane
# backed by Redis, with no Postgres, Temporal, or Celery dependencies.
#
# Build from repo root (build context must be the workspace root so pnpm can
# resolve cross-package deps):
#
#   docker build -f services/agent-proxy/Dockerfile -t posthog-agent-proxy .

# Pin the same Node version as the rest of the monorepo (.nvmrc).
# The digest wins over the tag — update both together when bumping NODE_VERSION.
ARG NODE_VERSION=24.13.0
ARG NODE_IMAGE=node:${NODE_VERSION}-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f

#
# Build stage — install workspace deps, bundle the Hono entry into a single .mjs.
# Everything (including ioredis) is bundled so the runtime stage ships with no
# node_modules at all.
#
FROM ${NODE_IMAGE} AS build
WORKDIR /code

# `corepack enable` reads the `packageManager` field in package.json to pick the
# pnpm version — no `corepack prepare pnpm@latest` (non-deterministic).
RUN corepack enable

# Copy lockfile + workspace manifests first so the install layer caches across
# unrelated source changes. `patches/` is needed because pnpm-lock.yaml may
# reference workspace-level patch files.
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json tsconfig.json ./
COPY patches/ patches/

# pnpm needs every referenced workspace package's `package.json` BEFORE install
# so it can build the dependency graph. Copy manifests only (cache-friendly),
# then source after.
COPY services/agent-proxy/package.json services/agent-proxy/package.json

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter @posthog/agent-proxy...

COPY services/agent-proxy/ services/agent-proxy/
WORKDIR /code/services/agent-proxy
RUN pnpm exec tsx scripts/build-agent-proxy.ts

#
# Runtime stage — minimal slim image with just the self-contained bundle.
#
FROM ${NODE_IMAGE}
WORKDIR /code

# Commit hash burned in for incident triage.
ARG COMMIT_HASH
RUN echo "${COMMIT_HASH:-unknown}" > /code/commit.txt

# Bundle is fully self-contained — ioredis and every other dep is inlined.
COPY --from=build --chown=node:node /code/services/agent-proxy/dist/agent-proxy-server.mjs ./agent-proxy-server.mjs
COPY --from=build --chown=node:node /code/services/agent-proxy/dist/agent-proxy-server.mjs.map ./agent-proxy-server.mjs.map

ENV NODE_ENV=production \
    PORT=8003

EXPOSE 8003

USER node

CMD ["node", "agent-proxy-server.mjs"]
