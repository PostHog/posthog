# Global Rate Limiter — Design and Implementation

## Overview

The global rate limiter enforces per-entity event throughput limits across a fleet of capture nodes.
It uses a **2-epoch sliding window counter** in Redis for global state,
a **leaky bucket local decay** model for zero-Redis-I/O hot-path decisions,
a **unified background pipeline** that batches all Redis reads and writes into a single round-trip per tick,
and **pressure-tiered adaptive sync** to minimize read volume for low-utilization entities.

## Architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│  Capture Node                                                        │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Hot Path  (check_limit_internal)                              │  │
│  │                                                                │  │
│  │  1. Lookup entity in local moka LRU cache                     │  │
│  │  2. Compute effective_level() via leaky bucket decay           │  │
│  │  3. Compare against threshold → Allowed / Limited              │  │
│  │  4. Increment local_pending on CacheEntry                     │  │
│  │  5. Enqueue UpdateRequest to mpsc channel                     │  │
│  │  6. Maybe push entity key to pending_sync (DashSet)           │  │
│  │                                                                │  │
│  │  ⚡ Zero Redis I/O — all decisions are local                   │  │
│  └───────────┬──────────────────────────────┬────────────────────┘  │
│              │ mpsc channel                  │ pending_sync set      │
│              ▼                               ▼                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Background Tick Loop  (spawned tokio task)                    │  │
│  │                                                                │  │
│  │  Every tick_interval (default 1s):                            │  │
│  │                                                                │  │
│  │  1. Drain mpsc channel → aggregate into write_batch            │  │
│  │     HashMap<(entity_key, epoch), count>                       │  │
│  │                                                                │  │
│  │  2. Drain pending_sync set → sync_keys Vec                    │  │
│  │                                                                │  │
│  │  3. Build single Redis pipeline:                              │  │
│  │     WRITES: INCRBY + EXPIRE for each (key, epoch)            │  │
│  │     READS:  MGET [curr_epoch, prev_epoch] per entity          │  │
│  │                                                                │  │
│  │  4. Execute pipeline                                          │  │
│  │                                                                │  │
│  │  5. Process read results:                                     │  │
│  │     - Compute weighted_count from 2-epoch response            │  │
│  │     - Measure drift vs local estimate                         │  │
│  │     - Update CacheEntry (estimated_count, pressure, synced_at)│  │
│  │     - Reset local_pending to 0 (Redis now includes our writes)│  │
│  │     - Track tier transitions                                  │  │
│  └───────────────────────────┬────────────────────────────────────┘  │
│                              │                                       │
└──────────────────────────────┼───────────────────────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │       Redis         │
                    │                     │
                    │  Key format:        │
                    │  {prefix}:{key}:{e} │
                    │                     │
                    │  e = epoch number   │
                    │  TTL = 2 × window   │
                    └─────────────────────┘
```

## Key Concepts

### 1. Two-Epoch Sliding Window Counter

Instead of N discrete time-bucket keys, each entity uses exactly **2 Redis keys**:
a current epoch counter and a previous epoch counter.

```text
epoch = floor(unix_timestamp / window_interval)

Redis keys for entity "team_42":
  {prefix}:team_42:{epoch}        ← current
  {prefix}:team_42:{epoch - 1}    ← previous
```

The estimated count uses weighted interpolation based on how far into the current epoch we are:

```text
progress = (now % window_interval) / window_interval     // 0.0 .. 1.0
estimated = prev_count × (1.0 - progress) + current_count
```

This produces a smooth, continuously-updating estimate that's more accurate than fixed buckets.

```text
  Count
    │
    │   prev epoch          current epoch
    │  ┌──────────┐       ┌──────────┐
    │  │▓▓▓▓▓▓▓▓▓▓│       │░░░░░░    │
    │  │▓▓▓▓▓▓▓▓▓▓│       │░░░░░░    │
    │  └──────────┘       └──────────┘
    │       weight:            weight:
    │    (1 - progress)        1.0
    │
    └──────────────────────────────────── Time
         epoch N-1    ↑     epoch N
                   boundary
