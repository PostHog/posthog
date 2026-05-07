---
name: working-with-skills
description: >-
  Best practices for agents managing PostHog skills via the MCP `llma-skill-*` tools —
  how to discover, read, create, update, and refactor skills efficiently, especially
  large skills with many bundled files. Use whenever you are about to call any
  `llma-skill-*` tool, asked to author or edit a shared skill, or troubleshoot
  why a skill write was rejected. Pairs with `skills-store` (which covers the
  raw tool surface) by adding the decision-tree, efficiency, and pitfall guidance.
---

# Working with PostHog skills

This skill teaches agents how to use the `llma-skill-*` MCP tools well — minimum
context, minimum round-trips, minimum mistakes. If you are not yet familiar with
the tool surface itself, read the `skills-store` skill first for the catalog.
This document is about *how to choose between the tools* and *how to scale the
workflow* when skills get big.

## Operating principles

1. **Progressive disclosure is non-negotiable.** Lists return descriptions, get
   returns body + manifest, file-get returns one file. Never preload bundled
   files "just in case" — every preloaded script is wasted context for the
   actual task.
2. **Pick the smallest write primitive that does the job.** A targeted `edits`
   or `file_edits` is cheaper, safer, and clearer in version history than a
   full body or full bundle replacement.
3. **Reads are cheap; concurrent overwrites are not.** Always have a recent
   `version` from `llma-skill-get` (or from the response of the previous write)
   before calling any write tool, and pass it as `base_version`.
