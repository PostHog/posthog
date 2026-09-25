# MCP development guide

## Commands

Run these commands from the repository root:

- Run `pnpm --filter=@posthog/mcp run typecheck` after changing TypeScript or TSX files. It checks types without emitting files.
- Run `pnpm --filter=@posthog/mcp run format` to apply Oxfmt only. Use `lint` and `format:check` for verification; neither command rewrites files.
- Run `pnpm --filter=@posthog/mcp run lint:fix` to apply safe Oxlint fixes. It does not apply suggestion fixes that may change behavior.
- Run `pnpm --filter=@posthog/mcp run fix` before committing JavaScript, TypeScript, JSON, YAML, CSS, or SCSS changes. It applies safe Oxlint fixes, always runs Oxfmt, and fails if either tool fails.

## MCP Analytics

- Before adding or changing MCP Analytics instrumentation, read the [tracking and observability architecture](ARCHITECTURE.md#tracking-and-observability).
- Prefer `@posthog/mcp-analytics` for all MCP telemetry it supports. The SDK should own reusable MCP Analytics behavior. Server code should only provide the relevant typed data and PostHog-specific integration.
- Do not duplicate SDK behavior with custom event capture, property mapping, session handling, identity handling, or other parallel instrumentation.
- Event and property names beginning with `$mcp_` are owned by MCP Analytics SDKs. Do not invent, add, rename, reinterpret, or manually populate `$mcp_*` fields in server code unless the SDK explicitly exposes them for that purpose.
- Before introducing a new MCP Analytics event, property, or concept, check whether the SDK already supports it or whether it belongs in the SDK.
- If the SDK does not support a required signal or event, discuss the design with `@team-mcp-analytics` in Slack (`#team-mcp-analytics`) before implementing it. Prefer extending the SDK when the signal could be useful to other MCP Analytics customers. A custom event can be more appropriate for a product-specific or one-off need, but sync with the team first.
- Assign [`PostHog/mcp-analytics`](https://github.com/orgs/PostHog/teams/mcp-analytics) as a reviewer on every PR that changes MCP Analytics instrumentation.
- In the PR description, include a short **MCP Analytics** note that summarizes the changed analytics behavior, why it is needed, and whether it uses existing SDK support or requires something new.