```

### 2. Leaky Bucket Local Decay

Each `CacheEntry` stores the last-known weighted count from Redis (`estimated_count`)
and the time it was synced (`synced_at`).
Between syncs, the estimate **decays** at the configured leak rate:

```text
leak_rate = threshold / window_interval

effective_level(entry, now) =
    max(0, estimated_count - leak_rate × elapsed) + local_pending
```

This models the natural drain of events from the sliding window,
keeping the local estimate useful for much longer than a simple stale/fresh binary.

```text
  Level
    │
    │ ╲                                     ← estimated_count decays
    │   ╲                    ·····          ← local_pending accumulates
    │     ╲              ····
    │       ╲        ····
    │         ╲  ····
    │           ╳  ← effective_level = decayed global + local pending
    │       ····  ╲
    │   ····        ╲
    │                 ╲
    │──────────────────╲──────────────────── threshold
    │                    ╲
    └──────────────────────────────────── Time
          synced_at              next sync
```

### 3. Unified Background Pipeline

All Redis I/O is deferred to a single background tokio task.
This means the hot path (request evaluation) **never blocks on Redis**.

The background task uses `tokio::select!` over two sources:

```text
┌───────────────────────────┐     ┌──────────────────────────┐
│  mpsc channel (writes)    │     │  tokio interval (tick)   │
│                           │     │                          │
│  UpdateRequest {          │     │  Every tick_interval:    │
│    key, count, timestamp  │     │  → drain both sources    │
│  }                        │     │  → build pipeline        │
│                           │     │  → execute               │
│  Aggregated into:         │     │  → process results       │
│  HashMap<(key, epoch),    │     │                          │
│           count>          │     │                          │
└───────────────────────────┘     └──────────────────────────┘
```

The pipeline per tick consists of:

- **Writes**: `INCRBY key delta` + `EXPIRE key ttl` for each `(entity, epoch)` with pending counts
- **Reads**: `MGET [current_epoch_key, prev_epoch_key]` for each entity in `pending_sync`

All operations go in a single Redis round-trip.

### 4. Adaptive Sync (Pressure Tiers)

Not all entities need to be synced at the same frequency.
The system assigns each entity a **pressure tier** based on how close it is to the threshold:

```text
  Pressure tiers and sync frequency:

  ┌─────────────────────────────────────────────────────────────┐
  │                                                             │
  │  ┌───────────┐ ┌──────────────┐ ┌─────────┐ ┌───────────┐ │
  │  │   Idle    │ │     Low      │ │ Normal  │ │    Hot    │ │
  │  │  < 10%    │ │  10% - 50%   │ │50% - 80%│ │  > 80%    │ │
  │  │           │ │              │ │         │ │           │ │
  │  │ No sync   │ │ 4× interval  │ │ 1× base │ │ ½× base  │ │
  │  │           │ │   (60s)      │ │  (15s)  │ │  (7.5s)   │ │
  │  └───────────┘ └──────────────┘ └─────────┘ └───────────┘ │
  │                                                             │
  │  0%          10%              50%         80%         100%  │
  │  ─────────────────────────────────────────────────────────  │
  │                     pressure (level / threshold)            │
  └─────────────────────────────────────────────────────────────┘