4. **Authoring follows the [Agent Skills spec](https://agentskills.io/specification).**
   Keep `name` kebab-case, descriptions trigger-rich, body short, bulky
   material in bundled files.

## Decision tree: which tool do I call?

```text
Need to know what's available?
  └─► llma-skill-list                    (names + descriptions only)

Need to use / inspect a specific skill?
  └─► llma-skill-get                     (body + file manifest, NO file contents)
        └─► llma-skill-file-get          (one file, on demand, only as referenced)

Authoring a brand new skill?
  └─► llma-skill-create                  (body + all initial files in one call)

Editing an existing skill?
  ├─ Body change?
  │    ├─ Substantial rewrite ............. update(body=...)
  │    └─ Surgical tweak .................. update(edits=[{old, new}, ...])
  ├─ Bundled file content change?
  │    └─ update(file_edits=[{path, edits:[...]}, ...])
  ├─ Add / remove / rename a file?
  │    ├─ Add ............................. llma-skill-file-create
  │    ├─ Delete .......................... llma-skill-file-delete
  │    └─ Rename .......................... llma-skill-file-rename
  └─ Wholesale bundle reset (rare!) ....... update(files=[...])  # replaces ALL files

Want a fork as the starting point?
  └─► llma-skill-duplicate               (then update the copy)
```

If you find yourself reaching for `update(body=...)` plus a sprawling `files=[...]`
to change one paragraph and one script, stop — that's two narrower calls
(`update(edits=[...])` plus `update(file_edits=[...])`) or even a single
`update` carrying both `edits` and `file_edits`.

## Discover before you fetch

```json
posthog:llma-skill-list
{ "search": "fractal" }
```

`llma-skill-list` is the right tool to "find a skill" — it returns names and
descriptions only. Reading the descriptions is the entire point: pick the right
skill before pulling any body. If `search` doesn't narrow it enough, list
without it and scan, but do not start fetching candidate bodies blindly.

`llma-skill-get` should be called **once per skill per task**, not per question.
Cache the body in your working memory; fetch again only if you suspect the
skill changed under you (e.g. a `409` on write — see "Concurrency" below).

## Reading a large skill efficiently

Big skills (long body, many bundled files) are the case where lazy loading
matters most.

1. `llma-skill-get(skill_name=...)` — read `body` + `files[]` manifest.
2. Scan the body's table of contents / headings. The body should already tell
   you which file goes with which task — that's why bodies stay short and
   reference files by path.
3. For each file the body explicitly points at for *the current task*, call
   `llma-skill-file-get(file_path=...)`. Skip everything else.
4. If the body references "see scripts/X for the rare case Y" and you are not
   in case Y, do not fetch `scripts/X`.

When in doubt, fewer files. You can always fetch one more on the next turn.

## Authoring a new skill

Use a single `llma-skill-create` call with body **and** initial files — the
skill lands at `version: 1` complete. Do not create the skill empty and then
make N follow-up `llma-skill-file-create` calls; that's N extra versions and N
extra round-trips for no benefit.

```json
posthog:llma-skill-create
{
  "name": "my-skill",
  "description": "What it does AND when to use it. Include trigger keywords.",
  "body": "# my-skill\n\n## When to use\n...\n## Workflow\n...",
  "license": "MIT",
  "compatibility": "Requires Python 3.10+",
  "allowed_tools": ["Bash", "Write"],
  "metadata": { "author": "me", "category": "..." },
  "files": [
    { "path": "scripts/foo.py", "content": "...", "content_type": "text/x-python" },
    { "path": "references/primer.md", "content": "...", "content_type": "text/markdown" }
  ]
}
```

### Authoring rules of thumb

- **`description` is the discovery surface.** It is the only thing
  `llma-skill-list` returns. Make it trigger-rich (what the user might say) and
  scope-honest (what the skill does and does not do).
- **`name`** — kebab-case, max 64 chars, no leading/trailing/consecutive
  hyphens. The spec validator rejects anything else.
- **Body ≤ ~500 lines.** Long preambles, exhaustive SQL, full example payloads,
  and runnable code belong in `references/`, `assets/`, or `scripts/`. The body
  should *route* to those files, not inline them.
- **File layout convention** — `scripts/` for executable code, `references/`
  for prose docs and examples, `assets/` for templates / data. Agents can rely
  on this for orientation when they only have the manifest.
- **`allowed_tools`** lists the MCP / built-in tools the skill expects to be
  callable. Be honest — under-declaring causes silent failures, over-declaring
  is a security smell.

## Updating an existing skill

The single most common mistake is using `update(body=..., files=[...])` for a
small change. That works, but it round-trips the entire skill, makes the diff
unreadable in version history, and risks dropping files if `files` was
incomplete. Use the smallest primitive instead.

### Always read first, capture `version`

```json
posthog:llma-skill-get
{ "skill_name": "my-skill" }
```

Note the returned `version` — pass it as `base_version` on every write. After a
successful write, the response contains the new `version`; chain further writes
with that.

### Body: full replacement vs incremental edits

Full replacement when you are restructuring the body:

```json
posthog:llma-skill-update
{ "skill_name": "my-skill", "body": "# my-skill\n\nNew body...", "base_version": 7 }
```

Incremental edits when you are tweaking a few lines (preferred for small
changes — easier to review, lower error surface):

```json
posthog:llma-skill-update
{
  "skill_name": "my-skill",
  "edits": [
    { "old": "Use Pillow for rendering.", "new": "Use Pillow ≥10.0 for rendering." },
    { "old": "## Old section title", "new": "## New section title" }
  ],
  "base_version": 7
}
```

Each `edits[].old` must match exactly once in the current body, and `body` and
`edits` are mutually exclusive in one call.

### Bundled file content edits

`file_edits` patches one or more existing files in place — non-targeted files
carry forward unchanged. This is the right primitive when you are tweaking
script logic or fixing a typo in a reference doc:

```json
posthog:llma-skill-update
{
  "skill_name": "my-skill",
  "file_edits": [
    {
      "path": "scripts/foo.py",
      "edits": [{ "old": "ITERATIONS = 100", "new": "ITERATIONS = 250" }]
    },
    {
      "path": "references/primer.md",
      "edits": [{ "old": "## Outdated header", "new": "## Updated header" }]
    }
  ],
  "base_version": 7
}
```

`file_edits` cannot **add**, **remove**, or **rename** files — only patch
existing ones. For structural changes, use the per-file tools.

### Combining edits in a single call

You can combine `edits` (body) and `file_edits` (existing files) in one
`llma-skill-update` call to publish a single coherent version when a change
spans both:

```json
posthog:llma-skill-update
{
  "skill_name": "my-skill",
  "edits": [{ "old": "## Configuration", "new": "## Setup" }],
  "file_edits": [
    { "path": "scripts/run.py", "edits": [{ "old": "DEBUG = False", "new": "DEBUG = True" }] }
  ],
  "base_version": 7
}
```

### Adding, removing, renaming files

Each is its own call, each publishes a new version:

```json
posthog:llma-skill-file-create
{ "skill_name": "my-skill", "path": "scripts/julia.py", "content": "...", "base_version": 7 }
```

```json
posthog:llma-skill-file-delete
{ "skill_name": "my-skill", "file_path": "scripts/old.py", "base_version": 8 }
```

```json
posthog:llma-skill-file-rename
{ "skill_name": "my-skill", "old_path": "scripts/julia.py", "new_path": "scripts/julia_set.py", "base_version": 9 }
```

`llma-skill-file-rename` is a true move — it carries the existing content
forward without resending it. Always prefer it over delete + create when the
content is unchanged.

### When to use `update(files=[...])` (rare)

Passing `files` to `llma-skill-update` **replaces the entire bundle** —
anything not in the array is dropped. This is the right tool only when you are
intentionally wiping and reseeding the bundle (e.g. importing a fresh local
SKILL.md tree). For almost every other case, prefer `file_edits` plus per-file
CRUD.

## Working with large multi-file skills

Skills with many files (10+) require extra discipline:

- **Treat the manifest as the index.** `llma-skill-get`'s `files[]` is your map.
  Match each task step to one file and fetch only that one.
- **Group structural changes into a sequence, not a fork.** If you are renaming
  three files, do them sequentially: `rename → rename → rename`, each chained
  via the previous response's `version`. That gives you three small reviewable
  versions instead of one giant `update(files=[...])` blob.
- **Keep edits localised.** A single `llma-skill-update` with `file_edits`
  targeting five files is fine. A single `update(files=[...])` carrying ten
  full file bodies is almost always a sign you should have used `file_edits`.
- **Refactor the body itself first.** If the body has grown past ~500 lines,
  the right next step is usually to split content into new bundled files
  before adding more material.

## Concurrency: `base_version`

Every write tool accepts `base_version`. Always pass it.

- The server compares `base_version` to the current latest version. If they
  match, the write succeeds and the new version is `base_version + 1`.
- If they differ, the write is rejected (someone else updated the skill).
  Re-run `llma-skill-get`, reconcile your changes against the new body, and
  retry with the fresh `version`.
- After a successful write, the response includes the new `version`. Chain
  further edits with that — do not re-`get` between back-to-back writes you
  control.

Skipping `base_version` does *not* speed things up — it just turns a clean
"someone else won the race" error into a silent overwrite of their work.

## Common pitfalls

- **Calling `llma-skill-list` with no search and then fetching every body** —
  defeats progressive disclosure. Read the descriptions first.
- **Pre-fetching every bundled file after `llma-skill-get`** — same mistake on
  the inner level. Fetch on demand from the body's directives.
- **Using `update(body=..., files=[...])` for a one-line fix** — round-trips
  the entire skill, makes diffs unreadable, and risks dropping files. Use
  `edits` / `file_edits`.
- **Using `update(files=[...])` when you meant to add one file** — drops every
  file you didn't include. Use `llma-skill-file-create` instead.
- **Delete + create instead of rename** — loses content history and costs an
  extra version bump.
- **Stale `base_version` after chained writes** — read the `version` from the
  previous write's response, not from your initial `get`.
- **Leaving `base_version` off** — accepts a silent overwrite. Always include
  it once you've done a `get`.
- **Empty / vague `description`** — the skill becomes effectively undiscoverable
  via `llma-skill-list` search. Treat the description as the trigger contract.
- **Long body + no bundled files** — when a body crosses ~500 lines, refactor
  into `references/` and `scripts/` rather than letting it grow.
- **Mixing `body` and `edits` in one update call** — they're mutually exclusive.
  Pick one.

## Porting a local SKILL.md tree into PostHog

When migrating a local skill folder (e.g. `my-skill/SKILL.md` plus
`scripts/`, `references/`, `assets/`):

1. Read the local `SKILL.md`. Its frontmatter maps to `name`, `description`,
   `license`, `compatibility`, `allowed_tools`, `metadata`. The body after the
   frontmatter becomes `body`.
2. Walk the bundled subdirs and gather every file as
   `{ path, content, content_type }`.
3. Call `posthog:llma-skill-create` once with everything — the skill lands at
   `version: 1` complete. Do not split this into a create + N file-create
   calls.

After the create, the skill is live for everyone via `llma-skill-get`.

## When a skill is the wrong answer

Not every persistent prompt belongs in the skills store:

- One-off task instructions belong in the conversation, not in a skill.
- Personal scratchpads belong in agent memory or local files.
- Code is not a skill — if it's something a service runs, it belongs in the
  repo.

A good skill is reusable, discoverable by description, and worth the cost of
keeping it correct over time.
