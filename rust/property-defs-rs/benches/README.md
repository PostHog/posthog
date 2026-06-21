# propdefs performance optimization loop

This directory holds the benchmark that is the **metric** for the propdefs optimization
loop, plus the spec for running the loop itself.

We optimize for two things, in priority order:

1. **Deduplication** — issue the fewest "not useful" DB writes per event. Concretely:
   maximize `dedup_ratio` / minimize `writes_per_1k_evt`, and drive
   `wasted_timestamp_writes` toward zero.
2. **Throughput** — process the most events/sec on the producer CPU path
   (`events_per_sec`).

## The benchmark

`pipeline.rs` is a `harness = false` bench (a plain `main`). It builds a deterministic,
seeded, realistic event stream entirely in memory — no Kafka, Postgres, or personhog — and
reports throughput and dedup numbers that are **identical across runs of the same code**,
so the loop can diff them directly.

```bash
# release build, full report
cargo bench -p property-defs-rs --bench pipeline

# machine-readable line for the loop driver
PROPDEFS_BENCH_JSON=1 cargo bench -p property-defs-rs --bench pipeline 2>/dev/null \
  | grep '^BENCH_JSON'
```

Tunables (env):

| var | default | meaning |
| --- | --- | --- |
| `PROPDEFS_BENCH_EVENTS` | 300000 | events generated |
| `PROPDEFS_BENCH_TEAMS` | 50 | distinct teams (Zipfian volume) |
| `PROPDEFS_BENCH_SEED` | 42 | RNG seed (determinism) |
| `PROPDEFS_BENCH_HOURS` | 6 | simulated hours for last_seen_at churn |
| `PROPDEFS_BENCH_CACHE_CAP` | 1000000 | per-subcache capacity (sweep eviction effects) |
| `PROPDEFS_BENCH_JSON` | unset | also print one `BENCH_JSON {...}` line |

### What each phase measures

- **Phase A — throughput.** `serde_json::from_str` + `Event::into_updates` over every event
  (the exact per-event producer CPU cost). Reports `events_per_sec`, `updates_per_sec`.
- **Phase B — dedup.** Replays every update through the producer-local compaction
  (`AHashSet`) + the real shared `Cache`. Reports `dedup_ratio`, `writes_per_1k_evt`, and
  the passed-write split by record type (`event_defs` / `event_props` / `prop_defs`).
- **Phase C — last_seen_at churn.** Replays event-definition updates across N simulated
  hours with the real key (`team, name, last_seen_at@hour`) vs a `(team, name)`-only
  counterfactual. The delta is `wasted_timestamp_writes` — the volume the
  "remove last_seen_at from event definition" change would eliminate.

### Metric definitions (the loop's objective)

```
dedup_ratio            = 1 - passed_total / updates_seen            # ↑ better
writes_per_1k_evt      = passed_total / (events / 1000)            # ↓ better
wasted_timestamp_writes= real_eventdef_writes - counterfactual     # ↓ better
events_per_sec         = events / parse_elapsed                    # ↑ better
```

## The loop

Each iteration:

1. **Measure baseline** — record `BENCH_JSON` for the current code (`baseline.json`).
2. **Pick one candidate** from the backlog (below). One change at a time.
3. **Implement** behind a flag/config where it changes production behavior.
4. **Re-measure** — same seed/size. Compare against baseline.
5. **Gate**:
   - keep if it improves the primary metric (dedup) without regressing throughput >X%,
     or improves throughput without regressing dedup;
   - revert otherwise.
6. **Validate correctness** — `cargo test -p property-defs-rs` must stay green; for changes
   to write SQL, also run the DB-backed `tests/batch_ingestion.rs` against a live Postgres.
7. Record the result, update `baseline.json`, repeat.

### Requirements / invariants the loop must not break

- **Correctness over speed.** Dedup is a filter in front of idempotent UPSERTs; a change
  that drops a *genuinely new* definition is a correctness bug, not a win. The benchmark's
  `passed_*` counts must never fall below the count of distinct real keys in the workload.
- **Determinism.** Same `(events, teams, seed, cache_cap)` ⇒ identical dedup counts.
- **No DB/Kafka in the hot metric.** Phase A/B/C stay in-memory so the loop is fast.
- **Behavior changes are gated.** Anything that changes what reaches Postgres (e.g.
  dropping last_seen_at precision, sharding caches) goes behind a config flag so it can be
  rolled out and reverted independently.
- **Tests green every iteration.** Never commit a red `cargo test`.

### Backlog (candidate optimizations, derived from the review)

Dedup-focused (primary):

- **D1. Drop/loosen `last_seen_at` in the event-def cache key.** Floor to a day (or remove
  from the key and bump last_seen_at on a slower cadence). Directly removes
  `wasted_timestamp_writes`. Gated by config.
- **D2. Negative cache for group-type resolution.** Cache teams/groups that resolve to
  "nothing" so we stop re-querying personhog for deleted/irrelevant teams.
- **D3. Avoid optimistic-insert/evict churn.** Insert into the shared cache only after a
  successful write, or use a short-lived "pending" set, so a transient DB blip doesn't evict
  a whole batch and cause a re-issue storm.
- **D4. Cache sizing / weighting / hybrid (foyer).** Only after the benchmark shows
  eviction-driven re-issues hurt at prod cardinality (sweep `PROPDEFS_BENCH_CACHE_CAP`).

Throughput-focused:

- **T1. Sanitize event name once per event, not once per property** (`get_props_from_object`
  re-allocates the event name for every property). Pure CPU win.
- **T2. Single hash-set probe in producer compaction** (`contains` + `insert` → one
  `insert`).
- **T3. Shard producers/caches by team** to cut shared-cache contention and improve
  locality (the "shard workers" item).

Pipelining (needs the DB-backed harness to show up, not visible in Phase A/B/C):

- **P1. Pipeline batches in the consumer** so batch K+1 is assembled/resolved while batch K's
  writes are in flight (today `process_batch` joins all writes before the next batch).
- **P2. Wire up `max_concurrent_transactions`** (currently dead config) or remove it; make
  write concurrency explicit instead of implicitly bounded by the PG pool.
