---
name: auditing-warehouse-source-health
description: >
  Audit the health of a PostHog project's data warehouse sources and syncs — find every broken or degraded source
  connection, sync schema, and webhook channel. Use when the user asks "why are my imports failing?", "what's broken
  with my sources?", "why is my warehouse data stale?", or wants a one-shot triage of source/sync health before
  deciding where to dig in. Produces a prioritized report grouped by severity, with recommended next steps. For
  materialized-view health use `auditing-warehouse-view-health`; for a single failing sync use
  `diagnosing-failed-warehouse-syncs`.
---

# Auditing data warehouse source health

This skill produces a project-wide audit of the **source and sync** side of the data warehouse pipeline — source
connections, sync schemas, and webhook push channels. Use it when the user wants a **summary of what's broken with
their imports**, not a deep-dive on one sync. The deep-dive on individual failures is
`diagnosing-failed-warehouse-syncs`; this skill is the scan that tells them where to look first.

The health-issues tools report every kind of health check in the project, not just sources — materialized-view
failures, ingestion warnings, outdated SDKs, web-analytics setup gaps, and more. Materialized views are covered by
`auditing-warehouse-view-health`. The other health-check kinds are owned by other products — surface them if they
appear, but route them to the relevant team rather than diagnosing here.

## When to use this skill

- "Why are my imports failing?" / "What's broken with my sources?"
- "Why is my warehouse data stale?"
- The user is new to a project and wants to know which sources they've inherited and whether they're healthy
- Weekly or monthly review of source/sync health
- Dashboards are stale and the user isn't sure which source is at fault

## Available tools

| Tool                                          | Purpose                                                                          |
| --------------------------------------------- | -------------------------------------------------------------------------------- |
| `health-issues-summary`                       | One-shot: active health-issue counts by `kind` and `severity` across the project |
| `health-issues-list`                          | Active health issues, filterable by `kind`, `severity`, `status`, `dismissed`    |
| `health-issues-get`                           | One issue's full `payload` plus trusted `remediation` (`human` + `agent`)        |
| `external-data-sources-list`                  | All sources with status and latest error                                         |
| `external-data-schemas-list`                  | All schemas with status, last_synced_at, latest_error                            |
| `external-data-sources-webhook-info-retrieve` | Check per-source webhook state (not covered by health issues)                    |

The health-issues tools aggregate across every health check — they're the fastest path to a summary. Call
`health-issues-summary` for the counts, then `health-issues-list` with `kind=external_data_failure` (always pass
`status=active` and `dismissed=false` — the list does **not** default-exclude resolved or dismissed issues), and
`health-issues-get` for a single issue's `remediation`. Use the external-data list endpoints when you need more
context than the summary provides (row counts, non-failing items, schema-level detail, source-level status).

## What counts as a source/sync "issue"

From the health-issues tools, this audit cares about a single `kind`:

| `kind`                  | Trigger                                                                                                     | Typical severity |
| ----------------------- | ----------------------------------------------------------------------------------------------------------- | ---------------- |
| `external_data_failure` | A sync schema is `Failed`, has hit a billing limit, or was paused with an error — the source/sync is broken | `warning`        |

Each issue carries a top-level `kind`, `severity` (`critical`/`warning`/`info`), and `status` (`active`/`resolved`),
plus a check-specific `payload` (`pipeline_name`, `pipeline_id`, `source_type`, `error`). `health-issues-get` adds a
human `title`, `summary`, `link`, and trusted `remediation`. The failing schema's `error` text (or a cross-check via
`external-data-schemas-list`) is what distinguishes a credential/schema failure from a billing-limit stop.

The other `kind`s the health checks return are out of scope for this skill:

- `materialized_view_failure` → `auditing-warehouse-view-health`
- setup-health kinds (`sdk_outdated`, `ingestion_warning`, `web_vitals`, `reverse_proxy`, …) → owned by the relevant
  product (growth / ingestion / web analytics); route, don't diagnose here

Note the health checks only report _active failures_. For source/sync health they don't flag:

- Schemas paused by the user with no recorded error (`should_sync = false`, no `latest_error`)
- Schemas that are slow or stale but technically `Completed`
- **Webhook problems on `sync_type: "webhook"` schemas.** The bulk-sync safety net can succeed while the webhook
  push channel is silently broken (deregistered, disabled on the remote side, failing signature verification).
  These don't surface as health issues — check per-source with `webhook-info-retrieve`.

If the user asks about staleness or unused items, reach beyond these tools — see Step 4.

## Workflow

### Step 1 — One-shot pull

Call `health-issues-summary` for the by-`kind` counts, then `health-issues-list` with `kind=external_data_failure`,
`status=active`, `dismissed=false` to pull the failing sources/syncs. Use `health-issues-get` on any issue whose
`remediation` you want to relay.

