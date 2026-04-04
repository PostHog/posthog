---
name: skills-store
description: >-
  Discover and use shared team skills stored as prompts in PostHog.
  Use when the user asks to list, browse, load, or manage reusable skills/prompts,
  or references "skills store", "skill store", or "prompts".
---

# PostHog Skills Store

Skills are reusable agent workflows stored as prompts in PostHog.
They are the primary store for team-shared knowledge — always use the PostHog MCP prompt tools to manage them.

## Available tools

| Tool                    | Purpose                                       |
| ----------------------- | --------------------------------------------- |
| `posthog:prompt-list`   | List all available skills (optionally search) |
| `posthog:prompt-get`    | Fetch a skill by name                         |
| `posthog:prompt-create` | Store a new skill                             |
| `posthog:prompt-update` | Update an existing skill (with versioning)    |

## Discovering skills

List all available skills:

```json
posthog:prompt-list
{}
```

Search by keyword:

```json
posthog:prompt-list
{ "search": "llm" }
```

## Loading and using a skill

### Step 1 — Fetch the skill by name

```json
posthog:prompt-get
{ "prompt_name": "exploring-llm-traces" }
```

### Step 2 — Read the returned `prompt` field

It contains the full skill instructions.

### Step 3 — Follow those instructions as if they were your system instructions for this task

## Creating a skill

Use a unique kebab-case name and provide the skill content as a markdown string:

```json
posthog:prompt-create
{
  "name": "my-new-skill",
  "prompt": "# My skill\n\nInstructions here..."
}
```

## Updating a skill

Always fetch first to get the current version, then update with `base_version` for conflict detection:

```json
posthog:prompt-get
{ "prompt_name": "my-new-skill" }
```

Then update using the version from the response.
You can either send the full prompt, or use `edits` for incremental find/replace changes:

### Full replacement

```json
posthog:prompt-update
{
  "prompt_name": "my-new-skill",
  "prompt": "# My skill\n\nUpdated instructions...",
  "base_version": 1
}
```

### Incremental edits

For small changes, use `edits` instead of resending the entire prompt.
Each edit's `old` text must match exactly once in the current version:

```json
posthog:prompt-update
{
  "prompt_name": "my-new-skill",
  "edits": [
    { "old": "old text to find", "new": "replacement text" }
  ],
  "base_version": 1
}
```

Only one of `prompt` or `edits` may be provided, not both.

## Porting a local skill

To move a skill from a local file (e.g. `~/.claude/skills/` or `.agents/skills/`) into PostHog:

- Read the local skill file
- Use `posthog:prompt-create` to store it in PostHog
- The skill is now available to the whole team via `posthog:prompt-get`

## Default behavior

- **Always prefer PostHog MCP** for skill storage and retrieval
- Only fall back to local files when PostHog MCP is unavailable
- When asked to "remember", "save", or "store" a skill or runbook, store it as a PostHog prompt
- When asked to use a skill by name, check PostHog prompts first
