# MCP development guide

## Commands

Run these commands from `services/mcp`:

- Run `pnpm typecheck` after changing TypeScript or TSX files. It checks types without emitting files.
- Run `pnpm format` before committing JavaScript, TypeScript, JSON, YAML, CSS, or SCSS changes. It applies Oxlint fixes and Oxfmt formatting, so it may rewrite files.
