---
name: managing-endpoint-versions
description: >
  Work safely with endpoint versions — preview a draft in the playground, roll back to an older
  version, update settings on one version without bumping query history, deactivate a specific
  version. Use when the user asks "how do I roll back my endpoint", "preview my changes before
  publishing", "I want to fix v5 without bumping the version", or anything involving the version
  history. Calls out today's limitations honestly: there is no pointer flip; "rollback" means
  forking the old query into a new top version.
---

# Managing endpoint versions

This skill is the practical guide to endpoint versioning. It covers the today-workflow, which
has some sharp edges worth being explicit about.

## When to use this skill

- "How do I roll back to v3?"
- "I want to test changes before they go live"
- "How do I update the description / `data_freshness_seconds` on a specific version?"
- "Can I disable v4 without affecting v5?"
- The user is uncertain whether a query change will cut a new version

## Versioning model — what to know

| Behaviour                                                                | Reality                                                                                                              |
| ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| Query change                                                             | **Auto-cuts a new version.** Saving any edit to the query creates a new version and bumps the current version number |
| Settings change (description, `data_freshness_seconds`, materialisation) | Does **not** cut a new version. Updates the targeted version in place                                                |
| The "current" version                                                    | Always the highest version number — it's not a pointer you can move backwards                                        |
| Calling without `?version=N`                                             | Runs the **latest** version. So unpinned callers always hit the newest                                               |
| Disabling the whole endpoint                                             | `endpoint-update` with `is_active: false` (no `version`) takes every version offline at once                         |
| Disabling a single version                                               | `endpoint-update` with `version` + `is_active: false` retires one version without affecting the others               |

The model is forward-only. There is no "make v3 the default again" operation today. Practically
this means "rollback" requires either creating a new top version that re-uses the old query, or
pinning callers to `?version=N`.

## Available tools

| Tool                | Purpose                                                                                         |
| ------------------- | ----------------------------------------------------------------------------------------------- |
| `endpoint-versions` | List all versions for an endpoint, latest first                                                 |
| `endpoint-get`      | Full config; supports `?version=N` to fetch a specific version                                  |
| `endpoint-update`   | The workhorse — supports `version` body param to target a specific version                      |
| `endpoint-run`      | Execute a version directly via `?version=N` (without affecting which version other callers hit) |

## Workflows

### Previewing a draft before publishing

There is no "draft" concept in the model. Editing the query commits it as a new version
immediately. To preview safely:

1. Test the new query first with the `execute-sql` tool (or the SQL editor) — not on the live endpoint
2. When ready, update the endpoint — this creates the new version automatically
3. Use `endpoint-run` with `?version=N` to confirm the new version returns what you expect
4. Old callers still hit the latest version (which is now your new version) — there is no
   "soft launch"

If the user needs a true staging endpoint, the only workaround today is a sibling endpoint
with a `_v2` or `_staging` suffix. Document this honestly — there is no in-product staging path.

### Rolling back to an older version

The forward-only model means "rollback" requires forking:

1. `endpoint-versions` to find the version with the good query (say v3)
2. `endpoint-get` with `?version=3` to retrieve that version's query JSON
3. `endpoint-update` with the v3 query as the new query — this **creates a new version** (e.g.
   v6) with the same query as v3
4. All callers without `?version=N` now hit v6 (== v3's query)

The old version (v5, the broken one) still exists and is still callable via `?version=5` until
explicitly deactivated.

Faster mitigation if you can change every caller: have them pin to `?version=3` until a real
fix is ready. Lower-impact than cutting a new version.

### Updating settings on a specific version

`endpoint-update` accepts a `version` field in the body. When set, settings updates apply to
that version only — they do not cut a new version. Useful when:

- Bumping `data_freshness_seconds` on an old version that some callers still pin to
- Adjusting description on a historical version for clarity
- Changing materialisation state per version (the materialisation is per-version anyway)

Important: passing `query` together with `version` is rejected — query changes always cut a new
top version, never modify history. The version arg only affects settings.

### Deactivating a single version

To take v3 out of service while keeping v4 and v5 callable:

```text
endpoint-update {name: "...", version: 3, is_active: false}
```

This sets `is_active: false` on v3 only. Callers pinned to `?version=3` start getting an error;
other callers are unaffected.

To re-enable: same call with `is_active: true`.

The whole-endpoint `is_active` field (without `version`) is a separate switch — it disables
every version at once. Use the version-scoped form for surgical takedowns.

### Pruning unused versions

Old versions accumulate over time. To find which are dead, call `endpoint-versions` and read each
version's `last_executed_at`: a version that's null or long stale hasn't been called recently.
Materialised dead versions are the costly ones — disable their materialisation with
`endpoint-update` + `version` + `is_materialized: false`, and deactivate with `is_active: false`
to signal they're retired.

Confirm with the user before retiring a version: `last_executed_at` counts only personal-API-key
calls and is recorded only for runs since that tracking was added (so a used version can still
read null), and a caller may be pinned to `?version=N`. The full audit flow lives in
`auditing-endpoints`.

## Example interaction

```text
User: "I shipped a broken query last night, v5. How do I roll back?"

Agent:
- endpoint-versions <name> → v5 (latest), v4, v3, v2, v1
- endpoint-get <name> ?version=4 → query JSON for v4
- "Rolling back means creating v6 with v4's query. v5 stays as a
   historical version but nobody hits it unless they explicitly
   pass ?version=5. Sound right?"
- User confirms
- endpoint-update <name> {query: <v4 query>} → creates v6
- endpoint-run <name> ?version=6 to confirm shape
- "Done. v6 is live with v4's query. Want me to also deactivate v5
   so it's clear it's defunct?"
- User: "Yes"
- endpoint-update <name> {version: 5, is_active: false}
```

## Important notes

- **There is no pointer flip.** "Rolling back" creates a new version. The version number is
  always going up. If the user is uncomfortable with the resulting history noise, that's a
  fair concern — surface it honestly.
- **A query change always creates a new version.** Updating settings on the side does not.
  If the user wants to fix a typo in v5's description without bumping to v6, use the version
  param.
- **Disabling a single version only blocks that version.** It doesn't change which version runs
  by default — that's always the highest version number.
- **Materialisation is per-version.** Each version has its own materialised view named
  `{endpoint_name}_v{version}`. Disabling materialisation on one version doesn't affect others.
- **Pinning is the safety net — push callers to use it.** Callers that pin to `?version=N` are
  insulated from query edits; unpinned callers always hit the latest and can be surprised by a new
  version. Encourage consumers to pin, validate a new version, then bump the pin deliberately.
- **The CLI manages versions too.** `posthog-cli exp endpoints {pull,push,diff}` lets the user
  keep endpoint definitions as YAML in version control and review changes before pushing — a
  cleaner workflow than editing live when query changes need review.
- **Activating an older version is not yet a product feature.** If the user repeatedly wants this —
  flip a pointer rather than fork — surface it as a feature gap (and nudge the team via
  `agent-feedback`). Don't pretend `endpoint-update` does it.
