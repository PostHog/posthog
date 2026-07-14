# ingestion-consumer

Rust Kafka consumer that routes analytics events to Node.js ingestion workers over HTTP with sticky per-`distinct_id` assignment.
It reads batches from Kafka, groups messages by `token:distinct_id`, pins each key to a worker (preserving per-person ordering), scatters sub-batches over HTTP, and commits offsets only after every message in the batch is accepted.
Worker health combines active `/_ready` probes with passive send outcomes; workers that leave the pool drain gracefully — in-flight work finishes, new work for their keys defers and re-routes to survivors in order.

## Ordering sentinels

`order_sentinel.rs` turns the consumer's two core guarantees into always-on, alertable metrics (see the module docs for semantics).
Each guarantee has a violation counter that must stay flat and a denominator that must grow:

| Guarantee | Violations (must stay 0) | Denominator / supporting |
| --- | --- | --- |
| Commits are contiguous, monotonic, non-empty per partition | `ingestion_consumer_commit_violations_total{kind=gap\|out_of_order\|overlap\|empty}` | `ingestion_consumer_commits_checked_total`, `ingestion_consumer_committed_offset{topic,partition}` |
| Async commits actually succeed | `ingestion_consumer_commit_confirmation_lag{topic,partition}` persistently > 0 | `ingestion_consumer_broker_committed_offset{topic,partition}`, `ingestion_consumer_last_successful_commit_timestamp_seconds`, `ingestion_consumer_commit_monitor_errors_total` |
| Per-key sends are in offset order, never re-sent after ACK (keyed messages only) | `ingestion_consumer_key_order_violations_total{kind=intra_group_disorder\|resend_after_ack}` | `ingestion_consumer_key_replays_total` (legal at-least-once retries), `ingestion_consumer_key_sentinel_keys`, `ingestion_consumer_key_sentinel_unkeyed_total` (skipped null-key messages) |
| Messages enter the worker pipeline in per-key offset order (end to end) | `ingestion_api_out_of_order_messages_total` (worker-side) | `ingestion_api_replayed_messages_total`, `ingestion_api_order_sentinel_keys` |

Commit success can't be observed via rdkafka's `commit_callback` — librdkafka drops the result of manual async commits (no conf-level `offset_commit_cb` is ever registered by rust-rdkafka, and only sync commits attach a reply queue).
Instead a background commit monitor fetches the group's broker-committed offsets every 30s (one OffsetFetch) and compares them to what was attempted: `commit_confirmation_lag` is transiently positive while async commits are in flight, and persistently positive when commits are submitted but not landing (e.g. a stuck coordinator).
Alerts should gate on `ingestion_consumer_offset_commits_total > 0` — an idle consumer that never committed has nothing to confirm.

Both sides default to enabled and have kill switches: `CONSUMER_ORDER_SENTINEL_ENABLED` here, `INGESTION_API_FEED_ORDER_SENTINEL_ENABLED` (plus `INGESTION_API_FEED_ORDER_SENTINEL_MAX_KEYS`) on the worker.
The rebalance metrics from the consumer context stay on regardless, and the `consumer_id`/`replay` request fields are always stamped so either side can be toggled independently.
The worker-side check lives in `nodejs/src/ingestion/api/feed-order-sentinel.ts`, fed by the `consumer_id` (process incarnation) and `replay` fields the transport stamps on every `/ingest` request.
It measures the invariant at its end point: the worker's grouping stage processes each key strictly in feed order, so "fed in offset order per key" is "processed in order per key".
Rebalances reset all baselines (`ingestion_consumer_rebalances_total{event}` counts them), so partition handoffs don't fire false positives.
Null-key messages (e.g. overflow rerouting) are excluded from the consumer-side key checks: the producer deliberately spreads such a routing key across partitions, forfeiting per-key order, so offsets from different partitions are not comparable and there is no invariant to check. The worker-side check is unaffected — it scopes keys per partition, an invariant that holds for all traffic.

## Debug API

