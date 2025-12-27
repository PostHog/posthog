#
# MCP Server Dockerfile
# Build from repo root: docker build -f services/mcp/typescript/Dockerfile -t mcp-server .
#

FROM node:22-alpine AS base

RUN corepack enable && corepack prepare pnpm@10.23.0 --activate

WORKDIR /code

# Install dependencies
FROM base AS deps

COPY pnpm-lock.yaml pnpm-workspace.yaml package.json turbo.json tsconfig.json ./
COPY patches/ patches/
COPY services/mcp/typescript/package.json services/mcp/typescript/

RUN --mount=type=cache,id=pnpm-mcp,target=/tmp/pnpm-store \
    pnpm --filter=@posthog/agent-toolkit... install --frozen-lockfile --store-dir /tmp/pnpm-store

# Build
FROM base AS builder

COPY --from=deps /code/node_modules ./node_modules
COPY --from=deps /code/services/mcp/typescript/node_modules ./services/mcp/typescript/node_modules
COPY services/mcp/typescript/ services/mcp/typescript/
COPY services/mcp/schema/ services/mcp/schema/

WORKDIR /code/services/mcp/typescript
RUN pnpm run build:server

# Production
FROM node:22-alpine AS runner

ENV NODE_ENV=production
ENV PORT=8080

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 mcp

WORKDIR /app

COPY --from=deps /code/services/mcp/typescript/node_modules ./node_modules
COPY --from=builder /code/services/mcp/typescript/dist/server ./dist/server
COPY --from=builder /code/services/mcp/typescript/package.json ./

USER mcp

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

CMD ["node", "dist/server/index.js"]
