# personhog-identity

The identity service of the personhog cluster. It owns the identity graph — distinct id resolution and get-or-create orchestration — per the personhog-identity saga RFC.

Person state spans two planes:

- the sync plane (Postgres primary), which owns existence, identity topology, and lifecycle scalars
- the async plane (leader + changelog), which owns person property content

`GetOrCreatePersonByDistinctId` / `GetOrCreatePersonsByDistinctIds` orchestrate both planes so a single ack covers both: `created = true` means the person stub is committed in Postgres AND the initial `$set`/`$set_once` are durable in the leader's changelog. Person-destroying operations (two-person merges, deletes) run as lifecycle sagas hosted in this service (`src/lifecycle/`).

## How get-or-create works

1. Batch resolve `(team_id, distinct_id)` keys on the Postgres primary (one UNNEST probe).
2. Misses get a person stub — deterministic uuidv5 of `team_id:distinct_id`, version 0, empty properties — plus distinct id rows, in one multi-row transaction with per-row `ON CONFLICT` handling. Extra distinct ids always get version 1: they can't be proven history-free, and version 1 is safe either way (the override it emits is a transient no-op when no events exist).
3. Created stubs fan out initial properties to their owning leaders through the router (`UpdatePersonProperties` with `x-team-id`/`x-person-id` routing headers), with bounded concurrency.

Races resolve per key, never failing the rest of a batch: a concurrent create conflicts on the deterministic uuid and returns the winner (`created = false`); a distinct id concurrently mapped elsewhere rolls back only that stub and re-resolves. A crash between the stub commit and the leader ack surfaces as a per-key error; the retried key resolves to the stub (`created = false`) and the caller applies properties through the normal update path.

### Coalesced stub transactions

Ingestion sends one entry per get-or-create call, so each new person costs its own transaction and commit.
With `STUB_CREATE_WORKERS` above 0, a fixed set of worker tasks runs every stub-creation transaction, for get-or-create and for merge targets (`src/storage/coalesce.rs`).
A worker takes one queued call and every call already queued behind it, up to `STUB_CREATE_MAX_BATCH_DISTINCT_IDS` distinct ids (default 50), into one transaction.
Calls share a transaction only when they would otherwise wait for a worker, so latency does not change while a worker is free.
`STUB_CREATE_BATCH_WAIT_MS` above 0 changes that: a free worker holds its first call for up to that long, counted from when the call was queued, so that calls which arrive in the meantime share its transaction.
The wait ends early when the batch reaches its distinct id cap, and it adds up to that many milliseconds to a get-or-create call.
A waiting worker holds the queue, so one batch forms at a time however many workers there are.
Calls that share a distinct id never share a transaction, so each call gets the outcome its own transaction would give.
When a shared transaction fails with a query error or a timeout, the worker reruns each call in its own transaction, so the failure reaches only the call that caused it.
The reruns run at the same time, so a rerun that waits on a lock delays only its own call.
A connection error or an exhausted pool fails every call in the batch, and callers retry as they do for any storage error.
The worker count also caps the heavy connections that stub creation can hold, so keep it well below `HEAVY_MAX_PG_CONNECTIONS`.
At most `STUB_CREATE_MAX_QUEUED_CALLS` calls (default 1000) wait for a worker, and a call that no worker has started stops waiting after `HEAVY_ACQUIRE_TIMEOUT_SECS`.
A call refused either way gets the error a heavy-pool acquire timeout gives: UNAVAILABLE from get-or-create, so the caller retries on another pod, and INTERNAL from the merge target path.
The default, `STUB_CREATE_WORKERS=0`, runs each call in its own transaction on the calling task.
With workers on, pool and query metrics for stub creation carry `client="batched"` and `method="StubCreateBatch"` in place of the caller's labels.
`personhog_identity_stub_create_callers_per_batch` shows how many calls share each transaction, `personhog_identity_stub_create_queue_wait_ms` shows how long a call waits for a worker, `personhog_identity_stub_create_batch_reruns_total` counts shared transactions that fell back to one transaction per call, and `personhog_identity_stub_create_rejected_total{reason}` counts calls refused for a full queue or a long wait.

