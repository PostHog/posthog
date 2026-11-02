# ingestion-consumer

Rust Kafka consumer that routes analytics events to Node.js ingestion workers over ordered gRPC streams, with at most one request per key in flight.
It reads batches from Kafka, groups messages by Kafka message key, packs each key's messages into requests (preserving per-key ordering; unkeyed messages can go to any worker), sends each request on its worker's `WorkerIngest` stream, and commits each partition's frontier: one past the prefix every worker accepted.
Worker health combines active `/_ready` probes with passive send outcomes; workers that leave the pool drain gracefully: in-flight work finishes, and new work for their keys waits and goes to survivors in order.

## Ordering sentinels

`order_sentinel.rs` and the offset ledger turn the consumer's core guarantees into always-on, alertable metrics (see the module docs for semantics).
Each guarantee has a violation counter that must stay flat and a denominator that must grow:

| Guarantee | Violations (must stay 0) | Denominator / supporting |
| --- | --- | --- |
| Commits are contiguous and monotonic per partition, each the ledger frontier one past the accepted prefix, and cover only completed offsets | `kafka_consumer_ledger_errors_total{stage,kind}` (a redelivered or out-of-window offset), `kafka_consumer_ledger_gap_offsets_total{topic,partition}` (offsets a frontier walked over without delivery), `ingestion_consumer_commit_violations_total{kind=empty\|uncredited}` | `ingestion_consumer_committed_offset{topic,partition}`, `kafka_consumer_ledger_uncommitted_offsets{topic,partition}` |
| Async commits land on the broker | `kminion_kafka_consumer_group_topic_partition_lag{group_id}` growing while `ingestion_consumer_messages_processed_total` holds its rate | `ingestion_consumer_committed_offset{topic,partition}` (the offset last handed to the client), `ingestion_consumer_offset_commits_total` |
| Per-key sends are in offset order, never re-sent after ACK (keyed messages only) | `ingestion_consumer_key_order_violations_total{kind=intra_group_disorder\|resend_after_ack}` | `ingestion_consumer_key_replays_total` (legal at-least-once retries), `ingestion_consumer_key_sentinel_keys`, `ingestion_consumer_key_sentinel_unkeyed_total` (skipped null-key messages) |
| Messages enter the worker pipeline in per-key offset order (end to end) | `ingestion_api_out_of_order_messages_total` (worker-side) | `ingestion_api_replayed_messages_total`, `ingestion_api_order_sentinel_keys` |

Commit success can't be observed via rdkafka's `commit_callback` — librdkafka drops the result of manual async commits (no conf-level `offset_commit_cb` is ever registered by rust-rdkafka, and only sync commits attach a reply queue).
The broker's view comes from kminion, which exports every group's lag per partition; commits that stop landing show as lag that grows while the consumer's processed rate holds, or as lag that stays above zero on a partition with nothing new to read.
A commit that never lands costs a replay from the last landed commit on the next restart, not a loss.

Both sides default to enabled and have kill switches: `CONSUMER_ORDER_SENTINEL_ENABLED` here, `INGESTION_API_FEED_ORDER_SENTINEL_ENABLED` (plus `INGESTION_API_FEED_ORDER_SENTINEL_MAX_KEYS`) on the worker.
The rebalance metrics from the consumer context stay on regardless, and the `consumer_id`/`replay` request fields are always stamped so either side can be toggled independently.
The worker-side check lives in `nodejs/src/ingestion/api/feed-order-sentinel.ts`, fed by the `consumer_id` (process incarnation) and `replay` fields the transport stamps on every sub-batch.
It measures the invariant at its end point: the worker groups each key's messages by distinct id and processes each group in feed order, so "fed in offset order per key" is "processed in order per distinct id".
A partial ack keeps that, because the worker leaves only the last messages of a distinct id unfinished and the consumer resends them in order.
Rebalances reset all baselines (`ingestion_consumer_rebalances_total{event}` counts them), so partition handoffs don't fire false positives.
Null-key messages (e.g. overflow rerouting) are excluded from both checks: the producer deliberately forfeits per-key order for them, and the consumer routes each one on its own, so there is no invariant to check on either side.

## Offset ledger

The consumer holds the per-partition offset ledger from `common/kafka-consumer`, which owns the commit.
Every delivered message is charged to its partition's ledger during collection, and accepted work completes its offsets there; the commit is then each partition's frontier, one past its longest completed prefix.
A partition that settles without a frontier is not committed and stays on its last commit: an earlier group on that partition is still out.
Each frontier the consumer takes goes to the commit pacer (`commit_pacer.rs`), and the consumer commits what the pacer hands back.
The pacer holds no I/O: the consumer commits what it is given.
A partition that leaves the assignment drops its pending frontier with its ledger, so a later commit cannot commit under another owner.

