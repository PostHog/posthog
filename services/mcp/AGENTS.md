# MCP development guide

## Commands

Run these commands from the repository root:

- Run `pnpm --filter=@posthog/mcp run typecheck` after changing TypeScript or TSX files. It checks types without emitting files.
- Run `pnpm --filter=@posthog/mcp run format` to apply Oxfmt only. Use `lint` and `format:check` for verification; neither command rewrites files.
- Run `pnpm --filter=@posthog/mcp run lint:fix` to apply safe Oxlint fixes. It does not apply suggestion fixes that may change behavior.
- Run `pnpm --filter=@posthog/mcp run fix` before committing JavaScript, TypeScript, JSON, YAML, CSS, or SCSS changes. It applies safe Oxlint fixes, always runs Oxfmt, and fails if either tool fails.

## MCP analytics

- Before you add or change MCP server analytics, read the [custom server integration guide](https://posthog.com/docs/mcp-analytics/custom-servers) and the [event and property reference](https://posthog.com/docs/mcp-analytics/events). Use `@posthog/mcp-analytics` for each signal that it supports. Do not duplicate SDK behavior in custom capture code.
- Event and property names that start with `$mcp_` are reserved for MCP Analytics SDKs. Do not add, rename, or reuse these names in server code.
- If the SDK does not support a required signal, check the design with `@mcp-analytics-folks` or `@team-mcp-analytics` before you implement it.
- Tag `@mcp-analytics-folks` or `@team-mcp-analytics` in each PR that changes MCP analytics instrumentation, and request their review.
