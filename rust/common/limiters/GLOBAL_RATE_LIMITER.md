# Global Rate Limiter — Design and Implementation

## Overview

The global rate limiter enforces per-entity event throughput limits across a fleet of capture nodes.
It uses a **2-epoch sliding window counter** in Redis for global state,
a **leaky bucket local decay** model for zero-Redis-I/O hot-path decisions,
a **background tick** that sends each node's counts to Redis and reads back fleet counts in bounded, chunked commands,
and **pressure-tiered adaptive sync** to minimize read volume for low-utilization entities.

## Architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│  Capture Node                                                        │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Hot Path  (check_limit_internal)                              │  │
│  │                                                                │  │
│  │  1. Enqueue UpdateRequest to mpsc channel (count > 0)          │  │
│  │  2. Lookup entity in the local moka cache                      │  │
│  │  3. Decide whether to push the key to pending_sync (DashSet)   │  │
│  │  4. Add this request to local_pending on the CacheEntry        │  │
│  │  5. Compare effective_level() against the threshold            │  │
│  │     → Allowed / Limited, with the read-outage guard            │  │
│  │                                                                │  │
│  │  ⚡ Zero Redis I/O — all decisions are local                   │  │
│  └───────────┬──────────────────────────────┬────────────────────┘  │
│              │ mpsc channel                  │ pending_sync set      │
│              ▼                               ▼                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Background task  (spawned tokio task)                         │  │
│  │                                                                │  │
│  │  Between ticks: merge each UpdateRequest into write_batch      │  │
│  │     HashMap<(entity_key, epoch), count>                        │  │
│  │                                                                │  │
│  │  Every tick_interval (default 1s):                             │  │
│  │  1. Take up to max_sync_keys_per_tick keys from pending_sync   │  │
│  │  2. Purge write entries whose epoch can no longer be read      │  │
│  │  3. Take up to max_sync_keys_per_tick write entries            │  │
│  │  4. Per Redis instance, writes first, then reads:              │  │
│  │     WRITES: INCRBY + EXPIREAT per (key, epoch), chunked        │  │
│  │     READS:  MGET [curr_epoch, prev_epoch] per entity, chunked  │  │
│  │  5. Apply each read chunk as it lands:                         │  │
│  │     - Compute weighted_count from the 2-epoch response         │  │
│  │     - Measure drift vs local estimate                          │  │
│  │     - Update CacheEntry (estimated_count, pressure, synced_at) │  │
│  │     - Reset local_pending to 0                                 │  │
│  │     - Record tier transitions for observability                │  │
│  │  6. Record read health per instance                            │  │
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
                    │ dies 1-2 epochs on  │
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

`synced_at` is `None` until the first Redis read lands. A never-synced entry is
due for a sync as soon as it clears `min_sync_floor`; a synced one waits out its
pressure tier. Collapsing the two delays a new key's first read by a full tier
interval, during which the node cannot see the fleet.

**A known, tolerated race.**
The request path's get-modify-insert can overwrite the entry a Redis read just refreshed.
The overwriting entry keeps the older estimate and the older `synced_at`, so it stays due for a sync, and the key's next request queues the read that corrects it.
Until then its estimate can be lower or higher than the fresh read.
It is higher when the key's previous epoch was over its threshold, because the window then drains faster than the leak rate.
The collision window is microseconds per event against one read per key every 7.5 to 60 seconds.
A fix via moka's per-key entry API cost ~0.3 µs per evaluation (+31% on this crate's bench) for no measurable change in decisions, so it is deliberately not applied.

Between syncs, the estimate **decays** at the configured leak rate:

```text
leak_rate = threshold / window_interval

effective_level(entry, now) =
    max(0, estimated_count - leak_rate × elapsed) + local_pending
```

This approximates the drain of the sliding window and keeps the local estimate useful for much longer than a simple stale/fresh binary.
It matches the real drain only when the previous epoch held exactly the threshold.
Below that the local estimate drains too fast, and above it too slowly.

