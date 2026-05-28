# Web analytics precomputation

Two precompute systems coexist: **lazy computation** (on-read, growing — the path forward) and **v2 pre-aggregated tables** (DAG-warmed, legacy, low adoption). Web analytics runners try them in order: lazy → v2 → raw events scan.

## At a glance

Lazy precompute families on master:

| Family       | Read tag                      | Bucket        | Compare period | Sessions join? | Read mechanism  | Source                                                                                             |
| ------------ | ----------------------------- | ------------- | -------------- | -------------- | --------------- | -------------------------------------------------------------------------------------------------- |
| overview     | `web_overview_lazy_query`     | UTC hourly    | full           | yes (24h pad)  | `sync_execute`  | [`web_overview_lazy_precompute.py`](backend/hogql_queries/web_overview_lazy_precompute.py)         |
| stats        | `web_stats_lazy_query`        | UTC hourly    | capped         | yes (24h pad)  | HogQL paginator | [`web_stats_lazy_precompute.py`](backend/hogql_queries/web_stats_lazy_precompute.py)               |
| stats_paths  | `web_stats_paths_lazy_query`  | UTC hourly    | budget-aware   | yes (24h pad)  | `sync_execute`  | [`web_stats_paths_lazy_precompute.py`](backend/hogql_queries/web_stats_paths_lazy_precompute.py)   |
| vitals_paths | `web_vitals_paths_lazy_query` | team-tz daily | none           | no             | HogQL direct    | [`web_vitals_paths_lazy_precompute.py`](backend/hogql_queries/web_vitals_paths_lazy_precompute.py) |

Family-specific details (schema columns, INSERT template, breakdown allowlists, follow-ups) live in the source files. This doc is the orientation; the source files are the contract.

## How lazy precompute works

Every read computes a `query_hash` from the runner's INSERT template + its placeholders (filters, date range, breakdownBy, team timezone, family-specific shape inputs). The framework looks up `PreaggregationJob` rows matching `(team_id, query_hash, window)`. Hit: return the existing `job_id`s. Miss: run the INSERT to materialise aggregate state into the family's preagg table, then return the new `job_id`. The runner then reads metrics via `*MergeIf` aggregates filtered by `job_id IN (…)` and the request's period.

```mermaid
sequenceDiagram
    participant R as Query Runner
    participant G as Eligibility Gate
    participant F as lazy_computation framework
    participant CH as ClickHouse
    R->>G: can_use_lazy_precompute(runner)
    alt gate rejects
        G-->>R: False → fall through to v2/raw
    else gate accepts
        G-->>R: True
        R->>F: ensure_precomputed(team, insert_query, window, ttl, table)
        F->>F: hash insert_query + placeholders → query_hash
        F->>CH: SELECT PreaggregationJob WHERE query_hash=? AND covers window
        alt READY job exists
            CH-->>F: existing job_ids
        else miss or expired
            F->>CH: INSERT INTO &lt;family&gt;_preaggregated SELECT … (state aggregates)
            F->>F: create PreaggregationJob row, status=READY
            CH-->>F: new job_id
        end
        F-->>R: LazyComputationResult(job_ids, ready=True)
        R->>CH: SELECT *MergeIf(state_col, period_filter)<br/>WHERE team_id=? AND job_id IN (…)
        CH-->>R: aggregated rows
        R-->>R: build response, set usedPreAggregatedTables=True
    end
```

**TTL**, by window recency — older windows refresh less often:

| Window    | TTL    |
| --------- | ------ |
| Today     | 15 min |
| Yesterday | 1 hr   |
| Last 7d   | 1 day  |
| Older     | 7 days |

**Session attribution.** Every family that joins sessions buckets by **session start at UTC-hour granularity** via `toStartOfHour(min(session.$start_timestamp))`, with the outer `HAVING` keeping only sessions whose start hour falls in the job window. Cross-team materialisation reuse is the reason for UTC-hour over team-tz hour. Sessions that straddle a bucket boundary are absorbed by a 24h forward pad on the event scan — derivation lives in [`web_overview_lazy_precompute.py`](backend/hogql_queries/web_overview_lazy_precompute.py). `vitals_paths` is the exception: no session join, bucketed by team-tz day instead.

A lazy _read_ failure falls through to v2/raw rather than surfacing the error. A lazy _gate rejection_ short-circuits before any INSERT runs.

## Eligibility gate

`can_use_lazy_precompute(runner)` decides at request time. The full canonical list of refusal classes lives in [`web_analytics_lazy_precompute.py`](backend/hogql_queries/web_analytics_lazy_precompute.py) as `LazyPrecomputeIneligible` subclasses — class names are stable identifiers used by logs and metrics. Two categories:

**Correctness refusals.** Org rollout flag off, per-query opt-in missing, non-whole-hour timezone (unless the family opts out — vitals_paths does), `query.conversionGoal` set, `query.sampling.enabled`, `query.modifiers.sessionsV2JoinMode == "uuid"`, missing or >90-day date range. Each one would either produce wrong rows or blow the precompute footprint.

