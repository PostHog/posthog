# @posthog/mcp-exec

A scrappy prototype MCP server that exposes the PostHog API to agents as **three meta-tools** instead of one tool per endpoint:

- `search` — find operations and types in the SDK by natural-language query
- `read` — fetch the TypeScript signature of an operation or type, with one level of transitive type refs inlined
- `exec` — execute a TypeScript snippet against a pre-bound `client`

The point is to test whether this shape uses fewer context tokens and is more usable for coding agents than the standard "one MCP tool per OpenAPI operation" pattern (the existing `services/mcp` ships ~200 tool schemas).

## Setup

```bash
# 1. Make sure the OpenAPI spec is up to date — the codegen reads from
#    posthog/frontend/tmp/openapi.json
hogli build:openapi

# 2. Make sure services/mcp/src/api/generated.ts is up to date — we re-export
#    its Schemas namespace verbatim
cd services/mcp && pnpm run generate-orval-schemas && pnpm run generate-mcp-types

# 3. Generate the client + sdk.d.ts + search-index.json
cd ../mcp/exec && pnpm install && pnpm run generate
```

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