### Coalesced attaches

A MergePersons call that attaches personless distinct ids writes them in one autocommit statement, so each call pays its own commit.
`ATTACH_WORKERS` above 0 runs every attach on its own set of worker tasks, with the same batching, rerun and refusal rules as stub creation: `ATTACH_MAX_BATCH_DISTINCT_IDS` (default 50) caps the distinct ids of one statement, and `ATTACH_MAX_QUEUED_CALLS` (default 1000) caps the calls that wait.
A batch of more than one call runs as one `attach_batch_mappings` statement (`attach_batch_mappings_with_outbox` with outbox writes on), with the same per-row guards and outcomes as a lone attach.
That statement waits at most 100 ms for one row lock and runs at most 250 ms in total, because every row's guards read the snapshot from when the statement started; a batch that times out reruns each call alone.
A batch of one runs the lone `attach_mappings` statement.
A refused attach fails its MergePersons call with INTERNAL, as a heavy-pool acquire timeout does.
The default, `ATTACH_WORKERS=0`, runs each attach on the calling task.
With workers on, attach pool and query metrics carry `client="batched"` and `method="AttachBatch"`, and the coalescer metrics are the stub-creation ones with `attach` in place of `stub_create`, for example `personhog_identity_attach_callers_per_batch`.
`ATTACH_BATCH_WAIT_MS` is the attach counterpart of `STUB_CREATE_BATCH_WAIT_MS`, with the same default of 0.
`STUB_CREATE_WORKERS` plus `ATTACH_WORKERS` caps the heavy connections the two can hold; startup warns when the sum reaches `HEAVY_MAX_PG_CONNECTIONS`.

## Layout

- `src/service/` — gRPC surface; `mod.rs` is dispatch-only, each RPC family has its own module (`get_or_create.rs`)
- `src/storage/` — `IdentityStorage` trait + Postgres implementation (primary only; identity reads must never be stale)
- `src/pools.rs` — the two primary pools, split by how long a statement holds its connection: fast (resolution, op bookkeeping) and heavy (stub creation, attach, saga transactions, GC), sized by `MAX_PG_CONNECTIONS` and `HEAVY_MAX_PG_CONNECTIONS`
- `src/leader.rs` — `PropertyWriter` trait + router-backed implementation
- `src/lifecycle/` — the lifecycle engine: merge and delete sagas, sweeper, GC
- Shared person primitives (row type, storage errors, uuidv5 scheme) live in `personhog-common::persons`

## Running locally

```bash
bin/start-rust-service personhog-identity   # gRPC :50055, metrics :9108
```

Tests need the persons database (`posthog_persons`) with `rust/persons_migrations` applied:

```bash
cargo test -p personhog-identity
```

## Query tags

Every statement carries `/* service='personhog-identity', operation='<name>' */` in front, the SQLCommenter shape both pganalyze and pgcollector parse, so load and latency can be cut by code path.
Compile-time checked queries get it from `op = "..."` on the `mirrored_query*!` macros; statements built at runtime wrap their SQL in `personhog_common::query_tag!("<name>", sql)`.
Operation names are `<saga or store>_<step>_<what>`, for example `merge_flip_lock_persons` or `stub_create_mappings`.
See `rust/pgcollector/docs/query-tags.md` for the key vocabulary.

## Parked lifecycle ops

A lifecycle op parks when the leader answers a semantic refusal after the point of no return: retrying a definitive refusal cannot succeed, so the op holds its fences and only an explicit retry under the same op id resumes it (the sweeper is barred). Refusals before the point of no return abort instead, recording `skipped_refused` for their sources and releasing fences in the same settlement. The sweeper re-drives interrupted sagas to a terminal state and defaults on; a fleet that disables it converts every orphaned saga into fences an operator must clear. The surface is the `personhog_lifecycle_ops_parked` gauge and the park's ERROR log carrying the op id and reason; resolution is a retry with the recorded op id.

