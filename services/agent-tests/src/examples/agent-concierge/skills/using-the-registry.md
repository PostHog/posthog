# Skill — using the Tools & Skills registry

Load this when the user asks about, mentions, or would benefit from
**shared, versioned skills or custom tools** — anything that fits the
shape "I want to reuse this across agents" or "make this a template
others can pin."

## What the registry is

Two new families of shared, append-only versioned templates that
agents pin into their bundle at freeze time:

- **Skill templates** (`agent_skill_template`) — markdown skills + companion
  files. Same shape as `bundle/skills/<id>.md` but team-owned and
  versioned. Canonical PostHog-shipped templates use `@posthog/<name>`;
  team-authored use plain slugs.
- **Custom tool templates** (`agent_custom_tool_template`) — TypeScript
  custom tools with `source`, `compiled_js`, `args_schema`. Compiles
  client-side; the registry just stores the artifact pair.

Agents reference them in `spec.skills[].from_template` /
`spec.tools[].from_template`. At freeze, Django resolves the ref,
copies the content into the bundle, stamps `version` back into the
spec, and writes a join row so the registry's "Used by" panel works.

## When to reach for the registry

| User intent (paraphrase)                                   | What you should do                                                                              |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| "the same skill on three agents" / "share X across agents" | Create a skill template, pin it from each spec via `from_template`                              |
| "I want a Stripe tool I can reuse"                         | Create a custom tool template instead of inlining the TS in each bundle                         |
| "use the canonical research skill"                         | Pin `@posthog/research` (canonical) via `from_template`                                         |
| "edit the X skill" — and X is a registry template          | Publish a new version of the template; existing frozen revisions stay pinned to the old version |
| "who's using this template?"                               | `agent-skill-templates-name-usages-list` / `agent-custom-tool-templates-name-usages-list`       |
| "what skills do we have?"                                  | `agent-skill-templates-list` (registry) — _not_ the per-agent bundle                            |

If the user wants a one-off skill living in a single agent's bundle,
**don't** push them into the registry. Templates are for reuse; a
single use case is just a bundle file.

## The registry tool surface

All under `@posthog/agent-skill-templates-*` and
`@posthog/agent-custom-tool-templates-*`. Read tools require
`agent_application:read`; writes require `agent_application:write`.

### Read tools (cheap, no consent)

| Tool                                             | Use when                                                                                |
| ------------------------------------------------ | --------------------------------------------------------------------------------------- |
| `agent-skill-templates-list`                     | Discover what skill templates exist (team-owned + canonical)                            |
| `agent-skill-templates-name-retrieve`            | Read one skill template's body + companion files; add `?version=N` for an older version |
| `agent-skill-templates-name-versions-list`       | Version history of a skill template                                                     |
| `agent-skill-templates-name-usages-list`         | "Who pins this skill template?" — before archiving, always run this                     |
| `agent-custom-tool-templates-list`               | Discover what tool templates exist                                                      |
| `agent-custom-tool-templates-name-retrieve`      | Read one tool template's source + compiled_js + args_schema                             |
| `agent-custom-tool-templates-name-versions-list` | Tool template version history                                                           |
| `agent-custom-tool-templates-name-usages-list`   | "Who pins this tool template?"                                                          |

### Write tools (require explicit user consent — see hard rule #5)

| Tool                                                | Effect                                                                                   |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `agent-skill-templates-create`                      | New skill template at v1. Pick a slug-shaped name; `@posthog/*` is reserved.             |
| `agent-skill-templates-name-publish-create`         | Append a new version. Body XOR `edits[]` (structured find/replace); files carry forward. |
| `agent-skill-templates-name-archive-create`         | Soft-delete every version. Frozen pins keep working, new pins forbidden.                 |
| `agent-skill-templates-name-duplicate-create`       | Clone under a new name — great for "start from `@posthog/research`."                     |
| `agent-skill-templates-name-files-create`           | Add a companion file (relative path, content).                                           |
| `agent-skill-templates-name-files-destroy`          | Remove a companion file.                                                                 |
| `agent-skill-templates-name-files-rename-create`    | Rename a companion file inside the latest version.                                       |
| `agent-custom-tool-templates-create`                | New tool template at v1. Requires `source`, `compiled_js`, `args_schema`.                |
| `agent-custom-tool-templates-name-publish-create`   | Append a new version. Source XOR `edits[]`; `compiled_js` must accompany either.         |
| `agent-custom-tool-templates-name-archive-create`   | Soft-delete every version.                                                               |
| `agent-custom-tool-templates-name-duplicate-create` | Clone under a new name.                                                                  |

## Versioning is append-only

Every publish creates `version + 1` and flips the prior row's
`is_latest`. **Old versions are not deleted** — frozen agent
revisions stay pinned to the version they froze against, even after
new versions land. This is the safety net for "I changed the skill
and broke five agents."

When the user says "edit X" against an existing registry template:

1. **Read the latest version** with `agent-skill-templates-name-retrieve`.
2. **Show the diff or summarize the change** so the user knows what's
   about to land.
3. **Publish via structured edits** with `edits: [{ old, new }]` —
   safer than full-body overwrite because each `old` must match
   exactly once. If the diff doesn't apply, the publish fails with
   `edit_index` pointing at the offending step.
4. **Surface the new version number** + how many existing pins are on
   the old version (run `…/usages/?pinned_version=<old>`).

If the template is canonical (`@posthog/<name>`), writes fail with
400 — the team isn't allowed to overwrite. Suggest **duplicate** to
fork it under a team-owned name.

## Pinning a template into an agent's spec

Inside `spec.skills[]` / `spec.tools[]`, the registry refs look
like this:

```jsonc
{
  "skills": [
    {
      "from_template": "<AgentSkillTemplate UUID>",
      "version": 3, // optional pre-freeze; stamped at freeze
      "alias": "research", // becomes bundle/skills/<alias>.md
    },
  ],
  "tools": [
    {
      "kind": "custom_template",
      "from_template": "<AgentCustomToolTemplate UUID>",
      "version": 2,
      "alias": "stripe_lookup",
    },
  ],
}
```

Omitting `version` means "latest at freeze time" — the freeze step
stamps the resolved number back. Post-freeze the entry also gains
`id` / `path` / `description` (for skills) and `kind: custom` /
`id` / `path` (for tools) so the runner can dispatch against it.
The `from_template` field stays on the JSONB row for lineage; the
runner's zod schema treats it as an extra and ignores it.

## Hard-delete is blocked

The join tables (`agent_revision_skill_template` /
`agent_revision_custom_tool_template`) use `on_delete=PROTECT`, so
Postgres refuses to hard-delete a template that a frozen revision
still pins. The only legal cleanup path is **archive** (soft delete).
If a user asks you to "really delete" a template, explain why archive
is the only safe call.

## What you must not do

- Don't write raw secrets into a custom tool template's `source` —
  same rule as bundle files, see `skills/secrets-and-integrations`.
- Don't publish a template version without surfacing the diff to the
  user. Surprise upgrades break frozen revisions on the next freeze.
- Don't archive a template without first running `…/usages/` and
  reporting affected agents to the user.
- Don't push a one-off skill into the registry just because the
  surface exists. Templates have an overhead — only worth it for ≥2
  consumers.
