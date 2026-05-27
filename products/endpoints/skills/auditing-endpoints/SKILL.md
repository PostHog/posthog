---
name: auditing-endpoints
description: >
  Audit every endpoint in a PostHog project for staleness, failed materialisations, and unused
  materialised versions. Use when the user asks "what endpoints can I clean up?", "are any of my
  endpoints broken?", "which materialised versions are still being called?", or wants a one-shot
  cleanup pass over the Endpoints product. Produces a prioritised report grouped by issue type, with
  recommended actions but does not modify anything without explicit confirmation.
---

# Auditing endpoints

This skill produces a project-wide audit of the Endpoints product. Use it when the user wants to
**find what to clean up** — unused endpoints, failing materialisations, materialised versions that
nobody calls any more. It does not modify anything; it reports.

The deeper investigation per endpoint is `diagnosing-endpoint-performance`. The audit's job is to
find candidates and hand off.

## When to use this skill

- "Audit my endpoints" / "What endpoints can I clean up?"
- The user is taking over a project and wants to know what they've inherited
- A periodic review (monthly / quarterly) of endpoint sprawl
- The user is over a materialisation cost budget and wants to know what to disable

The dedicated tools give a fast endpoint-level view. For per-version usage, call frequency, or
historical trends, query the `query_log` table with `execute-sql` — see "Deeper usage analysis"
below.

## Available tools

| Tool                              | What it's for                                                                                                                                                                                                                 |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `execute-sql` (HogQL)             | **Primary read path.** Query `system.data_modeling_endpoints` for metadata (name, is_active, current_version, derived_from_insight, last_executed_at) and `query_log` for usage (per-version calls, recency, duration, bytes) |
| `endpoint-materialization-status` | Per endpoint: is materialisation eligible, current status, last run, last error (not in the system tables — use this tool)                                                                                                    |
| `endpoint-versions`               | All versions for one endpoint, latest first, with each version's query and materialisation state                                                                                                                              |
| `endpoint-update`                 | Write path — disable (`is_active: false`) or unmaterialise (`is_materialized: false`) after the user confirms                                                                                                                 |
| `agent-feedback`                  | Tell the PostHog team what's missing or confusing in this flow so the product and skill improve                                                                                                                               |

Prefer reading from the system tables over the `endpoints-get-all` / `endpoint-get` tools — one
SQL query returns the whole inventory and lets you join metadata to usage in `query_log`.

## What counts as an issue

| Category                        | Trigger                                                               | Typical action                                     |
| ------------------------------- | --------------------------------------------------------------------- | -------------------------------------------------- |
| **Never called**                | No rows in `query_log` for the endpoint (personal-API-key calls only) | Confirm with the user, then disable                |
| **Stale**                       | `query_log` shows the last call more than 30 days ago                 | Confirm with the user; often safe to disable       |
| **Inactive**                    | `is_active = 0` in `system.data_modeling_endpoints`                   | Verify intent; if abandoned, delete                |
| **Failing materialisation**     | `endpoint-materialization-status` returns `Failed` with an error      | Hand off to `diagnosing-endpoint-performance`      |
| **Unused materialised version** | A materialised version with no calls in `query_log`                   | Unmaterialise that version, or roll to a newer one |
| **Drifted versions**            | Many versions exist (query changed repeatedly)                        | History noise — not an issue, but worth noting     |

`query_log` usage reflects the actual latest call (no artificial granularity) but covers
**personal-API-key calls only** — an endpoint exercised solely from the Playground tab or the app
will look unused. Always confirm before removing.

## Workflow

### 1. List endpoints and their metadata

One `execute-sql` query gets the whole inventory from `system.data_modeling_endpoints`:

```sql
SELECT name, is_active, current_version, derived_from_insight, last_executed_at
FROM system.data_modeling_endpoints
ORDER BY name
```

No rows → the project has no endpoints; say so and stop. Don't invent issues. (The
`last_executed_at` column here is a convenience endpoint-level timestamp; for accurate, per-version
and historical usage, use `query_log` in the next step.)

### 2. Pull usage from `query_log`

`query_log` records every personal-API-key call, tagged with the endpoint name and the version
that ran. One query gives recency and per-version call counts across all endpoints:

```sql
SELECT name, endpoint_version, count() AS calls, max(query_start_time) AS last_called
FROM query_log
WHERE endpoint LIKE '%/endpoints/%' AND is_personal_api_key_request
GROUP BY name, endpoint_version
ORDER BY name, endpoint_version DESC
```

Cross-reference with step 1:

- **In metadata, absent from `query_log`** → never called via API key
- **Last call more than 30 days ago** → stale
- **A materialised version with 0 calls** → unused materialised version (the prime cleanup target)