Set `DEBUG_API_ENABLED=true` **and** `DEBUG_API_SECRET` to mount a real-time debug API on the health server (default `:3301`), for dev and incident debugging; off by default.
Every request must present the secret as `X-Debug-Api-Secret`; enabling without a secret fails closed (nothing is mounted).
The secret is dedicated to this control-plane→consumer hop — deliberately not `INTERNAL_API_SECRET` (see `.agents/security.md`).
The ingestion control plane UI consumes these endpoints to render the consumer's live state.
`debug_recorder.rs` keeps a bounded in-memory buffer of structured lifecycle events — batch dispatch/assignment/commit, deferrals and flushes, send retries/exhaustion, worker health and membership — recorded at the same points that emit metrics, and it never influences routing.

- `/debug/load` — cheap JSON snapshot (worker health + dispatcher in-flight/pins/stash), safe to poll fast.
- `/debug/state` — the same plus the retained event backlog.
- `/debug/events` — SSE stream: backlog replay, then live events (concurrent subscribers capped at 8; 429 beyond).

## Testing

- `cargo test -p ingestion-consumer --lib` — unit tests.
- `cargo test -p ingestion-consumer --tests` — integration suites; the e2e suite requires Kafka on `localhost:9092`.

## Follow-up work

Known gaps in priority order.
The details below are grounded in the current code — re-verify limits and paths before building on them.

### 1. Sub-batch size cap and 413 handling (incident-class)

Sub-batches have no size bound: a batch (default 500 messages, each up to ~1 MB of Kafka payload) can merge onto one worker as a single HTTP request, while the worker's express app rejects bodies over 20 MB (`nodejs/src/common/api/router.ts`) with a 413.
The transport treats 4xx as non-retriable, so the same oversized sub-batch re-sends until the deferred-flush timeout, the process exits, Kafka redelivers, and it crash-loops deterministically — a stalled partition triggered by an ordinary burst of large events.
Fix: cap sub-batch payload size at build time (chunks sent sequentially per worker to preserve per-key order), plus a defensive split-in-half retry on 413.

### 2. Commit-error observability — done

Addressed by the commit monitor plus `SentinelContext` (`order_sentinel.rs`): broker-committed offsets are polled and compared against attempted commits (see "Ordering sentinels" above), and rebalance callbacks log assignment changes and reset the ordering sentinels.
The originally envisioned offset-commit callback turned out to be unreachable for manual async commits (librdkafka drops their results unless a conf-level `offset_commit_cb` is registered, which rust-rdkafka never does) — hence the polling design.
Remaining: alert rules on the new metrics.

### 3. DLQ for poison messages

A message a worker permanently rejects (4xx, or persistent `status:"error"`) has no dead-letter path: after the flush timeout the batch fails and the process crash-loops on redelivery.
`poison_batch_fails_safely_without_committing` pins the safe half of the trade-off (never commit past unaccepted messages).
Needs a design pass: DLQ topic, retry budget before giving up, the per-key ordering caveat (DLQ-ing one message then delivering later ones for the same person), and replay ownership.
Non-UTF-8 payloads — currently nulled in `collect_batch` with no metric — should route to the same DLQ as malformed input; a bytes-preserving wire format is not worth it while the producer (capture) guarantees UTF-8 JSON.

### 4. Revoke-aware partition handoff

Sticky pins and the deferral stash are per-process.
During a consumer-group rebalance another instance can start a partition from the last commit while this instance still has uncommitted in-flight work — duplicates and possible cross-pod interleaving per key (`second_consumer_joining_the_group_preserves_all_messages` asserts no loss only, deliberately).
Fix: on partition revoke (cooperative-sticky callback, via the same `ConsumerContext` as item 2), finish and commit in-flight batches for the revoked partitions before acknowledging the revoke.

### Smaller items

- Probe timeout is hardcoded to `probe_interval / 2`; a slow-but-serving worker's `/_ready` can flap it unhealthy. Make it independently configurable.
- Non-UTF-8 payload/header nulling has no metric — add a counter and a rate-limited warning even before the DLQ work lands.
