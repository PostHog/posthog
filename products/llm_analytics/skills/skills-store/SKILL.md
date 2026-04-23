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

| Tool                        | Purpose                                                    |
| --------------------------- | ---------------------------------------------------------- |
| `posthog:skill-list`        | List all available skills (Level 1 — names + descriptions) |
| `posthog:skill-get`         | Fetch a skill by name (Level 2 — body + file manifest)     |
| `posthog:skill-file-get`    | Fetch a single bundled file by path (Level 3 — on demand)  |
| `posthog:skill-create`      | Store a new skill (optionally with bundled files)          |
| `posthog:skill-update`      | Publish a new version (body, `edits`, or `file_edits`)     |
| `posthog:skill-file-create` | Add one bundled file to a skill (publishes a new version)  |
| `posthog:skill-file-delete` | Remove one bundled file from a skill                       |
| `posthog:skill-file-rename` | Rename one bundled file (move without rewriting content)   |
| `posthog:skill-duplicate`   | Duplicate an existing skill under a new name               |

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

Follow the [Agent Skills specification](https://agentskills.io/specification) when creating skills:

- **`name`** — kebab-case, max 64 chars, no leading/trailing/consecutive hyphens
- **`description`** — explain what it does AND when to use it. Include keywords agents will search for. This is the only thing visible at discovery time — make it count.
- **`body`** — keep under ~500 lines. Move detailed reference material, SQL, scripts, and long examples into bundled `files` so the body stays scannable.
- **Files** — use `scripts/` for executable code, `references/` for docs, `assets/` for templates/data. Agents pull these on demand via `skill-file-get`, so splitting keeps context lean.

Bundled files are optional and can be included in a single create call:

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

Each write publishes a new immutable version. Always fetch first to get the current version, then update with `base_version` for concurrency checks:

```json
posthog:skill-get
{ "skill_name": "make-fractals" }
```

Pick the most surgical primitive for what you're changing — the API offers several so you don't have to round-trip the whole skill to tweak one part. Anything you don't touch is carried forward from the current latest.

### Editing the body

Full replacement (good for substantial rewrites):

```json
posthog:skill-update
{
  "skill_name": "make-fractals",
  "body": "# make-fractals\n\nUpdated instructions...",
  "base_version": 2
}
```

Incremental find/replace (good for small tweaks — no round-tripping the whole body):

```json
posthog:skill-update
{
  "skill_name": "make-fractals",
  "edits": [
    { "old": "Use Pillow for rendering.", "new": "Use Pillow ≥10.0 for rendering." }
  ],
  "base_version": 2
}
```

Each `edits[].old` must match exactly once. `body` and `edits` are mutually exclusive.

### Editing one bundled file

Use `file_edits` to patch a single file without resending any other file:

```json
posthog:skill-update
{
  "skill_name": "make-fractals",
  "file_edits": [
    {
      "path": "scripts/mandelbrot.py",
      "edits": [
        { "old": "ITERATIONS = 100", "new": "ITERATIONS = 250" }
      ]
    }
  ],
  "base_version": 2
}
```

Non-targeted files carry forward unchanged. `file_edits` cannot add, remove, or rename files — use the per-file tools below for that.

### Adding, removing, or renaming a file

Atomic per-file tools — each publishes a new version and returns the updated skill (read its `version` to chain further edits via `base_version`):

```json
posthog:skill-file-create
{ "skill_name": "make-fractals", "path": "scripts/julia.py", "content": "...", "base_version": 2 }
```

```json
posthog:skill-file-delete
{ "skill_name": "make-fractals", "file_path": "scripts/old.py", "base_version": 3 }
```

```json
posthog:skill-file-rename
{ "skill_name": "make-fractals", "old_path": "scripts/julia.py", "new_path": "scripts/julia_set.py", "base_version": 4 }
```

### Replacing the whole bundle (rare)

Passing `files` to `skill-update` replaces ALL bundled files — anything not in the array is dropped. Only use this when you intentionally want to wipe and reseed the bundle. For everything else, prefer `file_edits` or the per-file CRUD tools above.

## Porting a local skill

To move a skill from a local SKILL.md directory (e.g. a local skills folder with `scripts/`, `references/`, `assets/` subdirs) into PostHog:

1. Read the local `SKILL.md` — use its frontmatter for `name`, `description`, `license`, `compatibility`, `allowed_tools`, `metadata`; the body after the frontmatter becomes `body`
2. Walk the `scripts/`, `references/`, and `assets/` subdirs and collect each file as `{ path, content, content_type }`
3. Call `posthog:skill-create` with everything in one shot — the skill lands at v1 with its full bundle

The skill is then available to the whole team via `posthog:skill-get`.

## Quick access: local bridge skill

Most coding agents support local skills or slash commands. A local bridge skill gives you a shortcut (e.g. `/phs my-github`) that routes straight to the PostHog skills API — faster and more deterministic than asking the agent to "use the PostHog skills store to load my-github".

Create a local skill in your agent's skills directory with these instructions:

```markdown
---
name: phs
description: >-
  Access and run shared team skills stored in PostHog.
  Use when the user asks to list, run, or manage PostHog skills,
  or references /phs, "ph skills", or "posthog skills".
user-invocable: true
allowed-tools: mcp__posthog__skill-list, mcp__posthog__skill-get, mcp__posthog__skill-create, mcp__posthog__skill-update, mcp__posthog__skill-file-get, mcp__posthog__skill-file-create, mcp__posthog__skill-file-delete, mcp__posthog__skill-file-rename, mcp__posthog__skill-duplicate
---

# PostHog Skills Store

Local bridge to the PostHog Skills Store.

## Load and run a skill

When the user says `/phs <skill-name>`:

1. `skill-get(skill_name="<skill-name>")` to fetch body + file manifest
2. Read the `body` field — follow it as system instructions for this task
3. Use `skill-file-get` to pull bundled scripts/references on demand

## List skills

skill-list # all skills
skill-list(search="llma") # filter by keyword

## Create / update

skill-create(name="my-skill", description="...", body="# Instructions...")
skill-get → note version → skill-update(skill_name="...", base_version=N, body="...")

## Edit one part of an existing skill

skill-get → note version → pick the smallest primitive:

- body tweak: skill-update(skill_name="...", base_version=N, edits=[{old, new}])
- one bundled file: skill-update(skill_name="...", base_version=N, file_edits=[{path, edits:[{old, new}]}])
- add/remove/rename a file: skill-file-create / skill-file-delete / skill-file-rename
```

The bridge is intentionally minimal — it just routes to the MCP tools. The real instructions live in PostHog and update without touching local files.

> **Agent-specific setup:** Where to save this depends on your agent. For Claude Code, save as `~/.claude/skills/phs/SKILL.md`. For other agents, consult your agent's docs on local skill or slash command configuration.

## Default behavior

- **Always prefer PostHog MCP** for skill storage and retrieval
- Only fall back to local files when PostHog MCP is unavailable
- When asked to "save", "store", or "remember" a workflow, runbook, or multi-step procedure, store it as a PostHog skill
- When asked to use a skill by name, use `skill-get` first
- When a skill references bundled files in its body, pull them with `skill-file-get` only when needed — don't preload
