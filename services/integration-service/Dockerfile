# PostHog integration-service (Hono / Node.js).
#
# Serves platform integration credentials (the OAuth app client ids/secrets and API
# keys PostHog itself owns) over HTTP, so they stop being injected as env vars into
# every pod that might need one. Backed by AWS Secrets Manager, cached in memory and
# in Redis under a KMS-wrapped data key.
#
# Build from repo root (build context must be the workspace root so pnpm can
# resolve cross-package deps):
#
#   docker build -f services/integration-service/Dockerfile -t posthog-integration-service .

# Pin the same Node version as the rest of the monorepo (.nvmrc).
# The digest wins over the tag — update both together when bumping NODE_VERSION.
ARG NODE_VERSION=24.13.0
ARG NODE_IMAGE=node:${NODE_VERSION}-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f

#
# Build stage — install workspace deps, bundle the entry into a single .mjs.
# Everything is bundled so the runtime stage ships with no node_modules at all.
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

# pnpm needs the referenced workspace package's `package.json` BEFORE install so it
# can build the dependency graph. Copy the manifest only (cache-friendly), then
# source after.
COPY services/integration-service/package.json services/integration-service/package.json

# --ignore-scripts: no dependency runs code at install time. This service holds every
# platform integration credential, so an install-time script in a transitive package
# is exactly the supply-chain path worth closing. None of the deps here need one.
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --ignore-scripts --filter @posthog/integration-service...

COPY services/integration-service/ services/integration-service/
WORKDIR /code/services/integration-service
RUN pnpm exec tsx scripts/build-integration-service.ts

# Fail the image build, not just CI, if the bundle reached outside this package or
# grew a dependency nobody listed.
RUN pnpm exec tsx scripts/check-import-boundary.ts && pnpm exec tsx scripts/check-deps-allowlist.ts

#
# Runtime stage — minimal slim image with just the self-contained bundle.
#
FROM ${NODE_IMAGE}
WORKDIR /code

# Commit hash burned in for incident triage.
ARG COMMIT_HASH
RUN echo "${COMMIT_HASH:-unknown}" > /code/commit.txt

# Bundle is fully self-contained — every dep is inlined.
COPY --from=build --chown=node:node /code/services/integration-service/dist/integration-service.mjs ./integration-service.mjs
COPY --from=build --chown=node:node /code/services/integration-service/dist/integration-service.mjs.map ./integration-service.mjs.map

ENV NODE_ENV=production \
    PORT=8004

EXPOSE 8004

USER node

CMD ["node", "integration-service.mjs"]
