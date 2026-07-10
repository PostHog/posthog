CLI-style command string. Supported commands:

```text
tools — list available tool names
search <regex_pattern> — search tools by JavaScript regex (matches name, title, description)
info [--json] <tool_name> — show tool name, description, and input schema (summarized if too large). Pass `--json` for raw JSON output.
schema <tool_name> [field_path ...] — drill into one or more field schemas in a single call (supports dot-notation and `*` globs, e.g. `series breakdownFilter.breakdowns`, `series.*`)
call [--json] [--confirm] <tool_name> <json_input> — call a tool with JSON input (--json returns raw JSON instead of optimized output in supported tools. Use raw JSON for scripts. --confirm is required by the CLI for destructive tools.)
```

**Namespaced references (`posthog:<tool-name>`):** strip the `posthog:` prefix and route through `exec`. Run `info <name>` to inspect, then `call <name> <json>`. E.g. `posthog:insights-list` → `posthog:exec({ "command": "info insights-list" })` then `posthog:exec({ "command": "call insights-list {}" })`. If the bare name isn't found, fall back to `search <pattern>` — it may have been renamed.
