# Web analytics precomputation

PostHog web analytics has two parallel precomputation systems. They target the same problem (avoid scanning raw events on every dashboard load) but use different mechanisms and apply to different query shapes.

## The two systems

### v2 pre-aggregated tables

DAG-warmed ClickHouse tables (`web_pre_aggregated_stats`, `web_pre_aggregated_bounces`) that store hourly-rollup data computed in the background. Gated per-team by the `useWebAnalyticsPreAggregatedTables` modifier plus the `SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES` feature flag.

- **Owned by**: web analytics team
- **Population**: scheduled Dagster jobs in `products/web_analytics/dags/`
- **Coverage**: stats table queries, web overview (partial)
- **Adoption** (as of 2026-05): effectively zero — only one team has the modifier on in prod

### Lazy computation

The newer general-purpose framework at `products/analytics_platform/backend/lazy_computation/`. Computes precomputed buckets on first read, caches them in a dedicated CH table per query family, and serves subsequent reads from the cache. Gated per-org by the `web-analytics-precompute-toggle` PostHog feature flag (evaluated against the team's organization).

- **Owned by**: web analytics team, riding on the analytics_platform framework
- **Population**: synchronous, on first read miss; subsequent reads hit the cache
- **Coverage** (today): `web_overview_query` and the PATHS (`WebStatsBreakdown.PAGE` + `includeBounceRate`) tile of `web_stats_table_query`. See `posthog/hogql_queries/web_analytics/web_overview_lazy_precompute.py` and `web_stats_paths_lazy_precompute.py`
- **Adoption** (as of 2026-05): freshly enabled, org feature flag gates further rollout

## When to use which

Both systems can coexist. The runner tries each in order; if both miss or are disabled the runner falls through to a raw events scan.

| You want…                                                             | Use                                                 |
| --------------------------------------------------------------------- | --------------------------------------------------- |
| A new query family where the cache shape is bounded and stable        | lazy computation                                    |
| Coverage of an existing query family that v2 already handles          | v2 if a team already has v2 enabled; otherwise lazy |
| Per-team custom precompute logic (uncommon)                           | lazy computation                                    |
| Background warming on a schedule                                      | v2                                                  |
| First-read latency budget that includes a precompute cost (~1.3x raw) | lazy computation accepts this; v2 doesn't have it   |

## Lazy computation for web overview (current production path)

`WebOverviewQueryRunner._calculate` runs three checks in order:

1. **Lazy precompute** (`can_use_lazy_precompute` + `execute_lazy_precomputed_read`) — the path described below.
2. **v2 pre-agg** (`get_pre_aggregated_response`) — the legacy path; falls through unless the team modifier is on.
3. **Raw events scan** — the original path.

### Schema

`web_overview_preaggregated` (sharded by `sipHash64(job_id)`, partitioned by `toYYYYMMDD(expires_at)`, `ReplicatedReplacingMergeTree` with `computed_at` as the version column). Five aggregate state columns matching the runner's metric tuple:

- `uniq_users_state AggregateFunction(uniq, UUID)` — unique persons (HLL ~99%)
- `uniq_sessions_state AggregateFunction(uniq, String)` — unique sessions (HLL ~99%)
- `sum_pageviews_state AggregateFunction(sum, Int64)` — pageviews/screens
- `avg_duration_state AggregateFunction(avg, Float64)` — average session duration (seconds)
- `avg_bounce_state AggregateFunction(avg, Int64)` — bounce rate (0/1 per session)

Partition key on `expires_at` rather than `time_window_start` so `ttl_only_drop_parts=1` can drop expired parts atomically.

### Bucketing and timezones

Buckets are **UTC hourly**. The read converts the team's local request window to UTC and filters bucket boundaries on hour edges. This means:

- **Whole-hour-offset timezones** (UTC, PT, ET, JST, etc. — ~99% of teams) read exact-to-the-hour data.
- **Half-hour-offset timezones** (IST `+5:30`, Newfoundland `-3:30`, Nepal `+5:45`, Iran `+3:30`) cannot be served correctly by UTC hourly buckets — the `can_use_lazy_precompute` gate refuses them via `is_integer_timezone()`. They fall through to v2/raw.

### Sessions that straddle bucket boundaries

The framework chunks the precompute span into **daily UTC jobs**. Each job's INSERT scans `[time_window_min, time_window_max)` for events, groups by `session_id`, and emits one hourly bucket row per session, keyed on `toStartOfHour(min(session.$start_timestamp))`.

A session that starts at 23:30 UTC with an event at 00:15 UTC the next day spans two daily jobs. Without help, the first job would only see the 23:30 event and miscount that session's pageviews.

To fix this, the INSERT widens the event scan forward by `SESSION_FORWARD_PAD_MINUTES` (currently 24 h) past the job's `[time_window_min, time_window_max)` window. The `HAVING` clause keeps each session attributed to its actual start hour — over-scan adds INSERT cost but cannot produce duplicate rows in any bucket. Forward-only is sufficient because the HAVING keeps only sessions whose `min(session.$start_timestamp)` falls inside the window; every event of such a session has `timestamp >= time_window_min`, so backward scanning never picks anything that survives HAVING.

The 24 h pad matches the JS SDK's hard `SESSION_LENGTH_LIMIT` and covers effectively 100% of population sessions (measured p99 ≈ 79 min, with a long tail). Sessions exceeding 24 h are documented as undercounted on cross-boundary days. The long-term fix is to drive the INSERT from `raw_sessions` (bounded by the embedded UUIDv7 timestamp), which removes the pad entirely.

### Eligibility gate

`can_use_lazy_precompute(runner)` in `web_overview_lazy_precompute.py`. Refuses when any of:

- The `web-analytics-precompute-toggle` PostHog feature flag is off for the team's organization
- Team timezone has a non-whole-hour UTC offset
- `query.conversionGoal` is set
- `query.sampling.enabled` is True
- `query.modifiers.sessionsV2JoinMode == "uuid"` (column type mismatch — temporary; should be re-enabled by re-typing `uniq_sessions_state` to `(uniq, UUID)`)
- `query.properties` contains more than one filter
- The single filter is not `EventPropertyFilter(key="$host", operator="exact", value=<non-empty string>)`
- Date range exceeds `MAX_PRECOMPUTE_DAYS` (90)
- Either date_from or date_to is None

When the gate returns False the runner silently falls through to v2 / raw. **Today there is no telemetry on gate rejections** — operators tuning the rollout have to read the source to know why a team isn't seeing the lazy path. A `web_overview_lazy_gate_rejected_total{reason}` counter would close that gap (open issue).

### TTL schedule

Different freshness per how recent the data is:

| Window    | TTL    | Rationale                                       |
| --------- | ------ | ----------------------------------------------- |
| Today     | 15 min | Dashboard refresh feels current                 |
| Yesterday | 1 hr   | Recently-stabilized data, occasional re-compute |
| Last 7d   | 1 day  | Stable enough that hourly recompute is wasteful |
| Older     | 7 days | Functionally static                             |

Stored via the `LAZY_TTL_SECONDS` dict; consumed by `lazy_computation_executor.parse_ttl_schedule` against the team's timezone.

### Read path

The read is a single `sync_execute` call (not HogQL — see "Why bypass HogQL" below). It computes the 5 metric pairs (current + previous period) via `*MergeIf` aggregates filtered by the team-tz date range converted to UTC. Settings:

- `load_balancing="in_order"` — paired with the INSERT side's same setting for read-your-writes via Approach E in [CONSISTENCY.md](../../products/analytics_platform/backend/lazy_computation/CONSISTENCY.md).
- `optimize_skip_unused_shards=1` — `job_id IN (...)` + sharding-by-`sipHash64(job_id)` lets ClickHouse prune to the right shards.

Result is built into the standard `WebOverviewQueryResponse` via `_build_response_from_row`, with `usedPreAggregatedTables=True`.

#### Why bypass HogQL

HogQL `HogQLGlobalSettings` is `extra="forbid"`, so we couldn't get arbitrary CH settings (originally `select_sequential_consistency=1`, since dropped) through `execute_hogql_query`. The read query shape is stable enough that `sync_execute` with parameterized values is appropriate. The team_id WHERE clause is enforced manually (the HogQL printer's auto-injected `team_id_guard_for_table` is not applied for sync_execute).

