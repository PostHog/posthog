CLI-style command string. Supported commands:

```text
tools — list available tool names
search <regex_pattern> — search tools by JavaScript regex (matches name, title, description)
info [--json] <tool_name> — show tool name, description, and input schema (summarized if too large). Pass `--json` for raw JSON output.
schema <tool_name> [field_path] — drill into a specific field schema (supports dot-notation, e.g. series, breakdownFilter.breakdowns)
call [--json] <tool_name> <json_input> — call a tool with JSON arguments inline in the command string (omit for tools that take no arguments). Pass `--json` for the inner tool's raw JSON result.
```

**Namespaced references (`posthog:<tool-name>`):** strip the `posthog:` prefix and route through `exec`. Run `info <name>` to inspect, then `call <name> <json>`. E.g. `posthog:insights-list` → `posthog:exec({ "command": "info insights-list" })` then `posthog:exec({ "command": "call insights-list {}" })`. If the bare name isn't found, fall back to `search <pattern>` — it may have been renamed.
