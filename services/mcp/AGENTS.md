# MCP development guide

## Commands

Run these commands from the repository root:

- Run `pnpm --filter=@posthog/mcp run typecheck` after changing TypeScript or TSX files. It checks types without emitting files.
- Run `pnpm --filter=@posthog/mcp run format` before committing JavaScript, TypeScript, JSON, YAML, CSS, or SCSS changes. It applies Oxlint fixes and Oxfmt formatting, so it may rewrite files.
