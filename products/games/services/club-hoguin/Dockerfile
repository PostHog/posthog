# Club Hoguin server (plain Node.js, no build step).
#
# One process that serves the web client and keeps the town in memory.
# Node runs the TypeScript in src/ as it is, so the image needs no compiler.
#
# Build from the repo root, because pnpm needs the workspace lockfile:
#
#   docker build -f products/games/services/club-hoguin/Dockerfile -t posthog-club-hoguin .

# Pin the same Node version as the rest of the monorepo (.nvmrc).
# The digest wins over the tag. Update both together when you change NODE_VERSION.
ARG NODE_VERSION=24.13.0
ARG NODE_IMAGE=node:${NODE_VERSION}-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f

#
# Build stage: install the two runtime packages from the lockfile, then keep only the files the server reads.
#
FROM ${NODE_IMAGE} AS build
WORKDIR /code

# `corepack enable` reads the `packageManager` field in package.json to pick the pnpm version.
RUN corepack enable

# pnpm-lock.yaml can name the patch files in patches/, so they come with the manifests.
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY patches/ patches/
COPY products/games/services/club-hoguin/package.json products/games/services/club-hoguin/package.json

# The root package has install scripts for the full dev setup. This image does not need them.
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --prod --ignore-scripts --filter @posthog/club-hoguin...

# The server reads the sprite sheet from @posthog/hedgehog-mode and serves two files from three.
# pnpm links packages into a shared store, so the files are copied out by name.
WORKDIR /code/products/games/services/club-hoguin
RUN mkdir -p /out/node_modules/@posthog/hedgehog-mode /out/node_modules/three/build \
    && cp node_modules/@posthog/hedgehog-mode/package.json /out/node_modules/@posthog/hedgehog-mode/ \
    && cp -R node_modules/@posthog/hedgehog-mode/assets /out/node_modules/@posthog/hedgehog-mode/ \
    && cp node_modules/three/package.json /out/node_modules/three/ \
    && cp node_modules/three/build/three.module.js node_modules/three/build/three.module.min.js \
        node_modules/three/build/three.core.js node_modules/three/build/three.core.min.js /out/node_modules/three/build/

#
# Runtime stage: Node, the server source, the web client, and the files from the build stage.
#
FROM ${NODE_IMAGE}
WORKDIR /code

# The commit hash is kept in the image for incident triage.
ARG COMMIT_HASH
RUN echo "${COMMIT_HASH:-unknown}" > /code/commit.txt

COPY --from=build --chown=node:node /out/node_modules ./node_modules
COPY --chown=node:node products/games/services/club-hoguin/package.json ./package.json
COPY --chown=node:node products/games/services/club-hoguin/src ./src
COPY --chown=node:node products/games/services/club-hoguin/web ./web

ENV NODE_ENV=production \
    PORT=8642

EXPOSE 8642

USER node

CMD ["node", "src/main.ts"]