`query_log` also exposes `query_duration_ms`, `read_rows`, and `read_bytes` per call — useful to
flag expensive endpoints in the same pass. Per-version coverage begins when the `endpoint_version`
tag started being recorded; older calls aggregate at the endpoint level only.

### 3. Check materialisation health

For each materialised endpoint, call `endpoint-materialization-status` (this isn't in the system
tables). Surface any with `status: "Failed"` separately — these are active failures, not staleness.

### 4. Present the audit

Render a prioritised report grouped by category. Don't dump raw JSON; use a readable table per
section:

```text
## Endpoints audit — 9 issues

### 🔴 Failing materialisations (1)
- weekly_revenue (v3) — Failed 2h ago, "Column 'event_date' does not exist"
  → hand off to diagnosing-endpoint-performance

### 🟠 Never called via API key (3)
- internal_admin_query — created 5 months ago
- legacy_signup_funnel — created 1 year ago, materialised
- experiment_arm_lookup — created 9 months ago

### 🟠 Unused materialised versions (2)  [from query_log]
- monthly_active_users — v3 materialised, 0 calls (currently on v4 — unmaterialise v3)
- order_summary — v1 materialised, 0 calls

### 🟡 Stale (3)
- holiday_promo_2024 — last called 4 months ago
- ab_test_phase_1 — last called 2 months ago
- daily_revenue_cohort — last called 45 days ago

Recommended order:
1. Investigate the failing materialisation (blocks fresh data)
2. Unmaterialise the unused versions (free storage + compute)
3. Disable the never-called endpoints (if user confirms)
4. Review stale endpoints with the user
```

The exact format is less important than: prioritised, grouped, actionable, and hand-off
clear.

### 5. Offer the next step

End with a clear question, not a decision:

- "Want me to unmaterialise the unused versions?" — needs `endpoint-update` with
  `is_materialized: false` per version
- "Want me to disable the never-called endpoints?" — needs `endpoint-update` with `is_active: false`
- "Want me to dig into the failing materialisation?" — hands off to
  `diagnosing-endpoint-performance`

**Never act from the audit alone.** Disabling or unmaterialising affects external API consumers;
always confirm before modifying.

## Example interaction

```text
User: "Audit my endpoints"

Agent steps:
- execute-sql on system.data_modeling_endpoints → 12 endpoints (4 materialised)
- execute-sql on query_log grouped by name, endpoint_version → 8 endpoints have calls;
  order_summary v2 has 0 calls
- endpoint-materialization-status on each materialised endpoint → 1 failing

- Report:
  "Found 6 things worth looking at across 12 endpoints:

   🔴 Failing materialisations (1)
   - monthly_active_users (v2) — materialisation failed yesterday with
     'memory limit exceeded'. The endpoint is still callable inline but
     responses will be slower.

   🟠 Never called via API key (3)
   - legacy_funnel_v1 — created 11 months ago
   - test_export — created 3 months ago
   - admin_dump — created 8 months ago, materialised (wasteful)

   🟠 Unused materialised versions (1)  [from query_log]
   - order_summary v2 — materialised but only v3 has calls.
     The v2 materialised view can be dropped safely.

   🟡 Stale (1)
   - holiday_2024 — last called 5 months ago

   Caveat: the endpoint-level signal only covers personal-API-key calls;
   playground and dashboard runs aren't counted. Per-version numbers
   come from query_log. Confirm before disabling.

   Want me to start with the failing materialisation, or clean up the
   unused version first?"
```

## Important notes

- **The audit is read-only.** Never call destructive tools from this flow. Hand off or confirm
  before any modification.
- **Empty = healthy.** Don't pad an empty report with theoretical issues. "Nothing to clean up"
  is a good answer.
- **Read with SQL.** `system.data_modeling_endpoints` (metadata) and `query_log` (usage) via
  `execute-sql` are the read path — one or two queries answer the whole audit and let you join
  metadata to per-version usage. The `data_modeling_endpoints.last_executed_at` column is a handy
  endpoint-level shortcut, but `query_log` is authoritative for per-version, frequency, and history.
- **API-key-only scope.** `query_log` usage only counts personal-API-key calls. An endpoint
  exercised only from the Playground tab or the app will look unused. Always confirm before acting.
- **Materialisation costs storage and compute.** When an endpoint no longer needs materialisation,
  the cheapest fix is `endpoint-update` with `is_materialized: false` — not deleting the endpoint.
- **Inactive ≠ stale.** An endpoint with `is_active: false` was deliberately turned off. Don't
  recommend deletion unless the user confirms it's truly abandoned.