If we later move back to HogQL (after the consistency story is settled), the HogQL table registration at `posthog/hogql/database/schema/web_overview_preaggregated.py` is still present and ready.

### Observability

- **Read query**: tagged `query_type="web_overview_lazy_query"` in `system.query_log.log_comment`.
- **INSERT query**: tagged `query_type="web_overview_lazy_insert"` (via the framework's `query_type` kwarg added in this commit family).
- **Failures**: `web_overview_lazy_precompute_failed_total{error_type}` Prometheus counter (bounded by Python exception class).
- **Cache warmer**: the DAG at `products/web_analytics/dags/cache_warming.py` recognizes both `web_overview_query` and `web_overview_lazy_query`.
- **Adoption / latency**: see [`evaluating-web-analytics-performance`](https://github.com/PostHog/posthog/blob/master/.agents/skills/) or query `system.query_log` directly.

### Known limitations / open issues

1. **No gate-rejection telemetry** — operators can't see why a team isn't seeing the lazy path. Counter pending.
2. **`error_type` Prometheus label is too coarse** — `ServerException` from CH could mean quorum / memory / schema. Should bucket by CH error code.
3. **UUID session mode rejected**, not handled. Re-typing `uniq_sessions_state` to `(uniq, UUID)` would lift this; tracked as a follow-up.
4. **Empty `*MergeIf` rows are treated as legitimate empty windows.** Empty `sync_execute` result on this query shape is almost always a driver/transport error rather than "no data"; should be treated as failure + fall through.
5. **HogQL `top_level_settings`** on `WebOverviewPreaggregatedTable` is currently unused (read bypasses HogQL); kept as a hook if we re-route through HogQL later.

## Adding lazy computation to another web analytics query family

Reference implementation: `posthog/hogql_queries/web_analytics/web_overview_lazy_precompute.py`.

Roughly:

1. **Schema** — new CH table under `posthog/clickhouse/preaggregation/`. ReplacingMergeTree with `(team_id, job_id, time_window_start)` ORDER BY, sharded by `sipHash64(job_id)`, partitioned by `toYYYYMMDD(expires_at)`. Register in `posthog/clickhouse/schema.py` test fixtures.
2. **Migration** — `posthog/clickhouse/migrations/0XXX_<name>.py`. Sharded + distributed CREATE on `NodeRole.DATA`.
3. **HogQL table** — `posthog/hogql/database/schema/<name>.py`. Register in `posthog/hogql/database/database.py`.
4. **`LazyComputationTable` enum** — add a value in `products/analytics_platform/backend/lazy_computation/lazy_computation_executor.py`.
5. **Insert query** — HogQL template using `{time_window_min}`/`{time_window_max}` placeholders. Add a session-boundary pad if the query has session-level joins.
6. **Read** — `sync_execute` with parameterized SQL, settings = `{"load_balancing": "in_order", "optimize_skip_unused_shards": 1}`. Filter by `team_id` AND `job_id IN (...)` in the WHERE clause.
7. **Runner integration** — add a `can_use_*` gate and an `execute_*_read` orchestrator; short-circuit in `_calculate` before the v2/raw fallthrough.
8. **Tests** — round-trip (lazy == raw) parameterized over team timezones, gate fallthrough for each disqualifying condition, half-hour-offset fallthrough, cache hit (second call doesn't create new jobs).
9. **Cache warmer** — add the new `query_type` to the warmer DAG's allowlist in `products/web_analytics/dags/cache_warming.py`.

Roadmap order in `~/notes/work/posthog/web-analytics/investigations/2026-05-19-lazy-computation-candidates.md`: `web_overview_query` (shipped), `stats_table_path_bounce_query` (shipped — this PR), `stats_table_main_query` (next), then `web_goals_query` deferred for custom-goal-definition complexity.

## Lazy computation for the PATHS tile

`WebStatsTableQueryRunner._calculate` adds a fourth check: lazy precompute first for the `WebStatsBreakdown.PAGE` + `includeBounceRate` combination only. Other breakdowns and other column combinations fall through to the existing v2/raw paths.

### Schema

`web_stats_paths_preaggregated` (sharded by `sipHash64(job_id)`, partitioned by `toYYYYMMDD(expires_at)`, ReplacingMergeTree with `computed_at` as the version column). One row per `(team_id, job_id, time_window_start, breakdown_value)`:

- `breakdown_value String` — pathname, optionally prefixed with `$host` when the query has `includeHost`.
- `uniq_users_state AggregateFunction(uniq, UUID)` — persons that touched this pathname.
- `sum_pageviews_state AggregateFunction(sum, Int64)` — pageview/screen events on this pathname.
- `avg_bounce_state AggregateFunction(avg, Nullable(Float64))` — `if(pathname == entry_pathname, is_bounce, NULL)` averaged across rows. `avg`'s null-skip semantics make this equivalent to "bounce rate of sessions that entered on this pathname" — matching the v2 `PATH_BOUNCE_QUERY` join semantic without a JOIN at read time.

The state is `Nullable(Float64)` so the `if(..., NULL)` expression in the INSERT round-trips into the column without an explicit `toNullable` coercion.

### Eligibility gate

`can_use_lazy_precompute(runner)` in `web_stats_paths_lazy_precompute.py`. Shares the common gate (`web_lazy_precompute_common.py`) with web overview — same org flag, same timezone / sampling / UUID-mode / filter rules. Adds PATHS-specific refusals:

- `query.breakdownBy != WebStatsBreakdown.PAGE`
- `query.includeBounceRate` is False (the lazy table is purpose-built for bounce-augmented paths)
- `query.includeAvgTimeOnPage` is True (not yet wired)
- `query.includeScrollDepth` is True (not yet wired)

### Read path

Single `sync_execute` over `web_stats_paths_preaggregated` with `uniqMergeIf` / `sumMergeIf` / `avgMergeIf` covering both current and previous periods. The runner builds the standard `WebStatsTableQueryResponse` (breakdown_value + visitor/views/bounce-rate tuples + ui_fill_fraction + cross_sell). Sorting, paging, and fill-fraction are computed in Python over the materialized result set, matching `PathBounceStrategy` defaults (visitors DESC, then breakdown_value ASC; `WebAnalyticsOrderByFields` overrides honored for VISITORS / VIEWS / BOUNCE_RATE).

### Known follow-ups

- INITIAL_PAGE + bounce (entry-pathname tab) is a different SQL shape — separate precompute table or shared one with an entry-only state column.
- `usedLazyPrecompute` is set on the response; the frontend's `PreAggregatedBadge` already keys off `usedPreAggregatedTables` so users see the badge without further wiring. Distinguishing lazy from v2 in the UI is a separate follow-up.

## Related code

- `posthog/hogql_queries/web_analytics/web_overview.py` — runner
- `posthog/hogql_queries/web_analytics/web_overview_lazy_precompute.py` — overview lazy path
- `posthog/hogql_queries/web_analytics/web_overview_pre_aggregated.py` — overview v2 path
- `posthog/hogql_queries/web_analytics/stats_table.py` — stats table runner
- `posthog/hogql_queries/web_analytics/web_stats_paths_lazy_precompute.py` — PATHS lazy path
- `posthog/hogql_queries/web_analytics/web_lazy_precompute_common.py` — shared eligibility gate + helpers
- `posthog/clickhouse/preaggregation/web_overview_preaggregated_sql.py` — overview schema
- `posthog/clickhouse/preaggregation/web_stats_paths_preaggregated_sql.py` — PATHS schema
- `products/analytics_platform/backend/lazy_computation/` — framework + CONSISTENCY.md + README