**Once reads have failed for `max_read_outage`, `local_pending` cannot limit a key.**
`local_pending` is a correction to the last fleet count this node read, and only a successful read clears it.
Nothing else ages it, so while reads to Redis fail it grows without bound.
Given a long enough read outage, one node's count reaches the threshold on its own and limits a key that is under its limit.
Everywhere else the limiter fails open when Redis cannot answer, so this path would fail closed.

So this node records, for each Redis instance, when its current run of failed reads began.
A tick with any successful read clears the record, a tick whose every read failed starts it if it is not running, and a tick with no reads leaves it alone.
A quiet period before a failure therefore never counts. A quiet period after a failure does, because no read has confirmed the count since.
A read fails only when the client cannot complete it.
With the read/write split client, a replica read that the primary then answers counts as a success, so the guard trips only when both fail.
The record is wall-clock time, not a tick count, because during an outage one tick can wait seconds on timeouts and reconnects.
Once reads have failed for `max_read_outage`, a key that instance owns is judged by its decayed fleet count alone:

```text
limit_level = reads failing ? max(0, estimated_count - leak_rate × elapsed)
                            : effective_level
```

The fleet count still drains as the window moves, so a key known to be over its limit keeps being limited until the evidence runs out.
The guard gates only the limit decision.
It does not reset the entry, change its counts, or change when it syncs, and it runs only for a key already over its threshold.

The signal is per instance, not global.
With more than one instance, a global signal would let a healthy instance hide a dead one, and the dead one's keys would fail closed again.
`max_read_outage` defaults to one `window_interval`.
A key under its limit sees fewer than `threshold` events in any one window, so this node's count for it can reach the threshold only once that count spans more than one window.
The count spans the outage plus the time since the key's last read before it, which is about one sync cadence of the key's tier.
So a false limit can happen only in that last cadence before the guard engages, and only for a key whose traffic lands mostly on this node.
For example, with steady traffic and a window eight times the sync interval, only a key above about 94% of its limit is exposed, for at most half a sync interval.
To close even that gap, set `max_read_outage` to `window_interval - sync_interval` or less. That bound holds while `sync_interval` is at most a third of `window_interval`.

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

### 3. Background Pipeline

All counter I/O runs in one background tokio task per limiter, so the hot path (request evaluation) **never blocks on Redis**.
A second task refreshes custom-key thresholds when a dynamic source is configured.

The background task uses `tokio::select!` over two sources:

```text
┌───────────────────────────┐     ┌──────────────────────────────┐
│  mpsc channel (writes)    │     │  tokio interval (tick)       │
│                           │     │                              │
│  UpdateRequest {          │     │  Every tick_interval:        │
│    key, count, timestamp  │     │  → take bounded slices of    │
│  }                        │     │    pending_sync and writes   │
│                           │     │  → send writes, then reads   │
│  Merged between ticks     │     │  → apply read results        │
│  into:                    │     │                              │
│  HashMap<(key, epoch),    │     │                              │
│           count>          │     │                              │
└───────────────────────────┘     └──────────────────────────────┘
```

The channel is not read while a tick runs, so updates wait in it until the tick ends.

Each tick, per Redis instance:

- **Writes** go first: `INCRBY key delta` + `EXPIREAT key deadline` for each `(entity, epoch)` with pending counts.
- **Reads** follow: `MGET [current_epoch_key, prev_epoch_key]` for each entity taken from `pending_sync`.
- Writes go first because a read result resets the key's `local_pending`, so the read must already include this tick's writes.
- Each side is split into commands of at most `max_keys_per_command` Redis keys, so a read command carries half that many entities.
- At most `max_concurrent_commands` commands run at once per instance. A tick with both reads and writes costs at least two round trips, and more when the batch is large.

### 4. Adaptive Sync (Pressure Tiers)

