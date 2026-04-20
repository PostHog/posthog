# Agent CLI (`ph`)

Agent-first CLI for the PostHog API, designed for coding agents (Claude Code, Cursor, etc.) that interact via bash.
Uses the same codegen pipeline as the MCP server — same tools, same YAML configs, zero token overhead.

## Usage

```bash
# Discovery
posthog-cli api list                              # all tools, grouped by category
posthog-cli api list --category "Feature Flags"   # filter by category
posthog-cli api list --json                       # machine-readable output

# Schema exploration (brief by default, --full for description)
posthog-cli api schema feature-flag-get-all
posthog-cli api schema query-trends --full

# Execute
posthog-cli api feature-flags-list --json '{"limit": 5}'
posthog-cli api query-trends --json '{"series": [{"event": "$pageview"}]}'

# Dry run (validate + show request without executing)
posthog-cli api feature-flag-get-all --json '{}' --dry-run

# Field filtering
posthog-cli api feature-flags-list --json '{}' --fields 'name,key,active'
```

## Auth

Credentials are resolved in this order:

1. **`posthog-cli login`** — stored token from `~/.posthog/credentials.json` (injected by the Rust CLI wrapper)
2. **Env vars** — `POSTHOG_CLI_API_KEY`, `POSTHOG_CLI_PROJECT_ID`, `POSTHOG_CLI_HOST`
3. **Local dev auto-detection** — when running inside a PostHog repo clone, defaults to `localhost:8010` with the dev API key

## Architecture

```text
posthog-cli api <args>          ← Rust binary (cli/)
       │
       └─► node services/agent-cli/dist/index.js <args>
                    │
                    ├── manifest.ts     → loads cli-manifest.json
                    ├── config.ts       → resolves auth
                    ├── executor.ts     → builds + sends HTTP requests
                    └── schema-explorer.ts → brief/full schema output
```

The CLI manifest (`services/mcp/schema/cli-manifest.json`) is generated alongside MCP tools
by `hogli build:openapi`. It contains HTTP method, path, param locations, descriptions,
and pre-resolved query schemas — no runtime OpenAPI loading needed.

## Development

```bash
# Run directly (monorepo, uses tsx)
pnpm --filter=@posthog/cli-agent dev list

# Via Rust CLI (auto-detects monorepo)
cargo run --manifest-path cli/Cargo.toml -- api list

# Regenerate manifest after changing serializers/YAML
hogli build:openapi
```