```

With typical power-law traffic distributions (~90% idle, ~8% low, ~1.5% normal, ~0.5% hot),
this reduces pipeline read volume by **~95%** compared to syncing every entity at the base interval.

**Tier transitions are immediate.**
If local traffic pushes an idle entity above the 10% boundary,
it's promoted to Low on the very next request — no waiting for a stale sync interval.

Tier boundaries are pressure-based (level / threshold), so they apply correctly to custom keys regardless of threshold magnitude. A custom key with a 100× higher limit than the default will sync at the same relative cadence when at equivalent pressure.

## Data Model

### CacheEntry (local moka LRU)

```rust
struct CacheEntry {
    estimated_count: f64,    // weighted count from last Redis sync
    synced_at: Instant,      // when we last read from Redis
    local_pending: u64,      // events counted locally since last sync, reset to 0 on sync
    pressure: f64,           // effective_level / threshold at last sync
}
```

`local_pending` is reset to 0 when fresh data arrives from Redis.
Since `estimated_count` already includes events this node wrote via INCRBY across prior ticks,
preserving `local_pending` would double-count them.
Events arriving during the MGET window (~100ms) are briefly lost from the local estimate
but are written to Redis on the next tick — the under-count is negligible (<0.002% of threshold).

### Redis Key Model

```text
Key:   {prefix}:{entity_key}:{epoch_number}
Value: integer counter (INCRBY)
TTL:   2 × window_interval (120s for 60s window)
```

Only 2 keys per entity exist at any time (current + previous epoch).

### Configuration

#### Rate limiting behavior

| Parameter | Default | Env var (capture) | Description |
|---|---|---|---|
| `global_threshold` | 1,000,000 | `GLOBAL_RATE_LIMIT_THRESHOLD` | Default limit per window per entity |
| `window_interval` | 60s | `GLOBAL_RATE_LIMIT_WINDOW_INTERVAL_SECS` | Sliding window size for the 2-epoch counter |
| `sync_interval` | 15s | `GLOBAL_RATE_LIMIT_SYNC_INTERVAL_SECS` | Base staleness before re-sync (adaptive tiers multiply this) |
| `tick_interval` | 1s | `GLOBAL_RATE_LIMIT_TICK_INTERVAL_MS` | Background pipeline cadence |
| `custom_keys` | empty | `GLOBAL_RATE_LIMIT_OVERRIDES_CSV` | Per-key threshold overrides (`key=limit,...`) |

#### Local cache (Moka)

These use sensible defaults derived from the rate limiting behavior settings above.
They are not exposed as env vars in capture — change them in the library defaults
only if you're also changing the window/sync intervals.

| Parameter | Default | Description |
|---|---|---|
| `local_cache_max_entries` | 300,000 | Hard cap on entry count. ~400 bytes/entry → 300K ≈ 120 MB. Exposed as `GLOBAL_RATE_LIMIT_LOCAL_CACHE_MAX_ENTRIES` in capture |
| `local_cache_ttl` | 600s | Absolute entry expiry. Should be long enough for leaky bucket decay to stay useful between syncs |
| `local_cache_idle_timeout` | 300s | Entries not accessed within this window are evicted early. Hot keys are constantly re-inserted so they never idle-expire; cold keys reclaim slots faster than waiting for the full TTL |

#### Redis

| Parameter | Default | Description |
|---|---|---|
| `global_cache_ttl` | 120s (2 × window) | `EXPIRE` TTL on Redis epoch keys. Must be ≥ 2 × `window_interval` so both epoch keys survive for reads |
| `global_read_timeout` | 100ms | Timeout for batched MGET reads |
| `global_write_timeout` | 100ms | Timeout for batched INCRBY writes |
| `redis_key_prefix` | `@posthog/global_rate_limiter` | Prefix for all Redis keys (capture derives from `capture_mode`) |

#### Internal

| Parameter | Default | Env var (capture) | Description |
|---|---|---|---|
| `channel_capacity` | 1,000,000 | — | mpsc channel buffer for async update requests |

#### How the TTL settings relate

```text
  Time ──────────────────────────────────────────────────────────────────►

  │◄── window_interval (60s) ──►│
  │                              │
  │  global_cache_ttl (120s = 2×window)                                  │
  │  Redis epoch keys expire after this, ensuring old counters clean up  │
  │◄─────────────────────────────────────────────────────────────────────►│
  │                                                                      │
  │  local_cache_idle_timeout (300s)                                     │
  │  Cold keys (no traffic) evicted after this, reclaiming Moka slots   │
  │◄─────────────────────────────────────────────────────────────────────►│
  │                                                                      │
  │  local_cache_ttl (600s)                                              │
  │  Absolute expiry — even hot keys eventually re-sync from scratch    │
  │◄─────────────────────────────────────────────────────────────────────►│
