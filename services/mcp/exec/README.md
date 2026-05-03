# @posthog/mcp-exec

A scrappy prototype MCP server that exposes the PostHog API to agents as **three meta-tools** instead of one tool per endpoint:

- `search` — find operations and types in the SDK by natural-language query
- `read` — fetch the TypeScript signature of an operation or type, with one level of transitive type refs inlined
- `exec` — execute a TypeScript snippet against a pre-bound `client`

The point is to test whether this shape uses fewer context tokens and is more usable for coding agents than the standard "one MCP tool per OpenAPI operation" pattern (the existing `services/mcp` ships ~200 tool schemas).

## Setup

```bash
# 1. Make sure the OpenAPI spec + v2 codegen artifacts are up to date —
#    `services/mcp/exec` consumes:
#      - frontend/tmp/openapi.json                (source of truth for ops + types)
#      - services/mcp/src/api/generated.ts        (Schemas namespace, re-exported verbatim)
#      - services/mcp/schema/generated-tool-definitions.json (richer descriptions)
#      - services/mcp/definitions/*.yaml          (which ops are enabled + curated docs)
hogli build:openapi

# 2. Generate the client + sdk.d.ts + search-index.json
cd services/mcp/exec && pnpm install && pnpm run generate
```

The YAML files in `services/mcp/definitions/` gate which OpenAPI operations land in the
generated `Client`. Operations marked `enabled: false` are excluded; `enabled: true` ones
inherit any curated `title` / `description` from the YAML (overriding the raw OpenAPI text)
which then flows into JSDoc on `sdk.d.ts` and the `search` ranking signal.

In addition to OpenAPI operations, the generator emits:

- `client.executeSql({ query, truncate? })`, `client.readDataSchema({ query })`,
  `client.readDataWarehouseSchema()` — backed by `POST /api/environments/{id}/mcp_tools/{name}/`.
- `client.queryTrends`, `client.queryFunnel`, `client.queryRetention`, `client.queryStickiness`,
  `client.queryPaths`, `client.queryLifecycle`, `client.queryLlmTracesList`, `client.queryLlmTrace`,
  `client.queryTrendsActors` — backed by `POST /api/environments/{id}/query/`.

## Run (stdio)

```bash
POSTHOG_API_KEY=phx_... POSTHOG_BASE_URL=https://us.posthog.com pnpm run dev
```

Wire into Claude Code via `~/.claude.json`:

```json
{
  "mcpServers": {
    "posthog-exec": {
      "command": "pnpm",
      "args": ["--filter", "@posthog/mcp-exec", "start"],
      "env": {
        "POSTHOG_API_KEY": "phx_...",
        "POSTHOG_BASE_URL": "https://us.posthog.com"
      }
    }
  }
}
```

## Architecture

See `/Users/georgiy/.claude/plans/planner-brief-scrappy-generic-music.md` for the full plan.

This prototype is **stateless** (no shared variables across `exec` calls), runs in-process with **no sandbox** (snippets `eval` against the SDK client — local dev only, do not expose), and has **no typecheck step** (snippets fail at runtime if wrong, agent retries).
