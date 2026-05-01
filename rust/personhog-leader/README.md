## personhog-leader cluster

### Requirements

- provides API contract allowing strong consistent reads/writes to person state
- enables faster/more efficient writes to person properties than writing directly to Postgres
- durably stores any write that a personhog client has received a status OK for
- new service versions can be deployed without service disruptions or inconsistent writes
- pods can scale up and down without service disruptions or inconsistent writes
- crashed pods can be recovered from with minimal downtime

### To Implement

### Known Implementation Details

```mermaid
---
title: PersonHog Leader Cluster
---
graph TB
    subgraph P[Leader Pod]
        C1[vNode Cache]
    end

    P -->|produce merged state| K[(Kafka person_state topic)]

    K -.->|"consume from O_pg_writer (cache warm)"| P

    K -->|consume + batch| PGW[Postgres Writer Service]
    PGW -->|idempotent upsert| PG[(PostgreSQL)]

```

#### Efficient Writes

- stateful API that caches person data on pods
- API can receive a list of property updates and only update/writes the changed property fields, doesn't replace the entire property field

TBD:

- what technology to use for the cache? how does a pod recover from a crash/restore its cache? how long does that take? does every pod crash result in service disruption? for how long?

#### Durability

- with writes going to the cache, the head of application state now lives in the cache (single point of failure), not in Postgres (durable store). we need durability
- after each person write to the cache and before we ack to client, we emit a message to kafka (acting as a distributed log)
- the head of our application state can always be materialized through replaying Kafka messages onto the outdated PG state
- a separate PG writer service consumes messages from the kafka topic and batch write to PG
- maintains a committed offset per partition, i.e. O_pg_writer(P)
- this offset is the boundary:
- below the offset: state is durably in Postgres
- at or above the offset: state is PG + the changes in our distributed log (the kafka topic)

#### Cache warming on partition handoff

When a partition moves between leader pods, the new owner repopulates
its cache by replaying the slice of `personhog_updates` that the
writer has not yet persisted to PG. The warming pipeline lives in
`src/warming.rs` and is invoked by `LeaderHandoffHandler::warm_partition`
when the handoff reaches the `Warming` phase (see
`personhog-coordination`'s README for the full
`Freezing → Draining → Warming → Complete` protocol).

**Pre-conditions established by the protocol:**

- `Freezing` collected freeze quorum from every router → no router
  forwards to the old owner anymore.
- `Draining` waited for the old owner's in-flight handlers to complete
  and produced `PodDrainedAck` → no producer can append to this
  partition's Kafka log.

By the time `Warming` runs, the partition's HWM is therefore stable
and warming can consume to a known endpoint without racing producers.

**The pipeline:**

1. Query the writer's consumer group's committed offset
   (`O_pg_writer(P)`) via a short-lived OffsetFetch consumer. Anything
   at or after this offset still needs to be in cache; anything below
   is already durable in PG.
2. Resolve the start offset: `committed_offset - lookback_offsets`,
   clamped to the partition's earliest available offset. The lookback
   is a configurable safety margin against momentary races between
   the writer's commit and our read of it.
3. `assign()` (not `subscribe()`) the warming consumer to the
   partition at the resolved start offset and consume until HWM.
4. Buffer decoded records locally; only commit them to the cache
   after the entire range warms successfully via
   `PartitionedCache::install_warmed_partition`, which builds the
   populated `PersonCache` first and publishes it via a single
   `DashMap::insert`. Any decode/IO failure mid-range aborts warming
   with no observable cache mutation, preventing a partial cache from
   silently masking PG fallback reads.

**Configurable knobs** (env vars, see `src/config.rs`):

- `WRITER_CONSUMER_GROUP` — group whose committed offset bounds the
  warming range.
- `WARM_LOOKBACK_OFFSETS` — safety margin to rewind past the writer's
  commit.
- `WARM_COMMITTED_OFFSETS_TIMEOUT_SECS`, `WARM_FETCH_WATERMARKS_TIMEOUT_SECS`,
  `WARM_RECV_TIMEOUT_SECS` — Kafka call timeouts.
- `WARM_RETRY_MAX_ATTEMPTS`, `WARM_RETRY_INITIAL_BACKOFF_MS`,
  `WARM_RETRY_MAX_BACKOFF_MS` — retry policy for transient Kafka
  metadata failures.

The synchronous rdkafka calls (`committed_offsets`, `fetch_watermarks`)
run on the blocking pool via `tokio::task::spawn_blocking` so a slow
broker can't park the runtime thread.

#### vNode ownership

The pod participates in `personhog-coordination`'s handoff protocol
via `LeaderHandoffHandler` (see `src/coordination/mod.rs`):

- `drain_partition_inflight` (Draining): waits for `InflightTracker`'s
  per-partition counter to drop to zero, then writes `PodDrainedAck`.
  Combined with the produce path's sync-await on Kafka delivery, this
  gives the protocol the guarantee that "no in-flight" implies
  "every acked write durable in Kafka."
- `warm_partition` (Warming): see the section above.
- `release_partition` (Complete): drops the partition's cache slot
  via `PartitionedCache::drop_partition` once the routing table has
  flipped to the new owner.

#### Request Path

```mermaid
graph TB
    C[Client] -->|"UPDATE /persons/<id>"| R

    subgraph R[Router]
        direction TB
        PARSE[Parse request] --> DECIDE{Consistent Read/Write?}
        DECIDE -->|"Yes"| HASH["Hash person_id → vnode"]
        HASH --> WATCH["Lookup vnode → pod(from metadata store cache)"]
    end

    WATCH -->|"handoff"| MS[(Metadata Store)]
    MS -->|"vnode assignments"| LOOKUP

    LOOKUP --> POD

    subgraph POD[PersonHog Leader BE]
        direction TB
        VALIDATE[Validate ownership] --> COMPUTE[Compute write]
        COMPUTE --> CACHE[Update in-memory cache]
        CACHE --> KAFKA[Durably store to Kafka]
    end

    KAFKA --> ACK[Ack to client]

```