Not all entities need to be synced at the same frequency.
The system assigns each entity a **pressure tier** based on how close it is to the threshold:

```text
  Pressure tiers and sync frequency:

  ┌─────────────────────────────────────────────────────────────┐
  │                                                             │
  │  ┌───────────┐ ┌──────────────┐ ┌─────────┐ ┌───────────┐ │
  │  │   Idle    │ │     Low      │ │ Normal  │ │    Hot    │ │
  │  │  < 10%    │ │  10% - 50%   │ │50% - 80%│ │  ≥ 80%    │ │
  │  │           │ │              │ │         │ │           │ │
  │  │ 4× base,  │ │ 4× interval  │ │ 1× base │ │ ½× base  │ │
  │  │above floor│ │   (60s)      │ │  (15s)  │ │  (7.5s)   │ │
  │  └───────────┘ └──────────────┘ └─────────┘ └───────────┘ │
  │                                                             │
  │  0%          10%              50%         80%         100%  │
  │  ─────────────────────────────────────────────────────────  │
  │                     pressure (level / threshold)            │
  └─────────────────────────────────────────────────────────────┘
```

A key below `min_sync_floor` does not sync at all, whatever its tier.
An idle key above the floor syncs on the Low cadence, so a key that is hot across the fleet but cold on every node is still discovered.

**The tier is recomputed on every request.**
It uses the larger of the current `level / threshold` and the pressure at the last sync, so local traffic moves a key to a faster cadence at once.
`tier_transitions_total` counts changes only when a read lands.

Tier boundaries are pressure-based (level / threshold), so they apply correctly to custom keys regardless of threshold magnitude. A custom key with a 100× higher limit than the default will sync at the same relative cadence when at equivalent pressure.

**Tier-distribution gauges come from a throttled full scan.** `cache_size` is cheap (`entry_count`) and emits every tick. The per-tier `sync_tier_gauge` needs a full `cache.iter()` scan, so it runs only every `TIER_SCAN_INTERVAL_TICKS` (a constant, 30): the distribution moves slowly and prod metrics dedup to 60s, so scanning every tick would be wasted work under load. The scan runs in the background tick task, off the per-event hot path.

### 5. Timeouts

Each Redis command runs under two timeouts, and the shorter one fires first:

- The limiter's own timer, `global_read_timeout` or `global_write_timeout` (250ms by default).
- The Redis client's response timeout. In capture it is `GLOBAL_RATE_LIMIT_REDIS_RESPONSE_TIMEOUT_MS`, else `REDIS_RESPONSE_TIMEOUT_MS` (100ms by default).

A client timeout is counted under `cause="redis_write"` for writes and `cause="redis_error"` for reads.
The `write_timeout` and `read_timeout` causes mean the limiter's own timer fired.
With the read/write split client, a replica read that fails with a recoverable error, such as a timeout, is retried on the primary. So one read can use two client timeouts, and the limiter's read timer can still fire.

A write that times out is not retried.
If the command already reached Redis it still applies.
If it was still queued in the client, the client drops it, so a timed-out write may or may not have counted.

## Data Model

### CacheEntry (local moka cache)

```rust
struct CacheEntry {
    estimated_count: f64,    // weighted count from last Redis sync
    synced_at: Option<Instant>, // when we last read from Redis; None until the first read
    local_pending: u64,      // events counted locally since last sync, reset to 0 on sync
    pressure: f64,           // effective_level / threshold at last sync
}
```

`local_pending` is reset to 0 when fresh data arrives from Redis.
Since `estimated_count` already includes the events this node wrote via INCRBY, preserving `local_pending` would double-count them.
Events whose write has not landed when the read does drop out of the local estimate.
That covers events counted after the tick took its write batch, and writes deferred past the per-tick cap.
They appear in a later read once their write lands, unless their epoch ages out first and the tick purges them.

### Redis Key Model