```

**Tuning guidance:**

- `local_cache_idle_timeout` should be **shorter** than `local_cache_ttl`
  but **longer** than `sync_interval × 4` (the slowest adaptive tier interval)
  so that Low-tier keys aren't prematurely evicted between syncs.
- Under high key cardinality with cold-skewed traffic,
  a shorter idle timeout reclaims slots faster, keeping the cache responsive.
- `local_cache_ttl` acts as an upper bound on how stale an entry can get
  before being forced to re-sync from scratch on next access.
- `global_cache_ttl` is Redis hygiene — it only needs to be ≥ 2 × `window_interval`.
  Making it much larger wastes Redis memory on dead keys.

## Request Flow

```text
    Request arrives
         │
         ▼
  ┌──────────────┐
  │ check_limit  │
  │              │
  │ Cache hit?   │──── No ──→ Insert fresh entry, queue sync, ALLOW
  │              │            (fail open on first contact)
  └──────┬───────┘
         │ Yes
         ▼
  ┌──────────────────────┐
  │ effective_level()    │
  │                      │
  │ = max(0, est - drain)│
  │   + local_pending    │
  │   + this request     │
  └──────┬───────────────┘
         │
         ▼
  ┌──────────────────────┐
  │ level >= threshold?  │──── Yes ──→ LIMITED (return response)
  └──────┬───────────────┘
         │ No
         ▼
  ┌──────────────────────┐
  │ Sync needed?         │
  │ (pressure-tiered)    │──── Yes ──→ Push to pending_sync
  └──────┬───────────────┘
         │
         ▼
  ┌──────────────────────┐
  │ Enqueue update       │
  │ to mpsc channel      │
  └──────┬───────────────┘
         │
         ▼
      ALLOWED
```

## Multi-Redis Partitioning

When multiple Redis instances are configured, work is partitioned by consistent hashing:

```text
  Entity keys          Redis instances
  ┌──────────┐
  │ team_1   │ ──hash──→ Redis[0]
  │ team_2   │ ──hash──→ Redis[2]
  │ team_3   │ ──hash──→ Redis[0]
  │ team_4   │ ──hash──→ Redis[1]
  │ ...      │
  └──────────┘

  Each partition executes its pipeline independently and in parallel.
  Single-instance mode (common case) skips partitioning entirely.
```

## Metrics

| Metric | Type | Purpose |
|---|---|---|
| `global_rate_limiter_eval_counts_total` | Counter | Core allow/limit decisions |
| `global_rate_limiter_cache_counts_total` | Counter | Cache hit/miss/sync_queued |
| `global_rate_limiter_pipeline_ms` | Histogram | Redis pipeline latency |
| `global_rate_limiter_tick_ms` | Histogram | Full tick duration |
| `global_rate_limiter_pipeline_size` | Histogram | Entities per pipeline (read/write) |
| `global_rate_limiter_pending_sync_size` | Gauge | Backpressure signal |
| `global_rate_limiter_sync_tier_gauge` | Gauge | Entity distribution across tiers |
| `global_rate_limiter_tier_transitions_total` | Counter | Tier promotion/demotion events |
| `global_rate_limiter_estimate_drift` | Histogram | Local vs Redis accuracy |
| `global_rate_limiter_sync_staleness_ms` | Histogram | Real staleness at access time |
| `global_rate_limiter_error_total` | Counter | Pipeline errors and timeouts |
| `global_rate_limiter_records_total` | Counter | Total Redis commands issued |

## Redis Load Reduction

Compared to the previous N-bucket design:

| Dimension | Old (N-bucket) | New (2-epoch + adaptive) |
|---|---|---|
| Keys per entity | 3 | 2 |
| Redis round-trips per check | 1 (inline MGET) | 0 (hot path is local) |
| Round-trips per tick | N/A | 1 (batched pipeline) |
| Read volume per tick | N/A | ~296 entities (vs ~6,667 without adaptive) |
| Total RT reduction | — | ~99% |
| Read volume reduction | — | ~95% |

## File Layout

```text
rust/common/limiters/
├── src/
│   ├── global_rate_limiter.rs    ← Core implementation + 31 unit tests
│   └── ...
├── tests/
│   └── global_rate_limiter_integration_tests.rs  ← 9 real-Redis tests
├── benches/
│   └── global_rate_limiter.rs    ← Benchmarks
└── Cargo.toml

rust/capture/src/
├── global_rate_limiter.rs        ← Capture service wrapper
├── config.rs                     ← Env config (sync_interval, tick_interval)
└── prometheus.rs                 ← Histogram bucket registration
```
