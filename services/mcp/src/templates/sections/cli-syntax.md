CLI-style command string. Supported commands:

```text
{extra_commands}tools — list available tool names
search <regex_pattern> — search tools by JavaScript regex (matches name, title, description)
info [--json] <tool_name> — show tool name, description, and input schema (summarized if too large). Pass `--json` for raw JSON output.
schema <tool_name> [field_path] — drill into a specific field schema (supports dot-notation, e.g. series, breakdownFilter.breakdowns)
call [--json] [--confirm] <tool_name> <json_input> — call a tool with JSON input (--json returns JSON instead of optimized output in supported tools. Informational responses remain tagged and escaped in both MCP and the agent CLI. --confirm is required by the CLI for destructive tools.)
```

**Batching.** You can stack up to 10 read-only commands (`tools`, `search`, `info`, `schema`) in one request, one per line. The reply repeats each command and puts its result underneath. `call` and `learn` do not batch — send each of those as its own `exec` call. You can issue them in parallel.

**Namespaced references (`posthog:<tool-name>`):** strip the `posthog:` prefix and route through `exec`. Run `info <name>` to inspect, then `call <name> <json>`. E.g. `posthog:insights-list` → `posthog:exec({ "command": "info insights-list" })` then `posthog:exec({ "command": "call insights-list {}" })`. If the bare name isn't found, fall back to `search <pattern>` — it may have been renamed.