```text
Key:   {prefix}:{entity_key}:{epoch_number}
Value: integer counter (INCRBY)
Dies:  (epoch + 2) × window_interval + grace + a per-key offset inside one window
```

`grace` is the part of `global_cache_ttl` above 2 × `window_interval`, and zero by default.
With zero grace, up to 3 keys per entity exist at any time. Reads consult 2 (current + previous
epoch); the offset that spreads expiry can hold the generation before those
alive for up to one more window.

**Two deployments that share a key prefix must agree on `window_interval`.**
The epoch number is `floor(unix / window_interval)`, so a mismatch splits the
shared counter into separate key namespaces. Capture's AI byte budget is one
such namespace (its prefix carries no `capture_mode`). The
`global_rate_limiter_window_seconds{scope}` gauge publishes each process's
running value so an alert can compare them.

### Configuration

Capture runs two limiters from these settings: the per-(token, distinct_id) limiter and the AI byte budget.
Where the two read different env vars, both are listed.

#### Rate limiting behavior

| Parameter | Default | Env var (capture) | Description |
|---|---|---|---|
| `global_threshold` | 1,000,000 | `GLOBAL_RATE_LIMIT_TOKEN_DISTINCTID_THRESHOLD` (capture default 300,000); AI: `AI_BYTE_LIMIT_PER_SECOND` × the AI window | Default limit per window per key |
| `window_interval` | 60s | `GLOBAL_RATE_LIMIT_WINDOW_INTERVAL_SECS`; AI: `AI_BYTE_LIMIT_WINDOW_INTERVAL_SECS`, else the former | Sliding window size for the 2-epoch counter |
| `sync_interval` | 15s | `GLOBAL_RATE_LIMIT_SYNC_INTERVAL_SECS` | Base re-sync cadence. The pressure tier scales it |
| `tick_interval` | 1s | `GLOBAL_RATE_LIMIT_TICK_INTERVAL_MS` | Background pipeline cadence |
| `min_sync_floor` | 10 | `GLOBAL_RATE_LIMIT_MIN_SYNC_FLOOR` (the AI limiter uses 0) | Minimum local level before a key is read. Capped at 1% of the key's threshold |
| `max_read_outage` | `window_interval` | `GLOBAL_RATE_LIMIT_MAX_READ_OUTAGE_SECS` | How long, in wall-clock time, reads to an instance must keep failing before its keys stop limiting on this node's unconfirmed counts. A replica read that the primary answers counts as a success. Derived from the configured window, not the default. `0` disables the guard |
| `custom_keys` | empty | `GLOBAL_RATE_LIMIT_TOKEN_DISTINCTID_OVERRIDES_CSV`; AI: `AI_BYTE_LIMIT_OVERRIDES_CSV` | Per-key threshold overrides (`key=limit,...`) |
| `custom_key_source` | none | `GLOBAL_RATE_LIMIT_CUSTOM_THRESHOLD_KEY` | Redis key of a JSON threshold map that replaces `custom_keys` once fetched. Per-(token, distinct_id) limiter only |
| `custom_key_refresh_interval` | 60s | `GLOBAL_RATE_LIMIT_CUSTOM_THRESHOLD_REFRESH_SECS` | Refresh cadence for `custom_key_source` |

#### Throughput bounds

| Parameter | Default | Env var (capture) | Description |
|---|---|---|---|
| `max_sync_keys_per_tick` | 20,000 | `GLOBAL_RATE_LIMIT_MAX_SYNC_KEYS_PER_TICK` | Keys read per tick, and write entries sent per tick. The rest wait for later ticks |
| `max_keys_per_command` | 2,000 | `GLOBAL_RATE_LIMIT_MAX_KEYS_PER_COMMAND` | Redis keys per command. A read costs two keys per entity |
| `max_concurrent_commands` | 4 | `GLOBAL_RATE_LIMIT_MAX_CONCURRENT_COMMANDS` | Commands in flight at once per instance |
| `max_write_batch_entries` | 200,000 | `GLOBAL_RATE_LIMIT_MAX_WRITE_BATCH_ENTRIES` | Buffered `(key, epoch)` entries. At the cap, updates for new keys drop and are counted |
| `max_pending_sync_entries` | 200,000 | `GLOBAL_RATE_LIMIT_MAX_PENDING_SYNC_ENTRIES` | Queued syncs. At the cap, new sync requests drop and re-queue on the key's next request |
| `channel_capacity` | 1,000,000 | — | mpsc channel buffer for async update requests |

