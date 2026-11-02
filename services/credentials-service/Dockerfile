# PostHog credentials-service (Hono / Node.js). Serves the platform integration
# credentials PostHog itself owns over HTTP; see README.md.
#
# Build from repo root (the build context must be the workspace root so pnpm can
# resolve cross-package deps):
#
#   docker build -f services/credentials-service/Dockerfile -t posthog-credentials-service .

# Pin the same Node version as the rest of the monorepo (.nvmrc).
# The digest wins over the tag; update both together when bumping NODE_VERSION.
ARG NODE_VERSION=24.22.1
ARG NODE_IMAGE=node:${NODE_VERSION}-bookworm-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205

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
COPY services/credentials-service/package.json services/credentials-service/package.json

# --ignore-scripts: nothing in this tree needs an install-time script, and for a
# service holding every platform integration credential that is the supply-chain
# path worth closing.
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --ignore-scripts --filter @posthog/credentials-service...

COPY services/credentials-service/ services/credentials-service/
WORKDIR /code/services/credentials-service
RUN pnpm build

#
# Runtime stage: the slim image plus the self-contained bundle.
#
FROM ${NODE_IMAGE}
WORKDIR /code

# Commit hash burned in for incident triage.
ARG COMMIT_HASH
RUN echo "${COMMIT_HASH:-unknown}" > /code/commit.txt

COPY --from=build --chown=node:node /code/services/credentials-service/dist/credentials-service.mjs ./credentials-service.mjs
COPY --from=build --chown=node:node /code/services/credentials-service/dist/credentials-service.mjs.map ./credentials-service.mjs.map

ENV NODE_ENV=production \
    PORT=8004

EXPOSE 8004

USER node

CMD ["node", "credentials-service.mjs"]