**Rollout refusals.** `query.properties` is either empty or one `EventPropertyFilter(key="$host", operator=EXACT)`. This is **not** a fundamental limit — it's a rollout-simplification cap. Each distinct filter shape becomes a distinct `query_hash`, so the per-team footprint is `filter_shape_count × bucket_count`. Capping at "≤1 `$host` EXACT" keeps that product tractable while we widen the org-flag rollout. A `system.query_log` survey ([skill](skills/evaluating-web-analytics-performance/SKILL.md)) confirmed `$host` is the dominant filter key in real traffic. Broader shapes are a follow-up once hit-rate data settles.

## v2 vs lazy: when to use what

| Scenario                                               | Use                                       |
| ------------------------------------------------------ | ----------------------------------------- |
| New query family, bounded and stable cache shape       | lazy                                      |
| Existing family that v2 already covers, team has v2 on | v2 (avoid double-warming); otherwise lazy |
| Background warming on a schedule                       | v2                                        |

Lazy accepts the ~1.3× first-read latency hit (the INSERT) in exchange for not running Dagster jobs. v2 doesn't have that hit but has writer/reader drift if the DAG falls behind.

## Adding a new family

1. **Schema** — new ClickHouse table under `posthog/clickhouse/preaggregation/`. `ReplicatedReplacingMergeTree(computed_at)`, ORDER BY `(team_id, job_id, time_window_start, …)`, sharded by `sipHash64(job_id)`, partitioned by `toYYYYMMDD(expires_at)`. Register in `posthog/clickhouse/schema.py` test fixtures.
2. **Migration** — `posthog/clickhouse/migrations/0XXX_<name>.py`, sharded + distributed CREATE.
3. **HogQL table** — register in `posthog/hogql/database/database.py`.
4. **`LazyComputationTable` enum** — add a value in `products/analytics_platform/backend/lazy_computation/lazy_computation_executor.py`.
5. **INSERT + READ** — HogQL templates using `{time_window_min}` / `{time_window_max}` placeholders. **Prefer `execute_hogql_query`** (or `runner.paginator.execute_hogql_query` for pagination) — the printer auto-injects `team_id_guard_for_table`, handles escaping, and respects modifiers. Drop to `sync_execute` only if HogQL provably can't express something. Apply the 24h forward pad if your INSERT joins sessions.
6. **Runner integration** — add `can_use_*` gate + `execute_*_read` orchestrator; short-circuit in `_calculate` before the v2/raw fall-through. Refuse any shape the precompute table can't represent — silent fall-through is the safe degradation.
7. **Tests** — round-trip (lazy == raw) over team timezones, gate fall-through per disqualifying condition, cache hit (second call doesn't create new jobs).
8. **Cache warmer** — add the `query_type` to the warmer DAG allowlist in `products/web_analytics/dags/cache_warming.py`.

## Operating it

- **Verify rollout / attribute slow tails**: the [`evaluating-web-analytics-performance`](skills/evaluating-web-analytics-performance/SKILL.md) skill is the playbook — slice `system.query_log` by `query_type` and `breakdown_by`.
- **Where things show up**:
  - Counters: `web_analytics_lazy_precompute_{rejected,fallback,success}_total{family, reason}` for gate outcomes; `<family>_lazy_precompute_failed_total{error_type}` for exceptions.
  - Structured logs: `<family>_lazy_precompute_<phase>` (`started` / `ensure_done` / `current_not_ready` / `previous_not_ready` / `completed` / `failed`).
  - Tags on reads/INSERTs: `query_type="<family>_lazy_query"` / `"<family>_lazy_insert"`.
- **Known limitations**:
  - `error_type` Prometheus label is too coarse (`ServerException` could mean quorum / memory / schema) — should bucket by ClickHouse error code.
  - The explicit `sessionsV2JoinMode == "uuid"` refusal is defensive against a `uniqState(String)` ↔ `uniqState(UUID)` mismatch on the overview column. Rare in prod (queries arrive without `modifiers.sessionsV2JoinMode` set; the default is applied during compilation, after the gate). Re-typing `uniq_sessions_state` to `(uniq, UUID)` removes the gate entirely.
  - Half-hour-offset timezones (IST, Newfoundland, Nepal, Iran) are gated out except on `vitals_paths`. Lifting this requires sub-hour buckets across the other families.

## Related code

- [`products/web_analytics/backend/hogql_queries/`](backend/hogql_queries/) — runners + lazy modules per family
- [`products/analytics_platform/backend/lazy_computation/`](../analytics_platform/backend/lazy_computation/) — `ensure_precomputed`, `LazyComputationResult`, `LazyComputationTable`; see `CONSISTENCY.md` for read-your-writes
- [`posthog/clickhouse/preaggregation/`](../../posthog/clickhouse/preaggregation/) — schema DDL per family
- [`products/web_analytics/dags/cache_warming.py`](dags/cache_warming.py) — warmer DAG allowlist
- [`skills/evaluating-web-analytics-performance/SKILL.md`](skills/evaluating-web-analytics-performance/SKILL.md) — query-log playbook