#### Local cache (Moka)

| Parameter | Default | Env var (capture) | Description |
|---|---|---|---|
| `local_cache_max_entries` | 300,000 | `GLOBAL_RATE_LIMIT_TOKEN_DISTINCTID_LOCAL_CACHE_MAX_ENTRIES` (capture default 5,000,000); AI: `AI_BYTE_LIMIT_LOCAL_CACHE_MAX_ENTRIES` | Entry cap. Moka's default TinyLFU policy can refuse a new key at the cap, and that key then takes the always-allowed miss path |
| `local_cache_ttl` | 600s | `GLOBAL_RATE_LIMIT_LOCAL_CACHE_TTL_SECS` | Time since the entry was last written. Every request and every read rewrites the entry, so this restarts each time. At or above `local_cache_idle_timeout` it never fires first |
| `local_cache_idle_timeout` | 300s | `GLOBAL_RATE_LIMIT_LOCAL_CACHE_IDLE_TIMEOUT_SECS` | Evicts entries no request touched within this time. Hot keys never idle-expire; cold keys reclaim slots |

#### Redis

| Parameter | Default | Env var (capture) | Description |
|---|---|---|---|
| `global_cache_ttl` | 120s | — | Only the part above 2 × `window_interval` is used, as clock-skew grace. Keys expire at the absolute deadline from `epoch_expire_at`, so a smaller value cannot shorten their life |
| `global_read_timeout` | 250ms | `GLOBAL_RATE_LIMIT_READ_TIMEOUT_MS` | The limiter's cap on one read command. See Timeouts |
| `global_write_timeout` | 250ms | `GLOBAL_RATE_LIMIT_WRITE_TIMEOUT_MS` | The limiter's cap on one write command. See Timeouts |
| `redis_key_prefix` | `@posthog/global_rate_limiter` | — | Prefix for all Redis keys. Capture derives the per-(token, distinct_id) prefix from `capture_mode`; the AI prefix carries none |

Capture connects each limiter to `GLOBAL_RATE_LIMIT_REDIS_URL`, with reads going to `GLOBAL_RATE_LIMIT_REDIS_READER_URL` when that is set.
Without `GLOBAL_RATE_LIMIT_REDIS_URL`, both limiters share capture's main Redis client, and the `GLOBAL_RATE_LIMIT_REDIS_*_TIMEOUT_MS` settings do nothing.
If the dedicated Redis is unreachable at startup, capture still starts.
Its client starts with no connection, and every command fails as unrecoverable, so the limiter's first failing tick heals it and connects it once Redis answers.
Until then the limiter behaves as in any Redis outage.
A malformed URL still stops capture from starting.

#### Clamps and tuning

`new()` clamps three settings and logs a warning when it does:

| Parameter | Clamped to at least | What an undersized value breaks |
|---|---|---|
| `local_cache_idle_timeout` | `window_interval` | Entries expire mid-window and the next request takes the always-allowed miss path |
| `local_cache_ttl` | `window_interval` | Same, for an entry that no request or read rewrites for that long |
| `global_cache_ttl` | 2 × `window_interval` | Nothing, because expiry is absolute and a smaller value only removes grace. Capture never sets it, so the warning fires at startup whenever the window is above 60s |

