---
name: skills-store
description: >-
  Discover and use shared team skills stored in PostHog.
  Use when the user asks to list, browse, load, or manage "shared skills",
  "team skills", or references the "skills store" / "skill store".
---

# PostHog Skills Store

Skills are reusable agent workflows stored in PostHog following the [Agent Skills specification](https://agentskills.io/specification) — a body of instructions (SKILL.md) plus optional bundled files (scripts, references, assets), structured metadata, and an `allowed_tools` list.

PostHog is the primary store for team-shared skills — always use the PostHog MCP skill tools to manage them.

## Available tools

| Tool                      | Purpose                                                     |
| ------------------------- | ----------------------------------------------------------- |
| `posthog:skill-list`      | List all available skills (Level 1 — names + descriptions)  |
| `posthog:skill-get`       | Fetch a skill by name (Level 2 — body + file manifest)      |
| `posthog:skill-file-get`  | Fetch a single bundled file by path (Level 3 — on demand)   |
| `posthog:skill-create`    | Store a new skill (optionally with bundled files)           |
| `posthog:skill-update`    | Publish a new version (with `base_version` for concurrency) |
| `posthog:skill-duplicate` | Duplicate an existing skill under a new name                |

Skills use progressive disclosure: discover by description, fetch the body only when relevant, and pull individual files on demand. Do not fetch every file eagerly.

## Discovering skills

List all available skills:

```json
posthog:skill-list
{}
```

Search by keyword (matches name and description):

```json
posthog:skill-list
{ "search": "fractal" }
```

`skill-list` returns only name + description — never the body. Use descriptions to decide which skill to fetch. The whole point of descriptions is that you can pick the right skill without loading any bodies.

## Loading and using a skill

### Step 1 — Fetch the skill by name

```json
posthog:skill-get
{ "skill_name": "make-fractals" }
```

The response contains:

- `body` — the full SKILL.md instructions (read these like system instructions for the task)
- `license`, `compatibility`, `allowed_tools`, `metadata` — spec fields
- `files[]` — manifest of bundled files (path + content_type only, not content)

### Step 2 — Follow the body

Read `body` and follow it. Treat it as your system instructions for this task.

### Step 3 — Fetch bundled files as needed

When the body references a script or reference doc, pull it on demand:

```json
posthog:skill-file-get
{ "skill_name": "make-fractals", "file_path": "scripts/mandelbrot.py" }
```

Only fetch files you actually need. If the body's decision tree points at one script, don't preload the others.

## Creating a skill

Use a unique kebab-case name, a description explaining when to use the skill (this is what discovery relies on), and the body as a markdown string. Bundled files are optional and can be included in a single create call:

```json
posthog:skill-create
{
  "name": "make-fractals",
  "description": "Generate fractal images as PNGs. Use when the user asks to make, render, or visualize fractals.",
  "body": "# make-fractals\n\nWhen to use... Workflow... Output contract...",
  "license": "MIT",
  "compatibility": "Requires Python 3.10+ with Pillow and numpy",
  "allowed_tools": ["Bash", "Write"],
  "metadata": { "author": "posthog", "category": "visualization" },
  "files": [
    { "path": "scripts/mandelbrot.py", "content": "...", "content_type": "text/x-python" },
    { "path": "references/primer.md", "content": "# Primer\n...", "content_type": "text/markdown" }
  ]
}
```

## Updating a skill

Each `skill-update` publishes a new immutable version. Always fetch first to get the current version, then update with `base_version` for concurrency checks:

```json
posthog:skill-get
{ "skill_name": "make-fractals" }
```

Publish a new version. Fields you don't provide are carried forward from the current latest. If you pass `files`, they replace the previous version's file set; if you omit `files`, they're carried forward:

```json
posthog:skill-update
{
  "skill_name": "make-fractals",
  "body": "# make-fractals\n\nUpdated instructions...",
  "base_version": 2
}
```

## Porting a local skill

To move a skill from a local SKILL.md directory (e.g. `~/.claude/skills/<name>/` with `scripts/`, `references/`, `assets/` subdirs) into PostHog:

1. Read the local `SKILL.md` — use its frontmatter for `name`, `description`, `license`, `compatibility`, `allowed_tools`, `metadata`; the body after the frontmatter becomes `body`
2. Walk the `scripts/`, `references/`, and `assets/` subdirs and collect each file as `{ path, content, content_type }`
3. Call `posthog:skill-create` with everything in one shot — the skill lands at v1 with its full bundle

The skill is then available to the whole team via `posthog:skill-get`.

## Default behavior

- **Always prefer PostHog MCP** for skill storage and retrieval
- Only fall back to local files when PostHog MCP is unavailable
- When asked to "save", "store", or "remember" a workflow, runbook, or multi-step procedure, store it as a PostHog skill
- When asked to use a skill by name, use `skill-get` first
- When a skill references bundled files in its body, pull them with `skill-file-get` only when needed — don't preload

## Prompts vs skills

PostHog also has a separate `posthog:prompt-*` tool family for plain single-text prompts (system prompts, short reusable text). Skills are the right choice whenever the workflow needs structured metadata, bundled files, or an `allowed_tools` surface. When in doubt, use skills.
