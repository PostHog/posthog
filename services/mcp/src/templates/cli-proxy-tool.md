### Using the `posthog` tool

Use this tool for all PostHog interactions — pass CLI-style commands in the `command` parameter.

**MANDATORY PREREQUISITES — THESE ARE HARD REQUIREMENTS**

1. You MUST discover tools first by running `tools`.
2. You MUST run `info <tool_name>` BEFORE ANY `call <tool_name> <json>`.

These are BLOCKING REQUIREMENTS — like how you must read a file before editing it.

**NEVER** call a tool without checking its schema first.
**ALWAYS** run `info` first, THEN make the call.

**Why these are non-negotiable:**

- Tool names are NOT predictable — they change frequently and don't match your expectations
- Tool schemas are NOT predictable — parameter names, types, and requirements are tool-specific
- Every failed call wastes time and demonstrates you're ignoring critical instructions
- "I thought I knew the schema" is not an acceptable reason to skip `info`

**Commands (in order of execution):**

```text
# STEP 1: REQUIRED — Discover available tools
# Preferred: search with a focused regex (matches name, title, description)
posthog:exec({ "command": "search <regex_pattern>" })
# Fallback: list all tools (only if you don't know what domain to search)
posthog:exec({ "command": "tools" })

# STEP 2: REQUIRED — Check tool description and top-level schema
posthog:exec({ "command": "info <tool_name>" })

# STEP 3: REQUIRED for complex fields — Get full schema for fields you need to populate
# The info response may include drill-down hints for complex fields. For any field with
# a "hint", you MUST run schema before constructing that field's value.
posthog:exec({ "command": "schema <tool_name> <field_name>" })

# STEP 4: Only after checking schema, call the tool
posthog:exec({ "command": "call <tool_name> <json_input>" })
```

Detailed reference (examples, query tools, URL patterns, guidelines) is in the `command` parameter description.