- An entry idles out only when no request touches it for `local_cache_idle_timeout`, so a key's sync cadence never evicts an active key.
- Under high key cardinality with cold-skewed traffic, a shorter idle timeout reclaims slots faster.
- **`min_sync_floor` gates reads only.** It never drops a count; it only suppresses the `MGET` for keys too far under their threshold to be limited. Counts can still be lost to a full channel, the write-batch cap, or a failed write.
- Writes are bounded separately. `absorb_update` merges updates by `(key, epoch)` between ticks, so write volume scales with distinct active keys, not event rate.

## Request Flow

```text
    Request arrives
         │
         ▼
  ┌──────────────────────────┐
  │ Custom mode, no override │──── Yes ──→ NOT APPLICABLE
  └──────┬───────────────────┘
         │ No
         ▼
  ┌──────────────────────────┐
  │ Enqueue the count to the │   (any count > 0, limited or not)
  │ mpsc channel             │
  └──────┬───────────────────┘
         ▼
  ┌──────────────────────────┐
  │ Cache hit?               │──── No ──→ Insert entry with this count,
  └──────┬───────────────────┘            queue a sync if at or above
         │ Yes                            the floor, ALLOW
         ▼
  ┌──────────────────────────┐
  │ Below the floor? no sync │
  │ Else due by tier cadence │──── Due ──→ Push to pending_sync
  └──────┬───────────────────┘
         ▼
  ┌──────────────────────────┐
  │ Add this count to        │
  │ local_pending            │
  └──────┬───────────────────┘
         ▼
  ┌──────────────────────────┐
  │ level >= threshold?      │──── No ──→ ALLOW
  └──────┬───────────────────┘
         │ Yes
         ▼
  ┌──────────────────────────┐
  │ Reads to the key's       │
  │ instance failing for     │──── No ──→ LIMIT
  │ max_read_outage?         │
  └──────┬───────────────────┘
         │ Yes
         ▼
  ┌──────────────────────────┐
  │ Decayed fleet count      │──── Yes ──→ LIMIT
  │ >= threshold?            │
  └──────┬───────────────────┘
         │ No
         ▼
      ALLOW (counted in outage_limit_skipped_total)
```

## Multi-Redis Partitioning

When multiple Redis instances are configured, work is split by a stable hash of the key, modulo the instance count:

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

### Before raising the instance count

Partitioning is dormant at one instance: `instance_index` returns 0 and never
hashes. Two things to know before that changes.

1. **Salt any new per-key derivation.** `select_redis_client` and
   `epoch_expire_at` both hash the entity key. If they share a hash, a shard
   count that shares a factor with the window leaves each shard only a fraction
   of the expiry offsets and the expiry burst returns per shard. See
   `EXPIRY_HASH_DOMAIN`. Jitter itself does not need a stable hash, because a
   disagreement only moves a deadline inside its bounded window. Shard
   selection does, and uses SipHash-1-3 for that reason.
2. **Changing the instance count splits counters while the rollout is in
   flight.** Pods on the old count and the new one route the same key to
   different instances, so each sees part of its traffic. This under-counts and
   therefore fails open, never over-enforces, and it clears once every pod
   agrees and the current epoch keys expire. Modulo sharding moves N/(N+1) of
   the keys when the count goes from N to N+1; a consistent-hashing scheme would
   move about 1/(N+1) of them and shrink this window, but it cannot remove it.

## Redis load

- The hot path issues no Redis I/O.
- Writes: each tick sends one INCRBY and one EXPIREAT per distinct `(key, epoch)` this node saw since the last drain, up to `max_sync_keys_per_tick`.
- Every node that saw a key writes it, so write volume grows with fleet size as well as with the number of active keys.
- Reads: each tick reads two epoch keys per key that is at or above the floor and due by its tier, up to `max_sync_keys_per_tick`.

## Metrics