## Ingestion warnings

The service publishes in-product ingestion warnings for the merge verdicts it settles, straight to the warnings topic as finished v2 rows (`source = "personhog-identity"`), through the shared `common-ingestion-warnings` crate's direct-row transport (`src/warnings.rs`).
A verdict warns here when it is final under retry and decided by this service alone; the ingestion consumer keeps the warnings that depend on its own retries or merge-mode policy.

| Verdict | Warning | Emitted from |
| --- | --- | --- |
| source illegal, oversized, or NUL-bearing (`skipped_illegal`) | `cannot_merge_with_illegal_distinct_id` | entrance |
| target illegal, oversized, or NUL-bearing (request rejected) | `cannot_merge_with_illegal_distinct_id`, one per source | entrance |
| `skipped_already_identified` | `cannot_merge_already_identified` | entrance (inline) or saga terminal record |
| `skipped_refused`, `error` | `merge_settled_failure` | saga terminal record |
| `skipped_conflict` replayed as settled by a recorded op | `merge_race_condition` | saga terminal record |
| `skipped_conflict` in a claim abort, `skipped_move_limit`, call failures | none here; the caller's | - |

Saga warnings emit once per committed terminal record, so an op the sweeper finishes warns exactly as one the RPC drove, and a retry that attaches to a finished op emits nothing new.
Inline verdicts re-emit when a retry re-classifies, the same at-least-once the response has; the producer throttles per team, warning type, and source distinct id (one an hour), with a per-pod per-type budget behind it.

`INGESTION_WARNINGS_ENABLED` (default `false`) turns the producer on; `INGESTION_WARNINGS_KAFKA_HOSTS`, `INGESTION_WARNINGS_KAFKA_TLS`, and `INGESTION_WARNINGS_TOPIC` (default `clickhouse_ingestion_warnings`) name the destination, a cluster separate from any event producer with a fixed fire-and-forget policy (leader ack, no retries, bounded queue).
Keep it off until the ingestion consumer stops emitting the same verdicts itself, or customers see each refusal twice.
Health reads from `ingestion_warnings_emitter_enabled{reason}` (absent when off, `0` when enabled but unusable) and `ingestion_warnings_total{source="personhog-identity",outcome}` (`emitted`, `throttled`, `delivered`, `delivery_failed`, ...).

## Delete retries must present a byte-stable request

A same-op-id delete retry is compared byte-for-byte against the frozen request, so the caller must present the identical `person_ids` list (same order, same duplicates) on every retry; a mismatch is refused `op_id_reused` and the deletion must be reissued under a fresh op id.

## Publish outbox contract

`personhog-publisher` (`src/bin/publisher.rs`, `src/publish/`) is a separate deployment that drains the `person_publish_outbox` table identity writes, and nothing orders the two deployments.
Everything the publisher reads is a contract between the two binaries:

- the outbox columns and the two row shapes the `CHECK` constraints keep exclusive: a mapping row (`create`, `attach`, carrying `person_uuid`, `distinct_id` and `version`) and an op pointer (`merge_op`, `delete_op`, carrying `op_id`, the cursor `cursor_person_id` and `cursor_mapping_ordinal`, `attempts`, `last_error` and `given_up_at`)
- the `lifecycle_op` row a pointer resolves against (`op_type`, `completed_at`, `outcome`) and the `lifecycle_op_person.moved` array of `{distinct_id, version}` entries on source and victim rows, published in `(person_id, position in moved)` order
- the lifecycle GC guard, which keeps an op while a pointer to it exists

A change to any of these lands in the publisher first, in its own PR, and in identity (the writer) in a later PR once that publisher is deployed everywhere.
Until the identity change has rolled out the publisher reads both the old and the new shape, and a column identity stops writing stays in the table while a pending row can still carry it.
The schema change itself is a third PR ahead of both, as the migrations check requires.