`CONSUMER_COMPLETION_GRANULARITY` selects the unit that settles against the ledger; each unit is one implementation of `Settlement` in `src/settlement/`, and the consumer loop is the same for both.
`poll` (the default) settles a whole poll once every one of its groups is accepted, oldest poll first, and commits its frontiers at once.
`group` settles each group's offsets as its completion arrives, in any order, so a stalled key holds back only its own partition's commit.
At `group` granularity the pacer keeps the latest frontier per partition and hands them out at most once per `CONSUMER_COMMIT_INTERVAL_MS` (default 500 ms).
The consumer asks the pacer on each completion wake, at the top of each loop turn, and on the completion wait's one-second heartbeat, and commits everything pending on exit.
Under the capped polling strategy, admission is per poll at both granularities: `CONSUMER_MAX_BACKGROUND_TASKS` caps in-flight polls, and a slot frees when its whole poll is covered, oldest first, so a stalled key still holds its poll's slot. See [Polling](#polling).
At `poll` granularity, `ingestion_consumer_commits_skipped_total{reason}` counts polls that settle with no frontier: `rejected` means the ledger dropped every slice (expected around a rebalance) and `no_frontier` means an earlier batch is still incomplete at the front of every window the batch settled.
The settlement publishes the uncommitted gauges, because it holds both places a partition's charge can be: the ledger's window and the pacer.
`kafka_consumer_ledger_uncommitted_offsets{topic,partition}` gauges the offsets each partition has polled and no commit has covered yet, including those taken for a commit the pacer still holds; `kafka_consumer_ledger_uncommitted_events` and `kafka_consumer_ledger_uncommitted_bytes` gauge the charge those offsets carry, where bytes is the payload plus key plus headers of each message.
The ledger emits its own counters, so any consumer built on the crate reports the same series.
`kafka_consumer_ledger_stale_slices_total{stage}` counts charges and settlements dropped because their partition was reassigned while they were in flight; a few around a rebalance are expected.
`kafka_consumer_ledger_errors_total{stage,kind}` counts contract violations in the ledger's accounting; it must stay 0. A violation stops the consumer, and the restart replays from the last commit: the ledger resets the partition's window, so offsets in flight below its next delivery would never complete and a later commit would move past them. The consumer logs the rejected slice with the batch and ledger generations and the window depth before it stops.

## Partition budget

`CONSUMER_PARTITION_BUDGET_EVENTS` and `CONSUMER_PARTITION_BUDGET_BYTES` bound each partition's replay exposure: the events and bytes the settlement reports as uncommitted for it.
A budget needs `CONSUMER_COMPLETION_GRANULARITY=group`. At `poll` a stalled partition holds back the commits of every partition in its poll, so their budgets would fill and pause together. The consumer ignores a budget at `poll` and logs a warning, so switching a lane back to `poll` rolls it back without unsetting the budget.
When either axis reaches its limit after a poll, the consumer pauses that partition's fetch through the Kafka client; when a commit brings both axes back under `CONSUMER_PARTITION_BUDGET_LOW_WATERMARK` (a fraction of the budget, default 0.8), it resumes.
The hysteresis matters because a pause purges the partition's fetched messages from librdkafka's queue and a resume refetches them.
A pause stops only the partition's fetch: the consumer keeps polling, so rebalance callbacks still run and `max.poll.interval.ms` stays satisfied, except while the capped polling strategy's cap is full or the continuous strategy is at its in-flight limit.
A revoked partition is forgotten. librdkafka keeps a partition's pause across a revoke and a reassignment, so the consumer resumes every partition it is assigned, and the partition starts with a fresh ledger.
Both limits default to `0`, which sets no budget; the admission cap (`CONSUMER_MAX_BACKGROUND_TASKS`) then governs alone.
The budget is a fixed amount per partition, not a share of a pod-wide amount, so a rebalance changes how many partitions a pod holds, not how much each may expose.
`ingestion_consumer_budget_paused_partitions` gauges how many partitions are paused and `ingestion_consumer_budget_pauses_total{topic,partition}` counts pauses; read them against `ingestion_lag_ms`.

## Polling

