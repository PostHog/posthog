# PostHog integration-service (Hono / Node.js). Serves the platform integration
# credentials PostHog itself owns over HTTP; see README.md.
#
# Build from repo root (the build context must be the workspace root so pnpm can
# resolve cross-package deps):
#
#   docker build -f services/integration-service/Dockerfile -t posthog-integration-service .

# Pin the same Node version as the rest of the monorepo (.nvmrc).
# The digest wins over the tag; update both together when bumping NODE_VERSION.
ARG NODE_VERSION=24.13.0
ARG NODE_IMAGE=node:${NODE_VERSION}-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f

#
# Build stage: install workspace deps, bundle the entry into a single self-contained
# .mjs, so the runtime stage ships with no node_modules at all.
#
FROM ${NODE_IMAGE} AS build
WORKDIR /code

# `corepack enable` reads the `packageManager` field in package.json to pick the
# pnpm version; `corepack prepare pnpm@latest` would be non-deterministic.
RUN corepack enable

# Copy lockfile + workspace manifests first so the install layer caches across
# unrelated source changes. `patches/` is needed because pnpm-lock.yaml may
# reference workspace-level patch files.
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json tsconfig.json ./
COPY patches/ patches/

# pnpm needs the workspace package's manifest before install to build the
# dependency graph; copying only the manifest keeps the layer cache-friendly.
COPY services/integration-service/package.json services/integration-service/package.json

# --ignore-scripts: nothing in this tree needs an install-time script, and for a
# service holding every platform integration credential that is the supply-chain
# path worth closing.
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --ignore-scripts --filter @posthog/integration-service...

COPY services/integration-service/ services/integration-service/
WORKDIR /code/services/integration-service
RUN pnpm build

#
# Runtime stage: the slim image plus the self-contained bundle.
#
FROM ${NODE_IMAGE}
WORKDIR /code

# Commit hash burned in for incident triage.
ARG COMMIT_HASH
RUN echo "${COMMIT_HASH:-unknown}" > /code/commit.txt

COPY --from=build --chown=node:node /code/services/integration-service/dist/integration-service.mjs ./integration-service.mjs
COPY --from=build --chown=node:node /code/services/integration-service/dist/integration-service.mjs.map ./integration-service.mjs.map

ENV NODE_ENV=production \
    PORT=8004

EXPOSE 8004

USER node

CMD ["node", "integration-service.mjs"]
