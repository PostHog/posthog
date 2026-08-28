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

## Parked lifecycle ops, and what bounds them

A lifecycle op parks when a leader semantic refusal reaches the engine: retrying a definitive refusal cannot succeed, and only an explicit retry under the same op id resumes a parked op (the sweeper is barred). Two design facts bound what a park can wedge:

- Refusals before the point of no return never park. For the merge driver this is structural: it aborts pre-flip refusals, releasing fences in the same settlement. For the delete driver it holds only because `FencePerson` mints no semantic refusal today — the delete driver has no abort path past its first step, so adding a semantic refusal to the fence RPC requires building one first (a guard comment in `delete.rs`'s seal marks the spot). Non-semantic failures (a foreign fence at seal, a partition mismatch, capacity) are transient in both drivers: the lease releases and the caller retries. Parks therefore only occur on the release path, after the flip (merge) or the destroying transaction (delete).
- A post-release park whose refusal was `release-unverified` holds ghost fences for the refused source: the live mark the release verification demanded is gone, and the leader's lazy healer removes exactly such fences on the next rejected write. A sibling source whose release failed only transiently in the same fan-out can keep a live-marked fence while the op parks; that one clears when a retry resumes the op and re-releases, so it is bounded by the retry loop rather than by the healer.

The residual is a park whose mark is live but whose sealed state fails verification (`uuid-mismatch`): corrupt state, where releasing the fence would be the wrong move, so the fence holds by design and writes to that person bounce until an operator intervenes. The surface is the `personhog_lifecycle_ops_parked` gauge and the park's ERROR log carrying the op id and reason; resolution is a retry with the recorded op id once the state is repaired, which resumes the parked op.

A definitive refusal before the flip is the opposite posture: the abort records `skipped_refused` for its sources, and the caller settles each pair as a counted, warned, acked loss rather than wedging. A leader configuration error (a missing or lagged fallback pool) therefore surfaces as the settled-loss counter spiking toward the merge rate, loudly but without stalling partitions — deliberate, because the recorded verdict replays for the retention window, so a wedge would outlive the fix by up to that long. The same window means the losses recorded during the error survive the fix: those pairs stay lost under their op ids, and only the customer's next identify, under a fresh op id, merges them.

The sweeper is part of this contract, not an optimization. A caller that loses a claim race drops its merge and never presents that op id again — a redelivered fold can plan different pairs and derive a different id — so an interrupted saga can be orphaned with its sources still fenced. The sweeper is what re-drives it to a terminal state; it defaults on, and a fleet that disables it converts every such orphan into frozen fences an operator must clear.

What the caller does with a park is part of the wedge's shape. The refusal passes through to ingestion as a no-verdict failure, so the batch fails, drops the team's memoized resolutions, and redelivers; each redelivery's retry unparks the op, re-drives into the same refusal, and re-parks. The partition therefore wedges loudly (fail-closed, by design) while the parked gauge dips briefly at every unpark — read a flapping gauge together with the batch-failure rate rather than as parks resolving.

## Rolling out changes to the retry-match comparison

The entrance compares a retry against the recorded op and refuses a mismatch with the `op_id_reused` semantic slug, which the ingestion store treats as a settled, deterministic verdict: it acks the event with the merge lost. That treatment is only safe against this service's drift-tolerant comparison (`same_merge`, which strips fields that legitimately differ between deliveries of one event). An older binary's strict comparison emits the same slug for ordinary drifted redeliveries, so identity must be fully rolled before an ingestion deployment that trusts the slug runs personhog-authoritative; under shadow the refusal never reaches a caller and the ordering does not matter.

## Delete retries must present a byte-stable request

The delete path has no drift-tolerant retry comparison: a same-op-id retry is compared against the frozen request exactly, so the caller must present the identical `person_ids` list — same order, same duplicates — on every retry, or the retry is refused `op_id_reused` and the deletion must be reissued under a fresh op id. Normalizing server-side would change the frozen shape old rows carry and refuse their retries instead, so the stability requirement sits with the caller.
