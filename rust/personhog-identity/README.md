# personhog-identity

The identity service of the personhog cluster. It owns the identity graph — distinct id resolution and get-or-create orchestration — per the personhog-identity saga RFC.

Person state spans two planes:

- the sync plane (Postgres primary), which owns existence, identity topology, and lifecycle scalars
- the async plane (leader + changelog), which owns person property content

`GetOrCreatePersonByDistinctId` / `GetOrCreatePersonsByDistinctIds` orchestrate both planes so a single ack covers both: `created = true` means the person stub is committed in Postgres AND the initial `$set`/`$set_once` are durable in the leader's changelog. The identity service never runs a saga; person-destroying operations (two-person merges, deletes) belong to the lifecycle manager.

## How get-or-create works

1. Batch resolve `(team_id, distinct_id)` keys on the Postgres primary (one UNNEST probe).
2. Misses get a person stub — deterministic uuidv5 of `team_id:distinct_id`, version 0, empty properties — plus distinct id rows, in one multi-row transaction with per-row `ON CONFLICT` handling. Extra distinct ids always get version 1: they can't be proven history-free, and version 1 is safe either way (the override it emits is a transient no-op when no events exist).
3. Created stubs fan out initial properties to their owning leaders through the router (`UpdatePersonProperties` with `x-team-id`/`x-person-id` routing headers), with bounded concurrency.

Races resolve per key, never failing the rest of a batch: a concurrent create conflicts on the deterministic uuid and returns the winner (`created = false`); a distinct id concurrently mapped elsewhere rolls back only that stub and re-resolves. A crash between the stub commit and the leader ack surfaces as a per-key error; the retried key resolves to the stub (`created = false`) and the caller applies properties through the normal update path.

## Layout

- `src/service/` — gRPC surface; `mod.rs` is dispatch-only, each RPC family has its own module (`get_or_create.rs`)
- `src/storage/` — `IdentityStorage` trait + Postgres implementation (primary pool only; identity reads must never be stale)
- `src/leader.rs` — `PropertyWriter` trait + router-backed implementation
- Shared person primitives (row type, storage errors, uuidv5 scheme) live in `personhog-common::persons`

## Running locally

```bash
bin/start-rust-service personhog-identity   # gRPC :50055, metrics :9108
```

Tests need the persons database (`posthog_persons`) with `rust/persons_migrations` applied:

```bash
cargo test -p personhog-identity
```

## Parked lifecycle ops

A lifecycle op parks when the leader answers a semantic refusal after the point of no return: retrying a definitive refusal cannot succeed, so the op holds its fences and only an explicit retry under the same op id resumes it (the sweeper is barred). Refusals before the point of no return abort instead, recording `skipped_refused` for their sources and releasing fences in the same settlement. The sweeper re-drives interrupted sagas to a terminal state and defaults on; a fleet that disables it converts every orphaned saga into fences an operator must clear. The surface is the `personhog_lifecycle_ops_parked` gauge and the park's ERROR log carrying the op id and reason; resolution is a retry with the recorded op id.

## Delete retries must present a byte-stable request

A same-op-id delete retry is compared byte-for-byte against the frozen request, so the caller must present the identical `person_ids` list (same order, same duplicates) on every retry; a mismatch is refused `op_id_reused` and the deletion must be reissued under a fresh op id.