The consumer loop is the only caller of `recv()`. It waits on Kafka, completions, the commit tick, the shutdown signal, and the poll's batch timeout, and hands each event to the selected implementation of the `PollingStrategy` trait in `src/polling/`.
The strategy returns steps, and the consumer carries them out: charge and submit a poll, submit a commit and resume its partitions, stop, or fail.
A poll is submitted when it reaches the batch size or the byte bound, or when `CONSUMER_BATCH_TIMEOUT_MS` passes after its first message.

The rebalance callbacks run inside `recv()`, on the loop's task. After every wake the loop hands the partitions they revoked to the strategy, before the event that woke it.
The strategy then removes those partitions' messages from the poll in progress and from its in-flight state: the batcher purges them, or Kafka delivers them again from the last commit.
So a message the loop adds to a poll always belongs to the current assignment, and the poll is charged under the partition's current ledger generation.

`CONSUMER_POLLING_STRATEGY` selects what bounds admission.
`capped` (the default) admits up to `CONSUMER_MAX_BACKGROUND_TASKS` polls, and frees a slot only when the oldest poll is covered, so a stalled key holds back fetching for every partition.

`continuous` admits polls without waiting on any of them.
The partition budget bounds each partition's replay exposure, and the in-flight limit bounds the whole pod: `CONSUMER_IN_FLIGHT_EVENTS` and `CONSUMER_IN_FLIGHT_BYTES` count the uncommitted charge of every partition, as the partition budget counts it.
The limit is approximate: it stops reading, and the poll in progress still completes, so the uncommitted charge can pass the limit by one poll. One poll holds at most `CONSUMER_BATCH_SIZE` events and `CONSUMER_BATCH_SIZE_KB` plus one message; with the byte bound off, its bytes are bounded only by the batch size times the largest message.
Room frees when a commit hands out offsets, as it does for the partition budget, not when a completion arrives.
At the limit the loop stops reading Kafka until a commit frees room, and rebalance callbacks wait with it, so size the limit above the budget times the partitions a pod holds.
`continuous` needs `CONSUMER_COMPLETION_GRANULARITY=group`, a partition budget, and an in-flight limit, and the budget and the limit each need both their events and bytes settings. A message with no key, value or headers charges zero bytes, so a byte-only limit admits any number of them. Without all three the consumer logs a warning and runs `capped`, so switching a lane back to `poll` rolls back both.
`ingestion_consumer_in_flight_limit_reached_total` counts each time the loop stops reading at the limit; the `kafka_consumer_ledger_uncommitted_*` gauges show each partition's share.

## Batcher

The batcher state machine in `src/batcher/` orders runs and places them on workers.

- One task owns the state machine and applies polls, worker responses, revokes and retry wakeups one at a time.
- Each key has a FIFO queue, and at most one request per key is in flight, which preserves per-key order.
- The packer builds a request only for a free worker slot, from ready keys up to a target size. Keys stay unclaimed until then, so a key's run keeps growing while every slot is busy, up to the run cap. A key's backlog past the run cap leaves in consecutive requests, one in flight at a time. The run cap is the target unless `INGESTION_RUN_CAP_*` sets it apart. A request never mixes assignment epochs or fresh and replayed messages.
- A request is placed on a worker when it is sent, against the load at that moment. Each worker takes at most `INGESTION_WORKER_CONCURRENT_BATCHES` requests at a time.
- A governor holds a permit pool between `INGESTION_GOVERNOR_MIN_PERMITS_PER_WORKER` and `INGESTION_WORKER_CONCURRENT_BATCHES` permits per routable worker, so at the ceiling the permits are the worker slots. A round-trip average over `INGESTION_GOVERNOR_LATENCY_BUDGET_MS` shrinks the pool by one. With the average within budget, the pool grows by one when the last pass was starved, which means it had ready work past the free permits. The pool moves at most once per `INGESTION_GOVERNOR_STEP_INTERVAL_MS`. Only accepted and partial acks feed the average. After a failed request, the requests sent to that worker until one of them settles feed nothing either, because they can wait out the stream's reconnect backoff. With `INGESTION_GOVERNOR_ADAPTATION=off` the pool is a shadow that reports what it would do while free slots size each pass.
- A failed send returns its messages to the front of their keys' queues. They retry through the packer as replay after the retry delay.
- A partial ack completes the messages the worker finished. Its unfinished messages return to the front of their keys' queues and go out again at once as replay. They need not be the last messages of their key.
- A key resends without a budget once `INGESTION_REQUEST_BUDGET_ATTEMPTS` settles have left its messages unfinished since it last finished a run, or at once when its request finished nothing, because a budgeted retry would wait out the same budget again. So a message that never fits the budget still finishes. A failed request neither counts nor resets the count. The resend rides in a request that holds only such keys, ahead of budgeted replays.
- A revoke drops the pending messages of the revoked partitions, because the new owner replays them.
- Pending work with nothing in flight and nothing accepted for `CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS` fails the consumer, which restarts and replays.

