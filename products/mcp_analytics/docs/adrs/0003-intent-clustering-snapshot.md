# ADR 0003 — Persist intent clusters as a per-team snapshot

- **Status:** Accepted, tracks PR [#58407](https://github.com/PostHog/posthog/pull/58407).
- **Owner:** team-posthog-ai.
- **Related code:**
  - [`products/mcp_analytics/backend/models.py`](../../backend/models.py) — `MCPIntentClusterSnapshot`.
  - [`products/mcp_analytics/backend/intent_clustering.py`](../../backend/intent_clustering.py) — clustering pipeline.
  - [`products/mcp_analytics/backend/tasks/tasks.py`](../../backend/tasks/tasks.py) — `compute_intent_clusters` Celery task.

## Context

The intent clustering surface (`/mcp-analytics/intent-clustering`) renders, per team:

- N clusters, each with a label, an intent count, a sample of intents, and a per-cluster journey Sankey.
- Metadata: distance threshold used, embedding model used, total intents scored, last computed at.

Three options:

1. **Compute on read.** Every request to the surface kicks a clustering run.
2. **Cache the result in Redis.** Run the pipeline on a schedule, cache the JSON, render from cache.
3. **Persist the result in Postgres.** One row per team, status state machine, recompute on demand or on a schedule.

The pipeline is expensive — embedding 500 intents per team plus an agglomerative clustering pass — so option 1 is off the table. Between Redis and Postgres, the deciding factor is durability, observability, and idempotency.

## Decision

Persist clusters in a Postgres table — [`MCPIntentClusterSnapshot`](../../backend/models.py) — one row per team, primary-keyed on `team_id`.

- **Schema.** `team` (PK, `OneToOneField`), `status` (`idle | computing | error`), `error_message`, `clusters` (JSONField — the full denormalised snapshot, including `clusters[]` and `computed_with`), `last_computed_at`, `last_computed_by`. `created_at` / `updated_at` for audit.
- **State machine.** `idle → computing → idle | error → idle` (next successful recompute clears the error). State is updated by the Celery task ([`compute_intent_clusters`](../../backend/tasks/tasks.py)), which is the only writer.
- **Trigger.** v1 is user-triggered ("Recompute" button). The task takes `team_id` and an optional `user_id` for attribution. A scheduled refresh is plausible but deliberately deferred — see future work below.
- **Reads.** The surface reads the row directly. There is no read-time computation. If the task is `computing`, the surface shows the previous snapshot plus a "recomputing…" indicator. If it is `error`, the surface shows the previous snapshot plus the error.

## Consequences

**Positive**

- One write path, one read path. The task is the only writer; surfaces are pure readers. Concurrent requests cannot trigger duplicate runs because `update_or_create(team=..., defaults={status: COMPUTING, ...})` is the gate.
- Snapshot is observable in `django-admin` and queryable like any other Postgres row — useful for debugging "why does this team see no clusters".
- `clusters` is denormalised JSON. The cluster view requires no joins; render is a single `SELECT`. We are not committing to a relational cluster schema we'd then need to migrate.
- Errors are durable. A failed clustering run leaves an `error` row with the message; the user sees something actionable instead of a blank surface.
- Empty-corpus runs persist explicitly via `_save_empty_snapshot` with the parameters used (distance threshold, embedding model, `n_intents = 0`), so "no clusters" is distinguishable from "never ran" at the row level.

**Negative**

- We are storing a denormalised JSON blob. If we ever want to query *across* clusters (e.g. "find teams whose top cluster mentions checkout"), we need to scan and parse, not index. Acceptable: cross-team analysis is not a v1 use case.
- The `OneToOneField` PK means one snapshot per team. If we want side-by-side snapshots (e.g. last week vs this week, A/B-style), we will need a different schema. Acceptable: not a v1 need.
- Celery is the runner. A worker outage means no recomputes until it recovers. The previous snapshot remains readable, so the surface degrades to "stale" rather than "broken".

## Alternatives considered

- **Redis cache.** Rejected. Loses durability across cache evictions, makes errors un-observable (no equivalent of an `error_message` column), and makes the "show stale snapshot while recomputing" UX harder to reason about. Postgres gives all three for free.
- **Relational cluster schema** (`cluster`, `cluster_intent`, `cluster_journey_node`). Rejected for v1. The cluster blob is read whole, written whole, and never mutated piecewise. A relational schema would buy us nothing and cost us a migration the first time the clustering output shape changes — which is exactly the regime we are in.
- **Compute-on-read with aggressive caching at the view layer.** Rejected. Hides the fact that the heavy work is happening; surprise latency spikes; no place to put `last_computed_by` or `error_message` for the surface to show.

## Future work

- **Scheduled refresh.** Once we have a sense of how many teams keep the surface populated, add a Celery beat schedule. The state machine already handles the concurrency case.
- **Snapshot history.** If users start asking "did this cluster exist last week?", we'll add a `history` table keyed on `(team_id, computed_at)` and store the same JSON blob there at completion. Cheap to add later; not worth it until we hear the demand.
