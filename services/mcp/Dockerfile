# PostHog MCP server (Hono / Node.js).
#
# Production runtime image. Build context is the repo root so we can install
# dependencies through the pnpm workspace.
#
#   docker build -f services/mcp/Dockerfile -t posthog-mcp .
#
# The legacy `Dockerfile.proxy` in this directory is for the `mcp-remote` CLI
# proxy distribution, not the server — different artifact, don't confuse them.

# Pin the same Node version as the rest of the monorepo (.nvmrc).
ARG NODE_VERSION=24.13.0
ARG NODE_IMAGE=node:${NODE_VERSION}-bookworm-slim

#
# Build stage — install workspace deps, bundle the Hono entry into a single .mjs.
# Everything (including ioredis) is bundled, so the runtime stage doesn't need
# `node_modules` at all.
#
FROM ${NODE_IMAGE} AS build
WORKDIR /code

# `corepack enable` reads the `packageManager` field in package.json to pick the
# pnpm version — no `corepack prepare pnpm@latest` (non-deterministic).
RUN corepack enable

# Copy lockfile + workspace manifests first so the install layer caches across
# unrelated source changes. `patches/` is required because pnpm-lock.yaml
# references workspace-level patch files (e.g. `heatmap.js@2.0.5.patch`).
# Root `tsconfig.json` is needed because product tsconfigs (`products/*/tsconfig.json`)
# extend it via relative path; vite reads it during the UI apps build.
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json tsconfig.json ./
COPY patches/ patches/

# pnpm needs every referenced workspace package's `package.json` BEFORE install
# so it can build the dependency graph and link transitive workspace deps. We
# do this in two passes: manifests first (cache-friendly install layer), then
# source after, so source edits don't bust the install cache.
COPY services/mcp/package.json services/mcp/package.json
COPY common/mosaic/package.json common/mosaic/package.json
COPY tools/openapi-codegen/package.json tools/openapi-codegen/package.json

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter @posthog/mcp...

COPY services/mcp/ services/mcp/
COPY common/mosaic/ common/mosaic/
COPY tools/openapi-codegen/ tools/openapi-codegen/
# `scripts/build-ui-apps.ts` imports React components from `products/<x>/mcp/apps/`
# (the generator scans `products/*/mcp/tools.yaml` and synthesizes entry points),
# so the whole `products/` tree needs to be in the build context.
COPY products/ products/
WORKDIR /code/services/mcp
# Build the bundled Hono entry and the MCP UI apps. The latter writes per-app
# bundles (main.js, styles.css) into `public/ui-apps/<app>/` for the runtime
# stage to serve via the static-assets route in `src/hono/app.ts`.
RUN pnpm exec tsx scripts/build-hono.ts && pnpm run build:ui-apps

#
# Runtime stage — minimal slim image with just the bundle.
#
FROM ${NODE_IMAGE}
WORKDIR /code

# Commit hash burned in for incident triage; matches the convention in
# Dockerfile.node.
ARG COMMIT_HASH
RUN echo "${COMMIT_HASH:-unknown}" > /code/commit.txt

# Bundle is fully self-contained — ioredis and everything else is inlined.
COPY --from=build --chown=node:node /code/services/mcp/dist/hono-server.mjs ./hono-server.mjs
COPY --from=build --chown=node:node /code/services/mcp/dist/hono-server.mjs.map ./hono-server.mjs.map
# UI app static assets — served at `/ui-apps/<app>/...` by `serveStatic` in app.ts.
COPY --from=build --chown=node:node /code/services/mcp/public/ ./public/

ENV NODE_ENV=production \
    PORT=3001

EXPOSE 3001

# Liveness/readiness are handled by the orchestrator (k8s probes hit /healthz
# and /readyz). No HEALTHCHECK directive — keeps the image free of curl etc.

USER node

CMD ["node", "hono-server.mjs"]
