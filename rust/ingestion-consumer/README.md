# ingestion-consumer

Rust Kafka consumer that routes analytics events to Node.js ingestion workers over ordered gRPC streams with sticky per-key assignment.
It reads batches from Kafka, groups messages by Kafka message key, pins each key to a worker (preserving per-key ordering; unkeyed messages can go to any worker), sends each worker's sub-batches on its `WorkerIngest` stream, and submits offsets for commit only through each partition's accepted prefix.
Worker health combines active `/_ready` probes with passive send outcomes; workers that leave the pool drain gracefully — in-flight work finishes, new work for their keys defers and re-routes to survivors in order.

## Ordering sentinels

`order_sentinel.rs` and `commit_sentinel.rs` expose ordering checks and commit observations as alertable metrics (enabled by default; see the module docs for semantics).
The poll-span check applies only at `poll` completion granularity; broker-offset observation and per-key checks also apply at `group` granularity.

| Guarantee | Violations (must stay 0) | Denominator / supporting |
| --- | --- | --- |
| Retired poll spans are contiguous and monotonic per partition (`poll` granularity); settled polls are non-empty | `ingestion_consumer_commit_violations_total{kind=gap\|out_of_order\|overlap\|empty}` | `ingestion_consumer_commits_checked_total` counts checked partition spans, not submissions |
| Broker offsets catch up to frontiers released for commit | `ingestion_consumer_commit_confirmation_lag{topic,partition}` persistently > 0 | `ingestion_consumer_committed_offset{topic,partition}` is the released-attempt offset, not broker confirmation; `ingestion_consumer_broker_committed_offset{topic,partition}`, `ingestion_consumer_last_successful_commit_timestamp_seconds`, `ingestion_consumer_commit_monitor_errors_total` |
| Per-key sends are in offset order, never re-sent after ACK (keyed messages only) | `ingestion_consumer_key_order_violations_total{kind=intra_group_disorder\|resend_after_ack}` | `ingestion_consumer_key_replays_total` (legal at-least-once retries), `ingestion_consumer_key_sentinel_keys`, `ingestion_consumer_key_sentinel_unkeyed_total` (skipped null-key messages) |
| Messages enter the worker pipeline in per-key offset order (end to end) | `ingestion_api_out_of_order_messages_total` (worker-side) | `ingestion_api_replayed_messages_total`, `ingestion_api_order_sentinel_keys` |

Commit success can't be observed via rdkafka's `commit_callback` — librdkafka drops the result of manual async commits (no conf-level `offset_commit_cb` is ever registered by rust-rdkafka, and only sync commits attach a reply queue).
Instead a background commit monitor fetches the group's broker-committed offsets every 30s (one OffsetFetch) and compares them to frontiers released by the pacer for attempted submission. `commit_confirmation_lag` excludes pending frontiers; it can remain positive after client submission fails or when submitted commits are not landing (e.g. a stuck coordinator), and can be transiently positive between monitor observations.
Alerts should gate on `ingestion_consumer_offset_commits_total > 0` — an idle consumer that never committed has nothing to confirm.

Both sides default to enabled and have kill switches: `CONSUMER_ORDER_SENTINEL_ENABLED` here, `INGESTION_API_FEED_ORDER_SENTINEL_ENABLED` (plus `INGESTION_API_FEED_ORDER_SENTINEL_MAX_KEYS`) on the worker.
The rebalance metrics from the consumer context stay on regardless, and the `consumer_id`/`replay` request fields are always stamped so either side can be toggled independently.
The worker-side check lives in `nodejs/src/ingestion/api/feed-order-sentinel.ts`, fed by the `consumer_id` (process incarnation) and `replay` fields the transport stamps on every sub-batch.
It measures the invariant at its end point: the worker's grouping stage processes each key strictly in feed order, so "fed in offset order per key" is "processed in order per key".
Rebalances reset all baselines (`ingestion_consumer_rebalances_total{event}` counts them), so partition handoffs don't fire false positives.
Null-key messages (e.g. overflow rerouting) are excluded from both checks: the producer deliberately forfeits per-key order for them, and the consumer routes each one individually rather than pinning it, so there is no invariant to check on either side.

## Offset ledger