| Metric | Type | Purpose |
|---|---|---|
| `global_rate_limiter_eval_counts_total` | Counter | Core allow/limit decisions |
| `global_rate_limiter_cache_counts_total` | Counter | Cache hit/miss/sync_queued, exactly one per evaluation |
| `global_rate_limiter_outage_limit_skipped_total` | Counter | Limits withheld because the key's instance was in a read outage. It stays at zero while reads work |
| `global_rate_limiter_read_failing_seconds` | Gauge | Seconds since reads to one instance began failing, per `redis_idx`, set on each tick that reads. Zero while reads succeed. The guard engages once it reaches `max_read_outage` |
| `global_rate_limiter_pipeline_ms` | Histogram | Latency of successful commands only, with no read/write label, so failed and timed-out commands are absent |
| `global_rate_limiter_tick_ms` | Histogram | Duration of ticks that had work |
| `global_rate_limiter_pipeline_size` | Histogram | Keys read and `(key, epoch)` entries written per tick, by `op` |
| `global_rate_limiter_commands_per_tick` | Histogram | Commands issued per tick per instance after chunking, by `op` |
| `global_rate_limiter_pending_sync_size` | Gauge | Keys read this tick, capped at `max_sync_keys_per_tick`. For the backlog, use `sync_deferred_size` |
| `global_rate_limiter_sync_deferred_size` | Gauge | Keys still queued for sync after a tick took its slice |
| `global_rate_limiter_write_deferred_size` | Gauge | `(key, epoch)` entries still batched after a tick took its slice |
| `global_rate_limiter_sync_skipped_total` | Counter | Syncs not queued because the key is below the floor |
| `global_rate_limiter_sync_tier_gauge` | Gauge | Entity distribution across tiers (scanned every `TIER_SCAN_INTERVAL_TICKS`) |
| `global_rate_limiter_tier_transitions_total` | Counter | Tier changes, counted when a read lands |
| `global_rate_limiter_cache_size` | Gauge | Live local cache entry count vs cap |
| `global_rate_limiter_window_seconds` | Gauge | Configured `window_interval` per scope. Deployments that share a Redis key prefix must report the same value, or their epoch keys diverge and the shared counter splits |
| `global_rate_limiter_eviction_total` | Counter | Cache evictions by cause (size/expired/explicit) |
| `global_rate_limiter_estimate_drift` | Histogram | Local vs Redis accuracy |
| `global_rate_limiter_sync_staleness_ms` | Histogram | Real staleness at access time. A large share sits past one minute in normal operation, from idle keys that stopped syncing below the floor, so read its tail as expected rather than as an outage |
| `global_rate_limiter_error_total` | Counter | By `step` and `cause`: failed commands (`redis_write`, `redis_error`, `write_timeout`, `read_timeout`, see Timeouts), drops at the caps (`channel_full`, `write_batch_full`, `pending_sync_full`), and `stale_epoch_purged` |
| `global_rate_limiter_records_total` | Counter | Keys moved by successful commands, by `op`: write entries for writes, two result slots per entity for reads |
| `global_rate_limiter_custom_thresholds_loaded` | Gauge | Custom thresholds applied at the last successful refresh |
| `global_rate_limiter_custom_thresholds_last_refresh_timestamp` | Gauge | Unix time of the last successful refresh |
| `global_rate_limiter_custom_thresholds_fetch_total` | Counter | Refresh fetches by `result`. Not scoped to a limiter |

## File Layout

```text
rust/common/limiters/
├── src/
│   ├── global_rate_limiter.rs    ← Core implementation and unit tests
│   ├── custom_key_source.rs      ← Dynamic custom-key thresholds from Redis
│   └── ...
├── tests/
│   └── global_rate_limiter_integration_tests.rs  ← Real-Redis tests
├── benches/
│   └── global_rate_limiter.rs    ← Benchmarks
└── Cargo.toml

rust/capture/src/
├── global_rate_limiter.rs        ← Capture service wrapper
├── config.rs                     ← Env config for both capture limiters
└── prometheus.rs                 ← Histogram bucket registration
```