| Setting | Default | Effect |
| --- | --- | --- |
| `INGESTION_PACK_TARGET_EVENTS` | `500` | Send a request to a free slot once this many events are ready. Unless a run cap is set, it also caps one key's run. `0` disables the event target and the cap, and needs a byte target. |
| `INGESTION_PACK_TARGET_BYTES` | `0` | Send a request to a free slot once this many key-plus-value bytes are ready. Unless a run cap is set, it also caps one key's run. `0` disables the byte target and the cap, and needs an event target. |
| `INGESTION_RUN_CAP_EVENTS` | `0` | The most events one key's run holds, which is the most of its backlog a key sends per round trip. With both run caps at `0`, the pack targets cap runs. When either is set, the run caps replace them, and a `0` cap leaves that dimension uncapped. |
| `INGESTION_RUN_CAP_BYTES` | `0` | One key's run stops growing once it holds this many key-plus-value bytes. Works with `INGESTION_RUN_CAP_EVENTS`. |
| `INGESTION_PACK_LATENCY_BUDGET_MS` | `0` | Once a slot is free, wait this long for ready events below the target to reach it. `0` waits for nothing: each free slot gets what is ready, packed up to the target. Replays never wait, because they already waited out a retry delay or a worker's time budget. |
| `INGESTION_REQUEST_SOFT_BUDGET_MS` | `0` | How long a worker may spend on one request before it stops starting work and acks what finished as partial. The rest goes out again at once. `0` sends no budget. A request split into several frames goes without one. Startup fails if it is below `100` or above `2147483647`, if it times `INGESTION_WORKER_CONCURRENT_BATCHES` reaches `INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS`, or if it plus `INGESTION_PACK_LATENCY_BUDGET_MS` reaches `CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS`. |
| `INGESTION_REQUEST_BUDGET_ATTEMPTS` | `3` | How many budgeted attempts may leave a key's messages unfinished, since the key last finished a run, before it resends without a budget. At least 1, or startup fails. Only read when `INGESTION_REQUEST_SOFT_BUDGET_MS` is set. |
| `INGESTION_PARKED_RETRY_INTERVAL_MS` | `200` | The delay before a failed send retries, and how often a request with no routable worker tries again. |
| `INGESTION_GOVERNOR_ADAPTATION` | `off` | `off` keeps the governor observing: it measures request round-trip time and reports the permit pool it would run, while free worker slots size each pass. `on` sizes the pass by free permits too. |
| `INGESTION_GOVERNOR_LATENCY_BUDGET_MS` | `0` | A round-trip average above this shrinks the permit pool by one per step. `0` never shrinks. Startup fails when adaptation is on without it, when it reaches `INGESTION_REQUEST_SOFT_BUDGET_MS`, because a saturated worker answers partial at about the soft budget and a budget above it never shrinks on saturation, or when it reaches `INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS`. |
| `INGESTION_GOVERNOR_MIN_PERMITS_PER_WORKER` | `1` | The permit pool never shrinks below this many permits per routable worker. Startup fails below `1`, above `INGESTION_WORKER_CONCURRENT_BATCHES`, or at it when adaptation is on, because the pool could not move. |
| `INGESTION_GOVERNOR_STEP_INTERVAL_MS` | `1000` | The least time between two permit steps. Startup fails below `100`. |

Metrics:

