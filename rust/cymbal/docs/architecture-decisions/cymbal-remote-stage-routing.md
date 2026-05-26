# Cymbal remote stage affinity routing

## Scope

This design covers routing from a Cymbal pipeline/orchestrator process to internal remote stage pods.
It does not change Node ingestion to Cymbal routing. The production remote-stage path now uses explicit per-endpoint selection so the client can observe primary hits, safe fallbacks, endpoint load, and fallback exhaustion.
Routing decisions are now made per event/item and then grouped back into endpoint sub-batches, so the internal remote API remains batch-efficient while affinity and capacity are applied at item granularity.

## Affinity-first with ordered fallbacks

Remote stage clients should ask for an ordered candidate list, not a single pod.
For stages with useful locality, the first candidate should be selected by rendezvous/highest-random-weight hashing over `(stage_id, affinity_key, endpoint)`.
The remaining endpoints, sorted by the same score, become a stable fallback order.

This avoids modulo-only hashing because adding or removing one endpoint does not reshuffle the relative order of all other candidates.
It also makes fallback explicit: later transport code can try the primary, then only the number of fallback candidates allowed by the stage policy.

## Stage-dependent policy

Routing policy is part of the stage contract because different stages have different locality and side-effect risks:

- **Resolution** benefits from symbol and artifact cache locality. Prefer a symbol/cache key when available, falling back to `team_id`.
- **Grouping** is deterministic and repository-light. Default to `team_id` affinity and allow ordinary safe fallbacks.
- **Linking** can create or reopen issues and update suppression/assignment state. Default to `team_id` affinity with strict/no-fallback routing unless operators explicitly loosen it.
- **Alerting** can emit spike-detection side effects. Default to strict/no-fallback routing; when the typed alerting input includes a spike issue, use that issue's `team_id` as the affinity key.
- **Rate limiting** must be explicit. The conservative default is strict `team_id` affinity. Random or broad fallback can change limiter locality and split counters unless the limiter backend is known to be shared correctly.

## Safe and unsafe fallback cases

Fallback is safe when the remote pod rejects the sub-batch before doing stage work.
The clearest example is gRPC `RESOURCE_EXHAUSTED` from admission control or an equivalent pre-work circuit/load rejection.
In that case another candidate can process the same items without duplicating side effects.

Fallback is unsafe when the caller cannot tell whether the first pod performed work.
Timeouts, broken connections after request acceptance, and generic transport errors may happen after repository writes, issue creation, alerting, or other side effects.
Resolution and grouping may later opt into broader retry behavior because their contracts are mostly deterministic, but linking and alerting should not fallback on ambiguous failures by default.

## Policy primitives

`cymbal-core::routing` has transport-neutral endpoint-picker and capacity-partitioning primitives that accept:

- `stage_id`;
- a routing/affinity key;
- a sorted list of resolved pod endpoints;
- per-endpoint local state such as ejected or overloaded;
- per-endpoint item-capacity snapshots and a local reservation ledger for the current dispatch;
- a routing policy.

The picker returns an ordered list of healthy candidates and the partitioner groups assigned items into endpoint sub-batches.
Policies include affinity-first, random, strict affinity with no fallbacks, and a maximum fallback-attempt limit.
Runtime policy overrides are configured with `CYMBAL_REMOTE_ROUTING_POLICIES` as comma-separated `stage_id=mode[:max_fallback_attempts]` entries.
The retained `CYMBAL_REMOTE_ROUTING_ENABLED=false` escape hatch disables affinity, fallback, and observed-load demotion while keeping explicit per-endpoint clients.
`cymbal-server` owns the Cymbal-specific default policy map, env parsing, DNS endpoints, tonic status conversion, metrics, and load metadata plumbing.
