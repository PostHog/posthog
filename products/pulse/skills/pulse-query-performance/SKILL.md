---
name: pulse-query-performance
description: >
  Playbook for a pulse mission analyzing ClickHouse query performance for one team.
  Finds slow-query regressions, materialization candidates, and OOM/timeout clusters
  in query_log_archive via the query-performance-execute-sql MCP tool, and reports
  them as pulse brief sections and opportunities.
---

# Pulse query-performance mission

You analyze query performance for the team named in your mission bundle, over the frozen window it pins.
Your ONLY access to query logs is the `query-performance-execute-sql` MCP tool: read-only ClickHouse SQL, capped at 10000 rows and 60 seconds per query.
Use the standard PostHog MCP tools only to resolve the team's own resources (insights, dashboards) that a finding points at.

## Data source rules

- Query `query_log_archive`; do not try `system.query_log` (hours of retention only).
- ALWAYS filter `is_initial_query = 1` — distributed sub-queries double-count otherwise.
- ALWAYS filter `team_id = <team_id from the mission bundle>` — this mission is per-team.
- Constrain `event_time` to the mission window. Before trusting any window-over-window comparison, run a per-day `count()` to confirm retention actually covers both windows.
- Useful typed columns (no JSONExtract needed): `lc_kind` (request/celery/temporal/...), `lc_product`, `lc_access_method`, `lc_query__kind` (TrendsQuery, FunnelsQuery, HogQLQuery, ...), `lc_dashboard_id`, `lc_insight_id`, plus `query`, `query_duration_ms`, `read_rows`, `read_bytes`, `memory_usage`, `exception_code`.
- A query is slow when `query_duration_ms > 30000 OR exception_code IN (159, 160, 241)`. Do NOT filter `type = 'QueryFinish'`: OOM and timeout rows are exception rows and that filter silently drops every failure.

## Playbook

Work coarse to specific; each step's output decides whether the next is worth running.

1. **Baseline.** p50/p95/p99 `query_duration_ms`, query count, and total `read_bytes` per `lc_query__kind` for the mission window, and the same for the preceding window of equal length.
2. **Regressions.** Kinds or specific insights (`lc_insight_id`) whose p95 moved > 50% window-over-window on meaningful volume. Correlate the onset date with the team's own changes (new insights, dashboards, experiments) via the PostHog MCP tools.
3. **Cost heads.** Top 10 query shapes by summed `read_bytes` and by summed `query_duration_ms`. Flag JSONExtract over `person_properties`/`properties` in the query text (materialization candidates) and high-cardinality `breakdown` usage.
4. **Failures.** Group `exception_code != 0` by code and `lc_query__kind`. OOM (241) and timeout (159, 160) clusters are opportunities, not noise; pull one full `query` text per cluster as the example.
5. **Verify.** For each finding you keep, compute the supporting numbers yourself: window-over-window deltas, and enough volume that the delta is not one outlier query. Do not eyeball.

## Reporting

Report findings through the standard pulse output contract (the mission prompt defines the JSON shape and path).

- Sections: use kind `what_happened` for regressions and failure clusters, `what_to_build_next` for materialization candidates and query rewrites.
- Opportunities: kind `fix` for regressions and failure clusters, `build` for materialization or query-shape improvements. Every opportunity carries `evidence_refs` naming the query_id or insight/dashboard it came from, and a `confidence` you can defend.
- Every number cites the window it came from.
- **Say less.** Drop anything you cannot support with a query you actually ran. A quiet window is a valid result: report empty sections and zero opportunities rather than padding.
