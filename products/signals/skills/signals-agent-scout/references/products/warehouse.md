# Lens: data warehouse

Warehouse signals don't show up in `top_events` — warehouse rows land in tables,
not events. The profile's `external_data_sources` section is the entry point:
each entry carries `source_type`, `status`, `prefix`, and connection metadata.
Pair that with `popular_insights` and `recent_dashboards` to see whether a
broken source is actually load-bearing for the team's analytics.

## Quick scan from the profile alone

Look at `external_data_sources`:

| Pattern                                                                  | What it usually means                          |
| ------------------------------------------------------------------------ | ---------------------------------------------- |
| `status = failed` on a recently-connected source                         | Setup-time misconfig — high-intent, real user  |
| `status = failed` on a long-running source that was healthy              | Drift / credential expiry / schema change      |
| `status = running` for hours past its expected window                    | Stuck sync — worth a closer look               |
| `status = cancelled` repeatedly                                          | Source is fighting itself or a downstream gate |
| Source's `prefix` referenced in `popular_insights` and currently failing | Outage with downstream impact — escalate       |
| Source `status = paused`                                                 | Almost always intentional — skip               |

If `external_data_sources` is empty or every entry is healthy, warehouse is
probably not where the signal is today. Move on.

## Patterns to look for

### Failed sync with downstream impact

A source with `status = failed` whose `prefix` shows up in `popular_insights` or
in a `recent_dashboards` query. The blast radius is real — every dashboard view
since the failure is reading stale or partial data.

1. `external-data-sources-retrieve` for the source's last error and recovery
   action.
2. `external-data-sync-logs` for the failure history — one-off vs recurring.
3. `execute-sql` against `system.insights` filtered to the source's prefix to
   confirm which charts depend on it (`name ILIKE '%<prefix>%' OR query::text
ILIKE '%<prefix>%'`).
4. Cross-check `existing_inbox_reports` — if the failure already has a report
   open, this is dedupe territory, not a fresh emit.

### Stuck running

A source's `status = running` for far longer than its typical window. Often a
silently-hung worker, a schema-discovery loop, or a CDC source whose WAL slot
has stalled. Symptom: downstream insights start showing a rising recency gap
without an explicit error.

`external-data-sync-logs` will show the last successful sync timestamp; if it's
older than the source's natural cadence, surface it.

### Schema drift

`external-data-schemas-list` for a source where the upstream renamed/dropped a
column the project depends on. Symptoms: most schemas healthy, one or two
schemas in `error` state with a column-mismatch message; or `popular_insights`
that previously rendered now returning empty buckets after the drift.

### Health-issue overlap

`data-warehouse-data-health-issues-retrieve` exposes the platform's own
health-issue stream. If a recent issue overlaps with a source the team actually
uses (cross-check with `popular_insights` / `recent_dashboards`), that's a
high-confidence finding — the platform already detected it; the scout's job is
to surface it to this team's inbox.

### Materialized view downstream

`view-list` for views materialized off warehouse tables. If a popular view's
underlying source is failing, the view returns stale data with no error. Pair
view recency (`view-run-history`) with `external_data_sources` status.

## Disqualifiers (skip these)

- **Source `status = paused`** — almost always intentional. Confirm with
  memory; if no entry exists, write one and skip.
- **Old prefix the team is migrating away from** — the new prefix takes the
  load, the legacy prefix's failures are expected. Memory entries from prior
  runs should already say so.
- **Manual one-shot reloads** — `external-data-schemas-reload` triggered by
  hand. Sync-log entries with isolated timestamps and no recurrence.
- **Single-shot setup failures during onboarding** — high noise on a freshly-
  connected source where the team is still iterating on credentials. Wait one
  run before emitting unless the failure is severe.

When in doubt, write a memory entry instead of emitting.

## MCP tools

- `external-data-sources-list` — start here. Filter by `status` ∈ {failed,
  running, cancelled} for the active set worth investigating.
- `external-data-sources-retrieve` — drill into a single source for the latest
  error message, last successful sync, and recovery actions.
- `external-data-schemas-list` — per-source schema health (which tables are
  syncing, which are erroring).
- `external-data-sync-logs` — failure history, run cadence, individual run
  durations.
- `data-warehouse-data-health-issues-retrieve` — platform-detected health
  issues.
- `view-list` / `view-run-history` — materialized views built off warehouse
  tables; their staleness is downstream blast radius.
- `read-data-warehouse-schema` — what's actually in the warehouse if you need
  to verify a column or row shape during investigation.
- `inbox-reports-list` — check whether the failing source already has a report
  before emitting; pre-existing inbox coverage is a strong skip signal.

For deep investigation playbooks, the sandbox image bakes
`posthog:diagnosing-failed-warehouse-syncs` (per-source failure recovery) and
`posthog:auditing-warehouse-data-health` (broad audit across all sources).
`posthog:tuning-incremental-sync-config` covers cases where the failure is
sync-type / incremental-field misconfig.

## Memory shapes worth writing

After investigating warehouse on a project, leave durable steers like:

- _"`stripe-charges` syncs weekdays only — Sunday gaps are not a stall."_
  (`pattern`, `domain:warehouse`, `entity:stripe-charges`)
- _"Prefix `legacy_pg_`is migrating to`prod*pg*`; failures on the legacy
source are expected through 2026-06."_ (`addressed`, `domain:warehouse`,
`entity:legacy*pg*`)
- _"View `lifetime_revenue` powers the LTV dashboard (id 42); flag warehouse
  sources feeding it as priority."_ (`pattern`, `domain:warehouse`,
  `entity:lifetime_revenue`)
- _"Source `hubspot_main` typically fails 1-2x/week on transient credential
  refresh — auto-recovers within an hour. Don't surface unless it's down for >
  6 hours."_ (`noise`, `domain:warehouse`, `entity:hubspot_main`)

These compound: by run #5, the scout knows which sources are load-bearing,
which failures are intentional, and which gaps the team has already addressed.
