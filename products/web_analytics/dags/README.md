# Web analytics cache warming

Hourly Dagster job (`web_analytics_cache_warming_job`) that keeps web analytics
precompute buckets and result caches fresh for the fleet's hot query shapes.
Selection scans `system.query_log` for shapes real users ran, groups them by
normalized shape, and replays a representative per shape through the production
query runners.

## Architecture

`get_warmable_queries_op` (fleet-wide selection, cached in object storage)
→ `warm_queries_op` (the split: scopes the selection and fans it into
team-disjoint shards) → mapped `warm_queries_shard_op` per shard.

Each shard runs as its own subprocess under the multiprocess executor. HogQL
compilation is CPU-bound Python, so parallelism comes from shard processes, not
threads; threads inside a shard overlap the IO-bound parts (ClickHouse reads
and inserts, cache lookups). Sharding is by `team_id % shards`, which keeps
every potential duplicate `(team, cache_key)` inside one shard so per-shard
dedupe needs no coordination. The run pod requests 6 CPUs / 12Gi via the
`dagster-k8s/config` tag on the job — the ceiling the 8-core dagster nodes can
actually schedule (~7.9 allocatable), so the default 8 shards deliberately
oversubscribe CPU slightly; that's fine because shards idle during their
IO-bound stretches. Don't size shards one-to-one with cores.

## Live-tunable settings (instance settings, no redeploy)

| Setting                                       | Default | Meaning                                                                                                                                                            |
| --------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `WEB_ANALYTICS_WARMING_SHARDS`                | 8       | Shard subprocesses per run (clamp 1-16). Real CPU parallelism is capped by the pod's 6-CPU request (the node-schedulable ceiling), so shards beyond ~8 add little. |
| `WEB_ANALYTICS_WARMING_SHARD_THREADS`         | 6       | Worker threads inside each shard (clamp 1-64). Total ClickHouse-side concurrency ≈ shards × this.                                                                  |
| `WEB_ANALYTICS_WARMING_DAYS`                  | 14      | query_log lookback for demand selection.                                                                                                                           |
| `WEB_ANALYTICS_WARMING_MIN_QUERY_COUNT`       | 2       | Per-shape demand floor for selection.                                                                                                                              |
| `WEB_ANALYTICS_WARMING_MAX_SHAPES`            | 400000  | Fleet-wide selection cap.                                                                                                                                          |
| `WEB_ANALYTICS_WARMING_SELECTION_TTL_SECONDS` | 21600   | Selection cache TTL (the expensive fleet scan re-runs on this cadence).                                                                                            |

Settings are read at run start; changes apply to the next run.

## Targeted runs (Launchpad)

Config binds under `ops.warm_queries_op.config`:

```yaml
ops:
  warm_queries_op:
    config:
      mode: backfill # full (default) | refresh | backfill
      team_ids: [] # optional scoping
      limit: 0 # hottest-first cap; bound manual backfills
```

- `full`: everything selected — skip fresh, refresh stale, cold-build the rest.
- `refresh`: only shapes already warmed once (cache entry exists) — cheap freshness pass.
- `backfill`: only never-warmed shapes — coverage expansion without re-touching the warm set.

Launches share a concurrent-run guard with the hourly schedule, so bound manual
backfills with `limit`.

## Observability

- Per-shape log line (`web_analytics_warming_shape`): outcome, duration, team,
  kind, breakdown, requested and replayed date range. Slow shapes (≥15s full
  wall-clock) escalate to WARNING.
- Per-shard heartbeat every ~2 minutes: progress, rate, ETA, outcome breakdown.
- Prometheus: `posthog_web_analytics_warming_queries_total{outcome=...}`,
  `posthog_web_analytics_warming_shapes_selected`.
