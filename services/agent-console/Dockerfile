# PostHog agent console — Next.js 15 standalone runtime.
#
# Build context is the repo root so pnpm + transpilePackages can resolve
# @posthog/agent-chat and @posthog/quill from the workspace:
#
#   docker build -f services/agent-console/Dockerfile -t posthog-agent-console .
#
# Reference: services/mcp/Dockerfile + next.js standalone output docs.

# `next` 15 supports Node 20+. The console's package.json declares
# `engines.node: ">=20"`, but the rest of the monorepo runs Node 24, so
# we share that pin for consistency.
ARG NODE_VERSION=24.13.0
ARG NODE_IMAGE=node:${NODE_VERSION}-bookworm-slim

#
# Build stage — workspace install + `next build`.
#
FROM ${NODE_IMAGE} AS build
WORKDIR /code

RUN corepack enable

# Manifests + lockfile first for cacheable installs.
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json tsconfig.json ./
COPY patches/ patches/

# Every workspace package referenced (directly or transitively) by the
# console needs its package.json available before install so pnpm can
# build the dep graph.
COPY services/agent-console/package.json services/agent-console/package.json
COPY packages/agent-chat/package.json packages/agent-chat/package.json
# Quill is a multi-package workspace itself; the simplest correct option
# is to copy every package.json in the tree before install.
COPY packages/quill/ packages/quill/

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile \
        --filter '@posthog/agent-console...'

# Sources for the console + the two workspace packages it transpiles.
COPY packages/agent-chat/ packages/agent-chat/
COPY services/agent-console/ services/agent-console/

# `@posthog/quill` ships `main: "./dist/index.cjs"` — it needs a build
# step before next can resolve the import (next's `transpilePackages`
# still goes through `main`/`exports` resolution).
#
# `@posthog/quill...` (trailing `...`) selects quill + every workspace
# package it depends on. agent-console doesn't depend on quill-charts
# and `pnpm --filter '@posthog/agent-console...' install` doesn't
# install charts' deps, so a glob like `@posthog/quill-*` would also
# pick up charts and fail with tsc-can't-resolve at build time. The
# `...` form excludes it naturally (quill itself doesn't depend on
# charts) and stays correct if new quill subpackages get added.
RUN pnpm --dir packages/quill -r --filter '@posthog/quill...' build

WORKDIR /code/services/agent-console
RUN pnpm run build

#
# Runtime stage — `.next/standalone` is a self-contained Node server
# with its own minimal node_modules tree (no pnpm at runtime).
#
FROM ${NODE_IMAGE}
WORKDIR /code

ARG COMMIT_HASH
RUN echo "${COMMIT_HASH:-unknown}" > /code/commit.txt

# `outputFileTracingRoot` in next.config.mjs is set to the monorepo root,
# so `.next/standalone/` reproduces the relative path
# `services/agent-console/server.js` plus the traced node_modules.
COPY --from=build --chown=node:node /code/services/agent-console/.next/standalone/ ./
COPY --from=build --chown=node:node /code/services/agent-console/.next/static/ ./services/agent-console/.next/static/
# No `public/` directory in the console source today. Add a
# `COPY ... public/ ...` line here if static assets are introduced.

ENV NODE_ENV=production \
    PORT=3040 \
    HOSTNAME=0.0.0.0

EXPOSE 3040

USER node

CMD ["node", "services/agent-console/server.js"]
