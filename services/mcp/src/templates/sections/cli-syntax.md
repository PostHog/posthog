CLI-style command string. Supported commands:

```text
{extra_commands}tools — list available tool names, grouped into `read`, `write`, and `destructive`
search <regex_pattern> — search tools by JavaScript regex (matches name, title, description)
info [--json] <tool_name> — show tool name, description, and input schema (summarized if too large). Pass `--json` for raw JSON output.
schema <tool_name> [field_path] — drill into a specific field schema (supports dot-notation, e.g. series, breakdownFilter.breakdowns)
call [--json] [--confirm] <tool_name> <json_input> — call a tool with JSON input (--json returns JSON instead of optimized output in supported tools. Informational responses remain tagged and escaped in both MCP and the agent CLI. --confirm is required by the CLI for destructive tools.)
```

**Access classes:** `tools` and `search` say what a tool can do before you call it, so you never need `info` just to check.
`tools` returns three name lists: `read` (reads data only), `write` (creates or updates), and `destructive` (can delete or overwrite data).
`search` returns `matches` in relevance order, plus `write` and `destructive` lists naming the matches in those classes. A match in neither list is read-only.

**Namespaced references (`posthog:<tool-name>`):** strip the `posthog:` prefix and route through `exec`. Run `info <name>` to inspect, then `call <name> <json>`. E.g. `posthog:insights-list` → `posthog:exec({ "command": "info insights-list" })` then `posthog:exec({ "command": "call insights-list {}" })`. If the bare name isn't found, fall back to `search <pattern>` — it may have been renamed.