The consumer holds the per-partition offset ledger from `common/kafka-consumer`, which determines the safe commit frontier.
Every delivered message is charged to its partition's ledger during collection. Accepted work completes its offsets there; each partition's frontier is one past its longest completed prefix.
A settlement without a new frontier produces no new commit candidate for that partition. An incomplete prefix can block later accepted offsets indefinitely; the pacing interval does not bound that wait.
At `poll` granularity, `ingestion_consumer_commits_skipped_total{reason}` counts poll settlements with no frontier: `rejected` means the ledger dropped every slice (expected around a rebalance), and `no_frontier` means a slice settled but an incomplete prefix blocked every affected partition.
Each frontier passes through the commit sentinel (`commit_sentinel.rs`) into the commit pacer (`commit_pacer.rs`). The consumer checks for due frontiers after poll retirement, when servicing completions, at the top of each loop turn, and on the one-second completion-wait heartbeat; exit also takes pending frontiers regardless of the interval.
`CONSUMER_COMPLETION_GRANULARITY` selects the unit that settles against the ledger: `poll` (the default) settles a whole poll once every one of its groups is accepted, oldest poll first, and `group` settles each group's offsets when its completion is serviced.
At `group` granularity, a stalled key blocks the ledger prefixes of the partitions it occupies, while other partitions can make commit progress for already-admitted work. Poll admission is still capped by `CONSUMER_MAX_BACKGROUND_TASKS`, and slots are freed only as whole polls retire oldest first: a stalled oldest poll can still prevent new admission across partitions.
That admission cap does not bound accepted-but-uncommitted replay exposure: retired polls can leave frontiers pending in the pacer while more work is admitted, and a submitted async commit may not yet have reached the broker.
At `poll` granularity the sentinel compares each retired poll's partition span to the end of the previous checked span. At `group` granularity frontiers bypass this check because a frontier no longer maps to one poll's slice.
`kafka_consumer_ledger_gap_offsets_total` counts undelivered filler offsets when a taken frontier drains them from the current ledger window. It does not observe gaps before the window's initial baseline or preserve a checked-span baseline across ledger resets; it is not equivalent coverage for the retired poll-span check, including its overlap and out-of-order checks.
At `poll` granularity the pacer adds no delay to frontiers produced by poll retirement.
At `group` granularity the pacer coalesces the latest frontier per partition. `CONSUMER_COMMIT_INTERVAL_MS` (default 500) is minimum spacing between normal non-empty releases for commit submission, not a maximum accepted-work latency. There is no dedicated pacing timer: completion servicing can wait through multiple collections while admission slots remain, and due frontiers can wait for loop servicing or the completion-wait heartbeat.
The sentinel records an attempted offset when the pacer releases it, before the consumer calls Kafka. Pending frontiers are excluded from `ingestion_consumer_commit_confirmation_lag`; released attempts are neither proof of successful client submission nor broker confirmation.
The pacer performs no I/O. The consumer submits released offsets asynchronously, and the commit monitor (`commit_monitor.rs`) separately reports broker-committed offsets.
Exit flushing is best-effort async submission of pending frontiers, bypassing the interval. It does not await broker confirmation or guarantee no replay after restart.
On revoke, a partition's pending frontier is dropped along with its ledger and sentinel baselines, rather than flushed. This prevents a later pacer release for the departed partition; it does not retract submissions already handed to Kafka.
The ledger emits its own metrics, so any consumer built on the crate reports the same series.
`kafka_consumer_ledger_uncommitted_offsets{topic,partition}` gauges each partition's window depth; `kafka_consumer_ledger_uncommitted_events` and `kafka_consumer_ledger_uncommitted_bytes` gauge the charge those offsets carry, where bytes is the payload plus key plus headers of each message.
`kafka_consumer_ledger_stale_slices_total{stage}` counts charges and settlements dropped because their partition was reassigned while they were in flight; a few around a rebalance are expected.
`kafka_consumer_ledger_errors_total{stage,kind}` counts contract violations in the ledger's accounting; it must stay 0. A violation resets that partition's ledger and the consumer keeps running; the consumer logs the rejected slice with the batch and ledger generations and the window depth before the reset.

## Debug API

Set `DEBUG_API_ENABLED=true` **and** `DEBUG_API_SECRET` to mount a real-time debug API on the health server (default `:3301`), for dev and incident debugging; off by default.
Every request must present the secret as `X-Debug-Api-Secret`; enabling without a secret fails closed (nothing is mounted).
The secret is dedicated to this control-plane→consumer hop — deliberately not `INTERNAL_API_SECRET` (see `.agents/security.md`).
The ingestion control plane UI consumes these endpoints to render the consumer's live state.
`debug_recorder.rs` keeps a bounded in-memory buffer of structured lifecycle events — batch dispatch/assignment, poll completion, commit submission, deferrals and flushes, worker health and membership — and never influences routing. Poll completion is not a commit submission, and commit submission is not broker confirmation.

- `/debug/load` — cheap JSON snapshot (worker health + dispatcher in-flight/pins/stash), safe to poll fast.
- `/debug/state` — the same plus the retained event backlog.
- `/debug/events` — SSE stream: backlog replay, then live events (concurrent subscribers capped at 8; 429 beyond).

## Testing

- `cargo test -p ingestion-consumer --lib` — unit tests.
- `cargo test -p ingestion-consumer --tests` — integration suites; the e2e suite requires Kafka on `localhost:9092`.

## Follow-up work

Known gaps in priority order.
The details below are grounded in the current code — re-verify limits and paths before building on them.

### 1. Sub-batch size cap — done

Sub-batches are split at `INGESTION_TRANSPORT_MAX_BODY_BYTES` (default 10 MiB) into consecutive frames on the worker stream, under the worker's `INGESTION_API_GRPC_READ_MAX_BYTES` (32 MiB).

### 2. Commit-error observability — done

Addressed by the commit monitor plus `SentinelContext` (`order_sentinel.rs`): broker-committed offsets are polled and compared against attempted commits (see "Ordering sentinels" above), and rebalance callbacks log assignment changes and reset the ordering sentinels.
The originally envisioned offset-commit callback turned out to be unreachable for manual async commits (librdkafka drops their results unless a conf-level `offset_commit_cb` is registered, which rust-rdkafka never does) — hence the polling design.
Remaining: alert rules on the new metrics.

### 3. DLQ for poison messages

A message a worker permanently rejects (a nack on every delivery) has no dead-letter path: after the flush timeout the batch fails and the process crash-loops on redelivery.
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
