# ingestion-consumer

Rust Kafka consumer that routes analytics events to Node.js ingestion workers over HTTP with sticky per-`distinct_id` assignment.
It reads batches from Kafka, groups messages by `token:distinct_id`, pins each key to a worker (preserving per-person ordering), scatters sub-batches over HTTP, and commits offsets only after every message in the batch is accepted.
Worker health combines active `/_ready` probes with passive send outcomes; workers that leave the pool drain gracefully — in-flight work finishes, new work for their keys defers and re-routes to survivors in order.

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

### 2. Commit-error observability

`commit_offsets` uses `CommitMode::Async` and never observes the result; persistent commit failure (e.g. after a rebalance) is invisible until restart-time redelivery.
Fix: a `ConsumerContext` with an offset-commit callback feeding a failure counter and a last-successful-commit gauge, alertable.
The same context provides rebalance callbacks — log partition assignment changes at minimum.

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
