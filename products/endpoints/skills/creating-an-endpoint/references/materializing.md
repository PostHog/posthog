# Materialising an endpoint

Materialisation pre-computes an endpoint's query into a saved view that's refreshed on a schedule.
Reads become near-instant but the data is as stale as the refresh interval. This reference is the
detailed flow behind step 6 of `creating-an-endpoint` and the step 2 decision in
`diagnosing-endpoint-performance`.

## When materialisation is the right call

| Signal                                                       | Means                                                                |
| ------------------------------------------------------------ | -------------------------------------------------------------------- |
| Endpoint is called more than ~10 times per minute, sustained | Reads will dominate cost — pre-computing saves a lot                 |
| Query takes more than ~1s of ClickHouse time inline          | Latency on the read path matters; materialisation collapses it       |
| Callers can tolerate 5-15 minute staleness                   | The refresh interval becomes the freshness floor                     |
| Variables are bounded — small known set of values            | Bucket overrides become tractable; the materialised view stays small |

If two or more of these apply, materialise. If none apply, don't.

## When materialisation is wrong

- **Real-time data requirement.** Anything that drives a "live" UI element where users notice
  10-minute lag.
- **High-cardinality variables.** If callers pass arbitrary `user_id` values, each materialised
  bucket is tiny and the refresh churn outweighs the read savings.
- **Low-traffic endpoint.** If it's called once a day, the materialisation refresh costs more
  than the inline reads would.
- **Cohort breakdowns or compare mode (insight endpoints).** Regular property breakdowns
  materialise fine; only cohort breakdowns and compare mode are rejected. Use
  `endpoints-materialization-preview` to confirm.
- **Query reads `now()` / `today()` directly.** Replace with a variable; otherwise the
  materialised result is anchored to the refresh time, not the call time.

## Eligibility rules

Eligibility is enforced server-side (and surfaced by `endpoints-materialization-preview`). Common
rejection reasons:

| Reason                                         | What it means                                                                                                                                                               | Fix                                                                                           |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `Cohort breakdowns are not supported`          | Cohort breakdowns produce a UNION ALL the transform can't tag by series                                                                                                     | Use a property breakdown, or split into separate endpoints, one per cohort                    |
| `Compare mode is not supported`                | Compare mode doubles the series, which the transform can't reconstruct                                                                                                      | Drop compare mode, or expose the comparison window as a variable                              |
| `Query has unresolved variables`               | A variable in the query has no default and the materialisation can't pick a value                                                                                           | Set defaults for all variables                                                                |
| `Query references non-deterministic functions` | `now()`, `today()`, `rand()` change between refresh runs                                                                                                                    | Replace with a `date_from` / `date_to` variable                                               |
| `CTE variables with JOINs … not supported`     | A variable filter combined with a top-level `JOIN` changes joined-row cardinality, silently producing wrong results (e.g. `LEFT JOIN` non-matches lose the variable column) | Filter inside a subquery/CTE, then join the result — don't apply the variable across the JOIN |
| `Query kind not supported`                     | Some query kinds (e.g. funnels) don't have a materialisation path yet                                                                                                       | Rewrite in HogQL                                                                              |

Always call `endpoints-materialization-preview` before enabling — it returns the exact
rejection reason if any, plus the transformed query so the user can sanity-check what will be
materialised.

## Variables become WHERE filters

When you call a materialised endpoint, the materialised view is queried with a
`WHERE` clause built from the variables you pass. This has two implications:

1. **All declared variables must be passed.** Calls missing any materialised variable are
   rejected. This is a security feature — it prevents callers from getting back the entire
   pre-aggregated dataset by omitting filters.
2. **The materialised view contains all rows across all variable combinations.** If your
   variables have N values each and there are M variables, the view's row count is roughly the
   product. Bound this by either:
   - Picking variables with small cardinality
   - Bucketing range/time variables with `bucket_overrides` (see below)

## Bucket overrides — making range variables materialisable

A continuous range variable — a timestamp or numeric filter like `WHERE timestamp >= {variables.since}`
— has effectively unlimited distinct values, so the view can't pre-compute every one.
`bucket_overrides` fixes this by pre-aggregating that column at a coarser grain and filtering at
read time. Pass a map of column → bucket function:

```json
{ "bucket_overrides": { "timestamp": "hour" } }
```

Supported functions: `minute`, `fifteen_minutes`, `hour`, `day`, `week`, `month` (each is a
`toStartOf…` rollup). Pick the **coarsest** bucket the caller can tolerate: `day` keeps the view
small and refreshes cheap; `minute` is large and expensive. The caller still passes their exact
value — the view just answers from the bucketed rollup. Run `endpoints-materialization-preview` to
see which range variables were detected and confirm the bucketing before you enable.

## Refresh schedule

The refresh interval determines staleness. Available intervals are tied to the data warehouse
saved query schedule — typically 5min, 15min, hourly, or daily. Pick the longest interval that
satisfies the user's SLA.

Materialisation status is tracked on the saved query (`DataWarehouseSavedQuery`) backing each
version. `endpoint-materialization-status` returns the last run time, status, and any error. If
it shows `Failed`, the inline path still works (the endpoint isn't broken — it's just slower
than expected), but the materialised data is stale.

## Per-version materialisation

Each endpoint version has its own materialised view, named `{endpoint_name}_v{version}`. When
you create a new version (by changing the query), the new version starts unmaterialised by
default. The old version's materialisation continues until you explicitly disable it via
`endpoint-update` with `version` and `is_materialized: false`.

This means a project can accumulate **unused materialised versions** — old versions of an
endpoint that nobody calls but are still being refreshed. The `auditing-endpoints` skill catches
this by reading per-version `last_executed_at` from `endpoint-versions`.

## Operational notes

- **Enabling materialisation is free to start.** No backfill — the first refresh kicks off the
  initial population. The endpoint stays callable inline during that time.
- **Disabling materialisation is reversible.** Set `is_materialized: false` and the
  materialised view is dropped on the next cleanup pass. Re-enabling re-creates it.
- **Storage costs add up.** Many materialised views with high-cardinality variables can dominate
  warehouse storage. When the user's project is hitting cost caps, materialisation cleanup is
  usually the first lever.
- **Materialisation failures don't block reads.** The endpoint stays callable inline if the
  refresh fails — the user gets stale data with longer latency, not an outright outage. Surface
  the failure but don't escalate it as a blocker unless freshness is critical.
