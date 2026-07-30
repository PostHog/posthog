# MCP development guide

## Commands

Run these commands from the repository root:

- Run `pnpm --filter=@posthog/mcp run typecheck` after changing TypeScript or TSX files. It checks types without emitting files.
- Run `pnpm --filter=@posthog/mcp run format` to apply Oxfmt only. Use `lint` and `format:check` for verification; neither command rewrites files.
- Run `pnpm --filter=@posthog/mcp run lint:fix` to apply safe Oxlint fixes. It does not apply suggestion fixes that may change behavior.
- Run `pnpm --filter=@posthog/mcp run fix` before committing JavaScript, TypeScript, JSON, YAML, CSS, or SCSS changes. It applies safe Oxlint fixes, always runs Oxfmt, and fails if either tool fails.