If there are no `external_data_failure` issues, tell the user their sources are healthy and stop. Don't invent
problems.

### Step 2 — Group and prioritize

1. **Whole-source failures first.** When many `external_data_failure` issues share one `source_type` (or, via
   `external-data-sources-list`, one source sitting in `Error`), that's a cascade — every schema under the source is
   effectively dead until it reconnects. Fix the source first.
2. **Individual sync schemas next**, in this order:
   - Billing-limit stops (the `error` text says so, or `external-data-schemas-list` shows `BillingLimitReached`) —
     billing issue, non-technical, flag and route to billing
   - `Failed` on heavily-used tables (user asks / check row counts via schemas-list if needed)
   - `Failed` on less-used tables

### Step 3 — Present the audit

Render a prioritized report. Don't dump the raw JSON — human-readable table per category:

```text
## Data warehouse source health — 4 issues

### 🔴 Sources (1)
- Stripe — authentication failed (failed 2h ago). All 8 tables under it are currently dead.
  → `diagnosing-failed-warehouse-syncs` on this source

### 🟠 Sync schemas (3)
- postgres_prod.orders (Failed 6h ago) — column "updated_at" does not exist
- postgres_prod.invoices (Failed 6h ago) — column "updated_at" does not exist
- hubspot.contacts (BillingLimitReached) — team quota exceeded

Recommended order:
1. Stripe auth (everything under it is dead)
2. Schema-drift on postgres_prod.orders / invoices — looks like upstream renamed a column
3. Billing limit on hubspot
```

The exact format is less important than: prioritized, grouped, actionable, and hinting at the right next skill.

### Step 4 — Go beyond active failures (when asked)

If the user wants more than just "what's on fire" — e.g. "what else should I look at?" — cross-check:

**Stale but "Completed" schemas:**
Call `external-data-schemas-list` and look for schemas with old `last_synced_at` relative to their `sync_frequency`.
A schema on `1hour` frequency that last synced 3 days ago is effectively broken even if status says `Completed`.

**Sources with zero sync activity:**
Sources where every schema has `should_sync: false` or `status = Paused`. These were set up and then abandoned —
candidates for cleanup via `external-data-sources-destroy`.

**Broken webhooks on webhook-type schemas:**
Iterate the sources that have any schema with `sync_type: "webhook"` (visible via `external-data-schemas-list`). For
each, call `external-data-sources-webhook-info-retrieve({source_id})`:

- `exists: false` while a schema is `sync_type: "webhook"` → webhook was never registered, or was deleted. Push
  channel is dead; only the bulk fallback is ingesting.
- `external_status.error` present → remote service is reporting a problem (permission revoked, endpoint
  deleted on their dashboard).
- `external_status.status` not `"enabled"` → remote has disabled the endpoint (often after repeated delivery
  failures).

Report these separately from the primary audit — they're a different shape of problem than failed syncs, and the fix
is a different skill (`diagnosing-failed-warehouse-syncs` scenario I, or `setting-up-a-data-warehouse-source` step
5.5).

Only run these extra checks if the user explicitly asks for a broader audit — they involve more tool calls and
heuristics.

### Step 5 — Offer the next step

End the audit with a clear hand-off:

- "Want me to dig into the Stripe failure?" → hands off to `diagnosing-failed-warehouse-syncs`
- "Want me to fix the schema drift on orders?" → hands off to `tuning-incremental-sync-config`
- "Want to disable the billing-capped schemas?" → one-click via `external-data-schemas-partial-update`

Never start applying fixes autonomously from an audit — the audit's job is to report and recommend, not remediate.
Any fix should be confirmed explicitly before executing.

## Important notes

- **The audit is read-only.** Never call destructive tools from the audit flow. Hand off to the diagnosis/tuning
  skills — which in turn confirm before acting.
- **Empty = healthy.** Don't pad an empty audit with hypothetical issues. "No source issues found" is a good answer.
- **Source failures cascade.** When reporting a source in Error, also mention which schemas under it are affected
  (or will be, once they try to sync again). The user needs to understand the blast radius.
- **Billing limits aren't technical problems.** Flag them but route to billing / quota discussion, not to a
  recovery action.
- **The health checks only surface active failures.** For staleness or abandoned sources you need to cross-check
  the list endpoints. Only do this when the user explicitly asks for a deeper audit.
- **Webhook health is separate from schema health.** The health checks don't know about webhook state.
  When a user's request mentions "real-time", "Stripe webhook", or "why is data hours behind on a webhook
  source", go straight to `webhook-info-retrieve` rather than inferring from schema status.
- **Materialized views and setup-health kinds are out of scope here.** They surface through the same health-issues
  tools but belong to other audits/products — route, don't diagnose.