- `ingestion_consumer_batcher_requests_sent_total{worker}` and `ingestion_consumer_batcher_messages_sent_total{worker}` count what each worker was sent, replays included.
- `ingestion_consumer_request_events` and `ingestion_consumer_request_bytes` record each request as sent. They show whether requests reach the pack target.
- `ingestion_consumer_request_queue_wait_seconds{kind=fresh|replay}` records how long a request's oldest message waited, including the pack budget.
- `ingestion_consumer_batcher_packed_requests_total{reason=target|deadline|replay|shutdown}` counts why the packer built each request: at the target, at the budget deadline, as a replay, or at shutdown.
- `ingestion_consumer_request_budget_partials_total` counts partial acks, and `ingestion_consumer_request_budget_unfinished_messages_total` counts the messages they left unfinished.
- `ingestion_consumer_request_budget_escalations_total` counts keys that resend without a budget, after their budgeted attempts or after a partial ack that finished nothing. A steady rate means the budget is too tight for the lane, or that the workers are saturated: a frame that waits out its budget for a pipeline slot comes back as a partial ack with nothing finished, and the worker counts it in `ingestion_api_grpc_admission_expired_total`.
- The `ingestion_consumer_batcher_*` gauges report keys, queued messages and bytes, claimed and waiting keys, unplaced work, and in-flight requests.
- `ingestion_consumer_governor_permits`, `ingestion_consumer_governor_ceiling` and `ingestion_consumer_governor_free_permits` report the permit pool, its ceiling, which is every slot on the routable workers, and the permits no request on a routable worker holds. With adaptation off the pool is the shadow pool.
- `ingestion_consumer_request_rtt_seconds` is the round-trip average the governor steps on.
- `ingestion_consumer_governor_adjustments_total{direction=grow|shrink,applied=true|false}` counts the governor's steps. `applied=false` means adaptation is off, so the step moved only the shadow pool. A step at a bound moves nothing and does not count.
- `ingestion_consumer_governor_starved_messages` reports the ready messages the last pass had past its free permits, which is demand the worker pool cannot take. With adaptation on they wait for a permit. With it off they went out on free slots, or wait for a slot.

## Debug API

Set `DEBUG_API_ENABLED=true` **and** `DEBUG_API_SECRET` to mount a real-time debug API on the health server (default `:3301`), for dev and incident debugging; off by default.
Every request must present the secret as `X-Debug-Api-Secret`; enabling without a secret fails closed (nothing is mounted).
The secret is dedicated to this control-plane→consumer hop — deliberately not `INTERNAL_API_SECRET` (see `.agents/security.md`).
The ingestion control plane UI consumes these endpoints to render the consumer's live state.
`debug_recorder.rs` keeps a bounded in-memory buffer of structured lifecycle events, recorded at the same points that emit metrics, and it never influences routing: poll dispatch, completion, commit submission and failure; every request the batcher sends (`RequestSent`) and how it settled (`RequestResolved`, with the unfinished count of a partial ack, or `RequestFailed` with its cause); worker health and membership.
A poll and a request both carry their assignment epoch and their offsets per topic-partition as runs of consecutive offsets, which is how the control plane UI matches a request to exactly the polls it carries, because a request can merge messages from several polls.
Routing keys never enter the payload, because they hold distinct ids.

- `/debug/load` — cheap JSON snapshot (worker health with each worker's in-flight requests and messages, plus the batcher's key-table counts), safe to poll fast. The batcher task answers the snapshot itself between two actions, so the hot path pays nothing when nobody asks; a task that does not answer within a second yields only the totals it last published.
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

Addressed by `RebalanceContext` (`rebalance.rs`) and kminion: the consumer reports the offset it last handed to the client, kminion reports the group's lag per partition (see "Ordering sentinels" above), and rebalance callbacks log assignment changes and reset the ordering sentinels.
The originally envisioned offset-commit callback turned out to be unreachable for manual async commits (librdkafka drops their results unless a conf-level `offset_commit_cb` is registered, which rust-rdkafka never does).
Remaining: alert rules on the ledger counters and on kminion lag.

### 3. DLQ for poison messages

A message a worker permanently rejects (a nack on every delivery) has no dead-letter path: after the stall timeout (`CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS`) the consumer fails and the process crash-loops on redelivery.
`poison_batch_fails_safely_without_committing` pins the safe half of the trade-off (never commit past unaccepted messages).
Needs a design pass: DLQ topic, retry budget before giving up, the per-key ordering caveat (DLQ-ing one message then delivering later ones for the same person), and replay ownership.
Non-UTF-8 payloads — currently nulled when a poll adds the message, with no metric — should route to the same DLQ as malformed input; a bytes-preserving wire format is not worth it while the producer (capture) guarantees UTF-8 JSON.

### 4. Revoke-aware partition handoff

The batcher's key queues are per-process.
During a consumer-group rebalance another instance can start a partition from the last commit while this instance still has uncommitted in-flight work — duplicates and possible cross-pod interleaving per key (`second_consumer_joining_the_group_preserves_all_messages` asserts no loss only, deliberately).
Fix: on partition revoke (cooperative-sticky callback, via the same `ConsumerContext` as item 2), finish and commit in-flight batches for the revoked partitions before acknowledging the revoke.

### Smaller items

- Probe timeout is hardcoded to `probe_interval / 2`; a slow-but-serving worker's `/_ready` can flap it unhealthy. Make it independently configurable.
- Non-UTF-8 payload/header nulling has no metric — add a counter and a rate-limited warning even before the DLQ work lands.
