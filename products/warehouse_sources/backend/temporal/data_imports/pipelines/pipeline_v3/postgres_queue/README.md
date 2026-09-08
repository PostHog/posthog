# Postgres queue for warehouse batch loading

## Problem statement

The Kafka-based consumer for warehouse sources load worked but was fragile. Because a single load could run long, we had to keep pushing max.poll.interval.ms higher (along with session timeouts and max.poll.records) just to stop the broker from evicting consumers mid-batch, every increase was a bandaid, not a fix. On top of that, most of the real logic lived outside the message: retry state in Redis, DLQ routing through a second producer, schema-level locks and progress tracking in yet another store. The message itself was barely more than a pointer; Kafka was carrying the notification while everything that actually mattered happened elsewhere. Every configuration knob we added was compensating for a mismatch between what Kafka gives you and what we actually need.

The v3 Kafka transport is not a fallback: it was deleted outright in [#77651](https://github.com/PostHog/posthog/pull/77651).
This queue is the only load path for v3.

## RudderStack's approach

RudderStack has been running warehouse loading on Postgres queues for 6+ years, handling 100K events/second at peak.
Their design uses two tables per queue (a jobs table and an append-only status table) which avoids UPDATE contention and keeps the write path insert-only.
They partition jobs into datasets of ~100K rows each, use COPY for bulk inserts, and run a compaction process to consolidate completed datasets.

You can find more on:

- [Why RudderStack Used Postgres Over Kafka](https://www.rudderstack.com/blog/why-rudderstack-used-postgres-over-apache-kafka-for-streaming-engine/)
- [Kafka vs PostgreSQL: Implementing Our Queueing System](https://www.rudderstack.com/blog/kafka-vs-postgresql-implementing-our-queueing-system-using-postgresql/)
- [Scaling Postgres Queues to 100K Events](https://www.rudderstack.com/blog/scaling-postgres-queue/)

## Our solution

We took RudderStack's two-table model (jobs + append-only status) but kept things simpler (for now, at least).
All SQL lives in `jobs_db.py`; the polling/retry/recovery engine is `../batch_consumer.py` and the Delta-sink adapter is `consumer.py`.

### What we use

- **Two tables, with state denormalized onto the jobs row**: `sourcebatch` (the jobs) and `sourcebatchstatus` (append-only status log).
  Every status write is a single-statement dual write (`build_status_dual_write_sql`): insert the status row, then mirror `latest_state`, `latest_attempt` and `state_changed_at` onto the batch row.
  Migration `0006_sourcebatch_latest_state` added those columns plus the partial indexes `sb_claimable_idx`, `sb_run_gate_idx` and `sb_schema_busy_idx`; `0008_sourcebatch_superseded` added `superseded` and `sb_failed_changed_idx`.
  Migrations live in `products/warehouse_sources_queue/backend/migrations/`.
  The `DISTINCT ON` view `v_latest_source_batch_status` still exists (created in `0001_initial`), but no query path reads it any more: the claim query and every sweep run off the denormalized columns, and per-batch latest-status lookups use a lateral `LIMIT 1` probe (`latest_status_lateral`).
  The view is only useful for ad-hoc SQL when debugging by hand.
- **Group leases** for cross-pod coordination: a row in `sourcegrouplease` keyed by `(team_id, schema_id)`, with a 300s TTL (`LEASE_TTL_SECONDS`).
  A lease is claimed via a conditional upsert inside the claim query, renewed by the consumer heartbeat, and reclaimable by any pod once it expires.
  This replaced the original session-level `pg_try_advisory_lock(namespace, hashtext(team_id:schema_id))` design: advisory-lock ownership is tied to a live server session, so it could be orphaned indefinitely on SIGKILL, pgbouncer session lingering, or node loss, wedging the whole loader fleet.
  An abandoned lease simply expires instead (see the `jobs_db.py` module docstring).
- **Claim-or-renew in one statement**: `get_unprocessed_and_lock` selects narrow claim candidates from the denormalized columns (with per-team round-robin fairness, head-of-line gating per run, a failed-run gate, and a schema-busy gate), then claims or renews the group leases for the winners inside a single writable CTE.
  The candidate CTE is `MATERIALIZED` so its `LIMIT` fully resolves before the lease upsert runs, and candidate groups are deduplicated because `INSERT ... ON CONFLICT DO UPDATE` cannot touch the same lease row twice in one statement.
  (The old README's `MATERIALIZED` rationale, preventing `pg_try_advisory_lock` from acquiring phantom locks in a `WHERE` clause, no longer applies: there are no advisory locks.)
- **Async consumer**: single asyncio process that polls every ~2s, groups batches by `(team_id, schema_id)`, processes groups concurrently, batches within a group sequentially.
  Each batch renews the lease on entry, heartbeats it (and re-inserts `executing` status) during processing, and verifies ownership before writing `succeeded`.
- **Three sweeps**, not one:
  - **Recovery sweep** (every 30s, `get_stale_executing`): batches whose latest status is `executing`, older than the 300s grace window, with no live lease over their group.
    The sweep deletes the expired lease first so a resurrecting owner cannot renew it, then re-queues the batch as `waiting_retry` (with a compare-and-swap on the observed `state_changed_at`) or fails the run at max attempts.
  - **Reconcile sweep** (every 300s, `reconcile_failed_runs` + `get_failed_runs`): finds runs with a `failed` queue batch whose `ExternalDataJob` was left non-terminal and marks the job failed.
    It is single-flighted fleet-wide through a sentinel lease row (`try_acquire_reconcile_sweep_slot`, team_id 0 / `__reconcile-sweep__`, 240s slot TTL): the sweeps reconcile global state, so N pods running them concurrently is pure duplicated load, exactly when the queue DB can least afford it.
  - **Stranded-run sweep** (same cadence and connection, `get_stale_stranded_runs`): runs the loader abandoned, meaning non-terminal batches, no live lease, and no loader progress for 6 hours.
    These have no `failed` batch for the reconcile sweep to key on (the extraction died before a final batch), so without this pass they would strand until the retention prune.
- **Sync producer** (`producer.py`): runs inside Temporal activities, plain `psycopg.Connection` with autocommit. Each `send_batch_notification` is a single INSERT.
- **New DB**: we created a new DB to store these tables.
- **Daily range partitioning** on `created_at`: both tables use `PARTITION BY RANGE (created_at)` with daily partitions and a DEFAULT partition catching rows that miss one.
  A Temporal scheduled workflow (`warehouse-sources-queue-partition-management`, daily at 8 AM UTC) creates the next 7 days of partitions, drops partitions older than 7 days, and prunes the matching S3 extraction prefixes on the same retention.
  `DROP TABLE partition` is O(1) metadata-only: no vacuum, no dead tuples.
- **Claim eligibility coupled to retention**: a batch is only claimable (or recovery-sweepable) while younger than `CLAIM_ELIGIBILITY_INTERVAL` (`6 days 12 hours`, `jobs_db.py`), which must stay below the 7-day retention window (`RETENTION_DAYS` in `posthog/temporal/warehouse_sources_queue_partition_management/activities.py`).
  Otherwise a claimed batch's extraction parquet may already be deleted from S3 when the loader reads it.
  `test_eligibility_window_stays_below_retention_window` in `test_jobs_db.py` enforces the coupling.
- **Partition pruning bounds**: consumer queries include `created_at > now() - interval '14 days'` (2x the retention) so the planner can skip dropped partitions.

### Query cost scales with the answer, not with history

The old claim "our poll query is cheap enough with proper indexing" did not survive contact with a production backlog.
Three changes in August 2026 restructured the hot queries after a production loader stall:

- [#82765](https://github.com/PostHog/posthog/pull/82765): the claim query's fairness sort ran over full-width rows (~1 KB of `metadata` each), so a backlog made every poll sort megabytes to keep ~50 rows, spilling past `work_mem` to disk. Candidates are now narrow `(id, created_at)` pairs, joined back only for the LIMIT winners.
- [#83022](https://github.com/PostHog/posthog/pull/83022): the failed-run reconcile ran a per-batch latest-status probe for every failed batch in the lookback window, so a failure storm made each sweep take minutes. It now picks winners from the denormalized columns and probes status only for the LIMIT winners.
- [#83067](https://github.com/PostHog/posthog/pull/83067): the stranded-run sweep gated raw batch rows, which the planner turned into a hash anti-join over every retained failed batch. It now aggregates into candidate runs first, so each gate is one index probe per run.

The shared lesson: every query on these tables must scale with the size of its answer (the claimable set, the candidate runs), never with retained failure history, because failure history is largest exactly when the fleet is least healthy.
The `jobs_db.py` docstrings on `_state_claim_candidates_sql`, `get_failed_runs` and `_stranded_candidate_runs_sql` carry the details, and plan-shape tests in `test_jobs_db.py` pin the query shapes.

### Adding a `sourcebatch` index

Never create a new index directly on the partitioned parent in one shot: a plain `CREATE INDEX` there recurses into every partition under a lock that blocks the claim path for the length of the build, and `CREATE INDEX CONCURRENTLY` is not supported on a partitioned parent.
The required pattern, established with `0008_sourcebatch_superseded` (read it as the reference implementation): create the parent index with `ON ONLY` (metadata only, invalid), build a matching index on each partition with `CREATE INDEX CONCURRENTLY`, then `ALTER INDEX ... ATTACH PARTITION` each one; attaching the last partition flips the parent index valid.
The migration must be `atomic = False` and re-runnable (a cancelled `CONCURRENTLY` build leaves an invalid index that must be dropped and rebuilt).

### What we left out

- **COPY bulk inserts**: the producer inserts one row per batch. At our volume, row-level INSERT is fine. (We can always move to bulk insert if needed)
- **Compaction**: RudderStack runs a background process to merge/drop completed datasets, it stores tables up to 100k rows and then they roll to the next one. We don't need it at the moment, but if we end up implementing rolling datasets, we will implement this compaction too.
- **Caching layers**: RudderStack uses "no jobs" caches and active pipeline caches to reduce query load. We have not needed them, but only because the claim path was restructured to run off partial indexes and denormalized state (see above); "proper indexing" alone was not enough.
- **Recursive CTE loose index scans**: their trick for finding distinct pipeline IDs efficiently. Our claim query gets the same effect from the partial indexes.
- **Active Partitions**: RudderStack designs a partition and then it assigns each partition to one processor instance, this is similar to how Kafka partitions work. We don't need this, this will be an overkill as we don't have any specifics for a partition.

### Architecture

![Postgres queue architecture](./20260423%20-%20PostgresArchitecture.png)

This diagram predates the lease model: it shows `pg_try_advisory_lock` coordination, `SELECT ... FOR UPDATE SKIP LOCKED`, and status UPDATEs, none of which exist any more.
The overall topology (Temporal producer activity, two tables, a fleet of consumer pods polling in a loop) is still right; read the "What we use" section above for the current coordination design.

## Metrics and health signals

The consumer engine emits nine `warehouse_pg_consumer_*` metrics (`metrics.py`): `batches_processed_total`, `batch_processing_duration_seconds`, `batch_retry_total`, `runs_failed_total`, `poll_duration_seconds`, `poll_batches_fetched`, `poll_failures_total`, `active_groups`, `recovery_sweeps_total`.
Other sinks get that nine-metric engine set under their own `{prefix}_pg_consumer_*` names via `make_consumer_metrics`, so dashboards and KEDA queries never conflate two consumers' series.
Two further counters exist only under the `warehouse_pg_consumer_*` prefix, incremented by the Delta consumer's reconcile sweep (`consumer.py`) rather than by the shared engine: `runs_reconciled_total` and `runs_terminalized_stale_total`.

The headline health signal is `warehouse_pg_queue_oldest_unclaimed_batch_seconds`: the age of the oldest batch no consumer has picked up yet.
It is the loader's data-freshness signal and rises whenever loading stalls, regardless of cause, so its alert fires even when every other signal looks green.
Its depth companion `warehouse_pg_queue_claimable_batches` says how much work sits behind that head; a stall and a burst look identical on age alone.
Every pod reports the same queue-wide values on the reconcile cadence; aggregate both gauges with `max()`.
Failed polls record their elapsed time in `poll_duration_seconds`, so degraded polls stay visible in the latency percentiles; `poll_failures_total` carries the reason label and is the alertable poll-health counter.
The maintenance queries (sweeps, reconcile passes, probes) report through `warehouse_pg_queue_query_duration_seconds` (labeled per query, observed on failure and timeout too) and `warehouse_pg_queue_query_failures_total`; the August 2026 stall came from a query with no latency signal at all.

For ad-hoc inspection (state summaries, active runs, leases, force-release), use the `manage_warehouse_queue` management command.

## Things to look out for

- **Partition health**: monitor that the `warehouse-sources-queue-partition-management` Temporal schedule is running. Alert on rows landing in DEFAULT partitions (means partition creation failed).
- **Poll duration vs lease TTL**: leases are claimed when the poll query starts, so a poll slower than half the 300s TTL hands groups over mostly expired; the consumer logs `poll_duration_approaching_lease_ttl` when this starts happening.
