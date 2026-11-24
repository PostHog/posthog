# syntax=docker/dockerfile:1.7.1@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
# The digest pins the frontend image; the tag alone is mutable. Update both together.
# PostHog credentials-service (Hono / Node.js). Serves the platform integration
# credentials PostHog itself owns over HTTP; see README.md.
#
# Build from repo root (the build context must be the workspace root so pnpm can
# resolve cross-package deps):
#
#   docker build -f services/credentials-service/Dockerfile -t posthog-credentials-service .

# Pin the same Node version as the rest of the monorepo (.nvmrc).
# The digest wins over the tag; update both together when bumping NODE_VERSION.
ARG NODE_VERSION=26.13.1
ARG NODE_IMAGE=node:${NODE_VERSION}-bookworm-slim@sha256:5df79989ed685e09f0a98019db4cebfb22fb9df1a53c0161664a011f7ff6b0f1

#
# Build stage: install workspace deps, bundle the entry into a single self-contained
# .mjs, so the runtime stage ships with no node_modules at all.
#
FROM ${NODE_IMAGE} AS build
WORKDIR /code

# `corepack enable` reads the `packageManager` field in package.json to pick the
# pnpm version; `corepack prepare pnpm@latest` would be non-deterministic.
RUN npm install -g corepack@0.36.0 && corepack enable

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

# AWS RDS global CA bundle, so the Aurora TLS connection verifies. Node does not trust it by default.
# NODE_EXTRA_CA_CERTS adds it to the default CAs, so the public CAs stay trusted.
# To update: download the bundle, recompute the hash with sha256sum, and replace the value below.
#   curl -fsS "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem" | sha256sum
ARG RDS_CA_BUNDLE_SHA256=90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b
ADD --checksum=sha256:${RDS_CA_BUNDLE_SHA256} --chmod=0644 \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /etc/ssl/certs/rds-global-bundle.pem
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/rds-global-bundle.pem

# Commit hash burned in for incident triage.
ARG COMMIT_HASH
RUN echo "${COMMIT_HASH:-unknown}" > /code/commit.txt

COPY --from=build --chown=node:node /code/services/credentials-service/dist/credentials-service.mjs ./credentials-service.mjs
COPY --from=build --chown=node:node /code/services/credentials-service/dist/credentials-service.mjs.map ./credentials-service.mjs.map
# The migration Job runs `node credentials-service-migrate.mjs` from this image. It reads
# ./migrations relative to the working directory.
COPY --from=build --chown=node:node /code/services/credentials-service/dist/credentials-service-migrate.mjs ./credentials-service-migrate.mjs
COPY --from=build --chown=node:node /code/services/credentials-service/dist/credentials-service-migrate.mjs.map ./credentials-service-migrate.mjs.map
COPY --from=build --chown=node:node /code/services/credentials-service/migrations ./migrations

ENV NODE_ENV=production \
    PORT=8004

EXPOSE 8004

USER node

CMD ["node", "credentials-service.mjs"]
