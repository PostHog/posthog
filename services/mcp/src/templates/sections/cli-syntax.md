CLI-style command string. Supported commands:

```text
tools — list available tool names
search <regex_pattern> — search tools by JavaScript regex (matches name, title, description)
info <tool_name> — show tool name, description, and input schema (summarized if too large)
schema <tool_name> [field_path] — drill into a specific field schema (supports dot-notation, e.g. series, breakdownFilter.breakdowns)
call <tool_name> — call a tool. Pass arguments via the `input` parameter (JSON object).
```

**Namespaced references (`posthog:<tool-name>`):** strip the `posthog:` prefix and route through `exec`. Run `info <name>` to inspect, then `call <name>` with `input`. E.g. `posthog:insights-list` → `posthog:exec({ "command": "info insights-list" })` then `posthog:exec({ "command": "call insights-list", "input": {} })`. If the bare name isn't found, fall back to `search <pattern>` — it may have been renamed.
