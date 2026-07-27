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

The dedicated tools give a fast endpoint-level view. For call frequency, recency, and cost over
time, query the `query_log` table with `execute-sql` (endpoint-level). Per-version recency comes
from `endpoint-versions` — each version carries its own `last_executed_at`.

## Available tools

| Tool                              | What it's for                                                                                                                                                                                                                          |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `execute-sql` (HogQL)             | **Primary read path.** Query `system.data_modeling_endpoints` for metadata (name, is_active, current_version, derived_from_insight, last_executed_at) and `query_log` for endpoint-level usage (call counts, recency, duration, bytes) |
| `endpoint-materialization-status` | Per endpoint: is materialisation eligible, current status, last run, last error (not in the system tables — use this tool)                                                                                                             |
| `endpoint-versions`               | All versions for one endpoint, latest first, with each version's query, materialisation state, and `last_executed_at`                                                                                                                  |
| `endpoint-update`                 | Write path — disable (`is_active: false`) or unmaterialise (`is_materialized: false`) after the user confirms                                                                                                                          |
| `agent-feedback`                  | Tell the PostHog team what's missing or confusing in this flow so the product and skill improve                                                                                                                                        |

Prefer reading from the system tables over the `endpoints-get-all` / `endpoint-get` tools — one
SQL query returns the whole inventory and lets you join metadata to usage in `query_log`.

## What counts as an issue

| Category                        | Trigger                                                                                          | Typical action                                     |
| ------------------------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------- |
| **Never called**                | No rows in `query_log` for the endpoint (personal-API-key calls only)                            | Confirm with the user, then disable                |
| **Stale**                       | `query_log` shows the last call more than 30 days ago                                            | Confirm with the user; often safe to disable       |
| **Inactive**                    | `is_active = 0` in `system.data_modeling_endpoints`                                              | Verify intent; if abandoned, delete                |
| **Failing materialisation**     | `endpoint-materialization-status` returns `Failed` with an error                                 | Hand off to `diagnosing-endpoint-performance`      |
| **Unused materialised version** | A materialised version whose `last_executed_at` (from `endpoint-versions`) is null or long stale | Unmaterialise that version, or roll to a newer one |
| **Drifted versions**            | Many versions exist (query changed repeatedly)                                                   | History noise — not an issue, but worth noting     |

Usage counts only **personal-API-key calls** — an endpoint exercised solely from the Playground
tab or the app will look unused. Per-version `last_executed_at` is recorded only for runs since
that tracking was added, so a version can read null while still being used; always confirm before
removing.

## Workflow

### 1. List endpoints and their metadata

One `execute-sql` query gets the whole inventory from `system.data_modeling_endpoints`:

```sql
SELECT name, is_active, current_version, derived_from_insight, last_executed_at
FROM system.data_modeling_endpoints
ORDER BY name
```

No rows → the project has no endpoints; say so and stop. Don't invent issues. (The
`last_executed_at` column here is a convenience endpoint-level timestamp; for call frequency and
cost, use `query_log` in the next step.)

### 2. Pull usage from `query_log`

`query_log` records every personal-API-key call, tagged with the endpoint name. One query gives
recency and call counts across all endpoints:

```sql
SELECT name, count() AS calls, max(query_start_time) AS last_called
FROM query_log
WHERE endpoint LIKE '%/endpoints/%' AND is_personal_api_key_request
GROUP BY name
ORDER BY name
```

Cross-reference with step 1:

- **In metadata, absent from `query_log`** → never called via API key
- **Last call more than 30 days ago** → stale

`query_log` also exposes `query_duration_ms`, `read_rows`, and `read_bytes` per call — useful to
flag expensive endpoints in the same pass. This is endpoint-level; per-version recency comes from
`endpoint-versions` (step 3).

### 3. Check materialisation health and unused versions

For each materialised endpoint, call `endpoint-materialization-status` (this isn't in the system
tables). Surface any with `status: "Failed"` separately — these are active failures, not staleness.

Then call `endpoint-versions` and read each version's `last_executed_at`: a **materialised**
version that's null or long stale is an unused-materialised-version candidate. Treat this as a
lead, not proof — per-version recency only counts API-key runs since tracking was added, so confirm
with the user before unmaterialising.

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

### 🟠 Unused materialised versions (2)  [from endpoint-versions]
- monthly_active_users — v3 materialised, last_executed_at null (currently on v4 — unmaterialise v3)
- order_summary — v1 materialised, last_executed_at null

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
- execute-sql on query_log grouped by name → 8 endpoints have calls
- endpoint-materialization-status on each materialised endpoint → 1 failing
- endpoint-versions on the materialised ones → order_summary v2's last_executed_at is null

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

   🟠 Unused materialised versions (1)  [from endpoint-versions]
   - order_summary v2 — materialised but its last_executed_at is null
     while v3 is current. Likely safe to unmaterialise v2.

   🟡 Stale (1)
   - holiday_2024 — last called 5 months ago

   Caveat: usage only counts personal-API-key calls; playground and
   dashboard runs aren't counted. Per-version recency comes from
   endpoint-versions and is sparse. Confirm before disabling.

   Want me to start with the failing materialisation, or clean up the
   unused version first?"
```

## Important notes

- **The audit is read-only.** Never call destructive tools from this flow. Hand off or confirm
  before any modification.
- **Empty = healthy.** Don't pad an empty report with theoretical issues. "Nothing to clean up"
  is a good answer.
- **Read with SQL, drill in with the version tool.** `system.data_modeling_endpoints` (metadata)
  and `query_log` (endpoint-level call counts, recency, cost) via `execute-sql` answer most of the
  audit. Per-version recency comes from `endpoint-versions` (each version's `last_executed_at`).
- **API-key-only scope.** Usage only counts personal-API-key calls. An endpoint exercised only from
  the Playground tab or the app will look unused. Always confirm before acting.
- **Materialisation costs storage and compute.** When an endpoint no longer needs materialisation,
  the cheapest fix is `endpoint-update` with `is_materialized: false` — not deleting the endpoint.
- **Inactive ≠ stale.** An endpoint with `is_active: false` was deliberately turned off. Don't
  recommend deletion unless the user confirms it's truly abandoned.
