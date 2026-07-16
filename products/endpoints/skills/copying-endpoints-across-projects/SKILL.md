---
name: copying-endpoints-across-projects
description: >
  Copy a PostHog endpoint (a saved HogQL/insight query exposed as an API route) to another project
  in the same organization, or duplicate it under a new name in the same project. Use when the user
  wants to duplicate an endpoint, promote an endpoint from staging to production, replicate an
  endpoint's query/variables/freshness config in another workspace, or clone an endpoint to iterate
  on it. Unlike feature flags and experiments, endpoints have NO native cross-project copy tool —
  this skill covers the read-then-recreate flow (endpoint-get then endpoint-create), the
  active-project switching it requires, name-collision checks, and the safe defaults (land
  unmaterialised in the target, verify with endpoint-run). Does not cover editing endpoint versions
  (see managing-endpoint-versions) or authoring a brand-new endpoint from scratch (see
  creating-an-endpoint).
---

# Copying endpoints across projects

This skill duplicates a PostHog **endpoint** — a saved HogQL or insight query exposed as a callable API route — either into another project in the same organization, or under a new name in the same project.

## The one thing to know first

There is **no server-side endpoint copy operation**. Feature flags have `feature-flags-copy-flags-create` and experiments have `experiment-copy-to-project`; endpoints have **neither**. Copying an endpoint means:

1. Read the full source config with `endpoint-get`.
2. Recreate it with `endpoint-create` (in the target project, or under a new name in the same project).

Both `endpoint-get` and `endpoint-create` operate **only on the active MCP project** — neither takes a project id. So a cross-project copy requires the active project to be **switched** between the read (source) and the write (target). Read the source first, capture the config, then switch to the target and create. If you cannot switch projects in this session, tell the user rather than creating the copy in the wrong project.

## When to use this skill

- "Copy this endpoint to another project", "duplicate this endpoint", "clone the endpoint"
- "Promote the endpoint from staging to production" (projects-as-environments)
- "Make a copy so I can iterate without touching the live one" (same-project duplicate under a new name)
- Replicating an endpoint's query, variables, and freshness config in a different workspace

## What this skill does not cover

- **Cross-organization copy.** Endpoints (and their queries) can only be recreated in projects you have editor access to; there is no org-to-org path.
- **Editing versions of an existing endpoint** — see `managing-endpoint-versions`.
- **Designing a new endpoint from scratch** — see `creating-an-endpoint` (this skill assumes the source endpoint already exists and is configured correctly).
- **Bulk-copying every endpoint in a project.** Copy one at a time; loop `endpoints-get-all` → per-endpoint copy if the user really wants all of them, and tell them you're doing so.

## Workflow

### 1. Resolve the source endpoint

You need the endpoint's **name** and the **source project**.

- If the user gave a name, use it. If they gave a fuzzy description, call `endpoints-get-all` in the source project and match on name/description.
- If the user didn't say which project the endpoint lives in, ask — don't assume the active MCP project is the source. Copying out of the wrong source is the most common foot-gun.
- Confirm the active project is the source (call `project-get` with no id to see the active project) before reading.

### 2. Read the full source config

Call `endpoint-get` with the source name. Capture everything you'll need to recreate it:

- `name`
- `query` (the whole HogQL/insight query definition — including any declared variables / `code_name`s)
- `description`
- `data_freshness_seconds`
- `is_materialized` (source state — see step 5 for why you usually don't copy this as-is)
- `tags`

Present a short summary to the user before copying: what the query returns, its variables, its freshness setting, and whether the source is materialised.

### 3. Resolve the target and check for a name collision

**Cross-project:** confirm the target project belongs to the same org and the user has editor access there. The copy will be created in whatever project is active at `endpoint-create` time, so plan to switch the active project to the target between step 2 and step 6.

**Same-project duplicate:** the new endpoint needs a **different name** — names are unique within a project and the URL path (`/api/projects/{team_id}/endpoints/{name}/run`) depends on it. Agree a new name with the user.

Either way, run `endpoints-get-all` in the target project and check whether the intended name already exists. If it does, stop and ask: creating over an existing name is not a safe silent action. Get the name right up front — it's baked into the caller URL and not trivially renameable later.

### 4. Decide the name in the target

- Cross-project, same purpose: keep the same name so caller code ports unchanged.
- Same-project or "copy to iterate": pick a clearly-derived new name (e.g. `weekly_active_users_v2`, `weekly_active_users_staging`). Snake_case, URL-safe, starts with a letter, max 128 chars.

### 5. Choose materialisation for the copy (default: OFF)

**Default to `is_materialized: false` on the copy, even when the source is materialised.** Rationale mirrors the safe default in `copying-flags-across-projects` (land disabled): materialisation costs recompute/storage on a cadence, and a freshly-copied endpoint has no proven traffic in the target yet. Ship it unmaterialised, confirm it's actually called, then enable materialisation later once usage justifies the cost.

Override to `is_materialized: true` only if the user explicitly wants the copy materialised from day one (e.g. a like-for-like production promotion of a high-traffic endpoint). Note the caveats from `creating-an-endpoint`: queries with cohort breakdowns or compare mode, and insight kinds other than Trends/Lifecycle/Retention (e.g. Funnels), are **not materialisable** — `endpoint-create` will simply create them unmaterialised regardless.

Carry `data_freshness_seconds` over unchanged unless the user wants different freshness in the target (remember it doubles as the materialisation refresh cadence).

### 6. Create the copy

With the target project active, call `endpoint-create` with:

- `name` — from step 4
- `query` — the source query captured in step 2, verbatim (this carries the variables/`code_name`s)
- `description` — from source (optionally note it's a copy)
- `data_freshness_seconds` — from source unless the user changed it
- `is_materialized` — from step 5 (default `false`)
- `tags` — from source if the user wants them; drop tags that are meaningless in the target project

### 7. Verify

Call `endpoint-run` on the new endpoint with a representative `variables` payload and confirm the response shape matches the source. For a cross-project promotion, sanity-check that the underlying events/properties the query references actually exist in the target project — a query that's valid in staging can return empty or error in a project with different taxonomy. If the copy is HogQL and callers rely on `offset` pagination, note that `offset` on `endpoint-run` is only supported for HogQL endpoints (not insight endpoints).

### 8. Report

Tell the user: the new endpoint's name and project, its materialisation state, its freshness setting, and the result of the verification run. If you switched the active project to do the copy, say which project is active now so they aren't surprised on their next call.

## Important notes

- **The query is a copy, not a link.** Like creating an endpoint from an insight, the target endpoint owns its own copy of the query. Later edits to the source endpoint do **not** propagate to the copy.
- **Variables come along inside `query`.** HogQL `code_name` variable declarations and insight breakdown variables live inside the query definition, so copying `query` verbatim preserves them. Double-check the copy's variables in the verification run.
- **No undo.** `endpoint-create` makes a new endpoint (or fails if the name is taken). Always confirm the target name and project with the user before creating, especially when the target is production.
- **Access.** The user needs editor access on the target project's team; without it `endpoint-create` will be rejected.

## Available tools

- `endpoint-get` — read the full source endpoint config (query, variables, freshness, materialisation, tags). Supports `?version=N`.
- `endpoint-create` — create the copy in the active project. Fields: `name`, `query`, `description`, `data_freshness_seconds`, `is_materialized`, `tags`.
- `endpoints-get-all` — list endpoints in the active project; use to resolve a fuzzy source name and to check for a name collision in the target.
- `endpoint-run` — execute the new endpoint to verify the copy's response shape.
- `project-get` — call with no id to confirm which project is currently active before reading the source or creating the copy.
