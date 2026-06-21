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
| `PROPDEFS_BENCH_FLOOR_SECS` | 3600 | last_seen_at floor period for Phase C (3600 = historical hourly baseline; 86400 = current daily default) |
| `PROPDEFS_BENCH_JSON` | unset | also print one `BENCH_JSON {...}` line |

### What each phase measures

- **Phase A — throughput.** `serde_json::from_str` + `Event::into_updates` over every event
  (the exact per-event producer CPU cost). The primary metric is `allocs_per_event` (heap
  allocations during parse, measured by a counting allocator) — it is deterministic, unlike
  wall-clock `events_per_sec` which swings up to 4x on shared CI and is reported as
  indicative only.
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
allocs_per_event       = parse_allocations / events                # ↓ better (deterministic)
events_per_sec         = events / parse_elapsed                    # ↑ better (indicative only)
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

Status: ✅ done · 🔬 investigated · ⬜ open

Dedup-focused (primary):

- ✅ **D1. Loosen `last_seen_at` in the event-def cache key.** Floored to a day (was hourly),
  gated by `EVENTDEF_LAST_SEEN_FLOOR_SECS`. Phase C `wasted_timestamp_writes` 2980 → 0 over
  6h; ~96% fewer event-def writes over 24h. The DB still records the real timestamp.
- ✅ **D2. Negative cache for group-type resolution.** TTL-bounded negative cache
  (`GROUP_TYPE_NEGATIVE_TTL_SECS`, default 600s) stops re-querying personhog for
  deleted/irrelevant teams and misused group types.
- ⬜ **D3. Avoid optimistic-insert/evict churn.** Insert into the shared cache only after a
  successful write, or use a short-lived "pending" set, so a transient DB blip doesn't evict
  a whole batch and cause a re-issue storm. (Not visible in Phase A/B/C — needs the DB-backed
  harness with failure injection.)
- ⬜ **D4. Cache sizing / weighting / hybrid (foyer).** Only after the benchmark shows
  eviction-driven re-issues hurt at prod cardinality (sweep `PROPDEFS_BENCH_CACHE_CAP`).

Throughput-focused:

- ✅ **T(lowercase). Borrow already-lowercase property keys in `detect_property_type`**
  instead of always allocating a lowercased copy. `allocs_per_event` 152.8 → 128.7.
- ⬜ **T1. Sanitize event name once per event, not once per property.** Saves the per-property
  null-scan; the owned `String` per EventProperty is still required, so it does not reduce
  `allocs_per_event` (only wall-clock) — low priority until field types change.
- 🔬 **T3 / "shard workers". Largely addressed.** `quick_cache::sync::Cache` already shards
  internally by key hash (see the min-32-items/shard note in `tests/update_cache.rs`), and the
  cache is split into 3 per-record-type subcaches. The original single-lock contention is gone.
  Further per-team sharding would help locality/eviction fairness, not lock contention — gate
  behind a contention measurement before investing.

Pipelining (measured against Postgres, not visible in Phase A/B/C):

- ✅ **P1. Write concurrency — reverted, then re-introduced once the regime was right.** First
  attempt regressed ~25-35% against a local Postgres (writes ~1ms, no latency to hide). Prod
  writes are ~173ms (the `posthog_eventproperty` insert), which *is* the regime where it pays
  off. It now lives in the staged writer (`WRITER_MAX_CONCURRENCY`); the end-to-end benchmark at
  173ms shows staged + concurrency=4 ~30% faster than the legacy serial-write path. Lesson:
  measure in the right regime — the first local measurement was unrepresentative.
- ⬜ **P4. Dead config.** `max_concurrent_transactions` and `skip_writes` are declared but never
  used (`skip_writes` even defaults to `true`). Wire up or remove — but `skip_writes` must be
  reconciled with prod config first, since making a default-`true` flag actually skip writes
  would be a breaking change.

## The benchmarks

| bench | what it measures | infra |
| --- | --- | --- |
| `pipeline` | parse throughput (allocs/event), dedup ratio, last_seen_at churn | none (in-memory) |
| `cache_contention` | shared vs per-thread cache scaling | none |
| `pipeline_scaling` | CPU pipeline scaling + cross-pod write amplification by routing | none |
| `end_to_end` | **the whole service**: real Kafka -> real pipeline -> real Postgres | Kafka + PG |

`end_to_end` is the most faithful baseline — it produces realistic events to a Kafka topic and
runs the actual reader/processor/writer (or legacy producer/consumer) loops against Postgres,
reporting end-to-end events/sec (all N consumed AND all distinct writes persisted). Set
`PROPDEFS_BENCH_WRITE_LATENCY_MS=173` to model the slow prod DB:

```bash
DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog SQLX_OFFLINE=true \
  PROPDEFS_BENCH_WRITE_LATENCY_MS=173 cargo bench -p property-defs-rs --bench end_to_end
```

## Running the DB-backed tests and benchmarks

A native PostgreSQL is started by the SessionStart hook (`.claude/hooks/setup-postgres.sh`),
which also exports `DATABASE_URL` and `SQLX_OFFLINE`. The `#[sqlx::test]` integration tests
(`batch_ingestion`, `queries`, `write_amplification`) run with a plain
`cargo test -p property-defs-rs`. The `end_to_end` bench additionally needs a Kafka broker;
Docker Hub's image CDN is blocked in the web container, so run Apache Kafka natively in KRaft
mode from `downloads.apache.org` (Java is installed) on `localhost:9092`.
