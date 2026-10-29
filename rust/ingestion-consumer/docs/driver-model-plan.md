# Driver-model implementation plan

Status: **draft, for discussion**.

This plan implements the [driver-model redesign](https://github.com/PostHog/posthog/blob/pl/ingestion/consumer-redesign-doc/rust/ingestion-consumer/docs/driver-model.md) ([#89277](https://github.com/PostHog/posthog/pull/89277)) in small steps.
Each step is one PR.

Implementation reference: [Jose's `kafka-consumer-loop` branch](https://github.com/PostHog/posthog/compare/master...jose-sequeira/kafka-consumer-loop). It is a source of tested shared primitives, not a stack to merge whole: its first commit extracts the Kafka consumer config builder, while its second also includes primitives scheduled for later cycles. Reuse the config extraction and the cycle-2 ledger representation deliberately; leave the accumulator, budget, partition-driver, commit-manager, and drain work to their named cycles below.

## Starting point

The plan starts from current master.
Master already contains two parts of the design:

- The routing key is the opaque Kafka message key ([#90282](https://github.com/PostHog/posthog/pull/90282)). A message without a key gets a synthetic per-message key.
- Each worker has one long-lived ordered gRPC stream ([#85238](https://github.com/PostHog/posthog/pull/85238), [#90790](https://github.com/PostHog/posthog/pull/90790)). The stream runner keeps an un-acked ledger, resolves acks in send order, applies an ack watchdog, and fences on failure.

An assignment epoch also exists.
A rebalance increments it, and every sub-batch carries it.

These components stay as they are: the stream runners, the P2C (power-of-two-choices) router, the aperture, the worker registry, and the key-order sentinel.

## Initial PR stacks

Both stacks start from this plan branch ([#91468](https://github.com/PostHog/posthog/pull/91468)), so the reviewed design and implementation history stay together. Within a stack, each PR is based on the preceding PR.

| Stack | Branch sequence | Scope |
| --- | --- | --- |
| Cycle 1 | `c1-delete-eager-flush` | Change 1. |
| Cycle 2 | `c2-common-ledger` -> `c2-ledger-shadow` -> `c2-ledger-active` -> `c2-ledger-cleanup` | Changes 2 through 5, one PR per plan step. |
| Cycle 3 | `c3-demux-groups` -> `c3-batcher` -> `c3-scheduler-seam` -> `c3-key-table` -> `c3-scheduler-switch` | Changes 6 through 10, one PR per plan step. |

The stacks are independent: cycle 2 can begin without cycle 1, and cycle 3 needs only cycle 1 and the crate from change 2. The merge gates remain part of the plan: change 4 cannot merge until change 3 has soaked with a zero mismatch counter, and change 5 cannot merge until change 4 is stable on every lane. Draft PRs may be prepared earlier, but they must not collapse those gates.

## The cycle model

Work proceeds in cycles.
Each cycle delivers one outcome: a property of the system that holds from then on.
A cycle has five phases:

1. **Prepare**: structure changes that extract the seams: the interfaces that later changes swap behind. No behavior change.
2. **Implement**: build the new component, fully tested, not selected.
3. **Verify**: prove the new component against production before it takes over. A verify change adds observation only: a shadow comparison, a gauge, a dry-run report. Verification with no new code is a soak — a watch period in production with no code change — with a stated exit criterion, not a PR.
4. **Switchover**: config selects the new component. Canary one lane, then all lanes. The config is the rollback.
5. **Cleanup**: one deletion removes the old component and the switch.

Rules:

- Each change is one PR.
- Prepare, implement, verify, and cleanup changes do not change behavior. The e2e tests must pass without edits.
- Only a switchover may change behavior. Some do not (a switchover with identical output is still staged and reversible).
- Every cycle names its verify evidence: the metrics to read and the exit criterion.
- Old code is deleted in cleanup, never edited.
- Dead code is deleted before a seam is extracted around it. A cleanup of a switch that never shipped can open a cycle (change 1).
- A structural outcome with no behavior change needs no switchover. Review and the e2e tests control its risk. The table labels such a change Structure (change 19).
- A cycle's cleanup lands only after its switchover is stable on all lanes.
- Swap the smallest piece that removes the most complexity. Components that already match the target design are not rebuilt.
- A change must not alter the meaning of an existing metric. Metrics of deleted machinery are deleted with it.
- The key-order sentinel stays enabled through every cycle.

Cycle 1 lands first: one fast change that removes complexity, preserves behavior, and depends on nothing else.
After that, the cycles run in order, with two exceptions.
Cycle 3 does not depend on cycle 2, so it can proceed while cycle 2 soaks.
Cycle 4 needs only cycle 3's switchover, so it can proceed while cycle 3's cleanup soaks.
Cycle 8 needs cycles 2 and 3.
The numbered order is one valid schedule, not the only one: the [cycle dependency graph](#cycle-dependencies) at the end shows the full ordering freedom.

The swap unit in cycle 3 is the **scheduler**: the decision core that says which runs may go to a worker now, and where.
That is where the complexity concentrates — the pins, the stash, and the flush interplay.
Packing follows at once (cycle 4): the performance win depends only on the key-table scheduler, not on the event loop, decoupled commits, or the budget.
The request time budget follows packing (cycle 5): its enforcement precondition is the one-outstanding-request-per-key rule (cycle 3), and its budget sizes against the packed request size.
The governor follows (cycle 6): it needs the scheduler's ready queue for its growth signal, and it comes after packing and the time budget, so RTT (request round-trip time) tunes once, against the final request shape.
The single-owner event loop follows as its own outcome (cycle 7), once the scheduler is simple.

Each change ends with its interface impact: the types it adds, modifies, or removes.
A change that adds metrics lists their names.

| # | Cycle | Phase | Change |
| --- | --- | --- | --- |
| 1 | 1 one send origin | Cleanup | Delete the dead eager flush |
| 2 | 2 frontier commits | Implement | Add the common Kafka consumer crate and offset ledger |
| 3 | 2 frontier commits | Verify | Run the ledger in shadow mode |
| 4 | 2 frontier commits | Switchover | Commit from the ledger frontier |
| 5 | 2 frontier commits | Cleanup | Delete the old commit computation |
| 6 | 3 one request per key | Prepare | Demux polls into groups |
| 7 | 3 one request per key | Prepare | Encapsulate the worker batcher |
| 8 | 3 one request per key | Prepare | Extract the scheduler seam |
| 9 | 3 one request per key | Implement | Build the key-table scheduler |
| 10 | 3 one request per key | Switchover | Switch to the key-table scheduler |
| 11 | 3 one request per key | Cleanup | Delete the old scheduler |
| 12 | 4 target-sized requests | Implement | Add the packer |
| 13 | 4 target-sized requests | Switchover | Set the packing targets |
| 14 | 5 partial redelivery | Implement | Add partial settlement and the request time budget |
| 15 | 5 partial redelivery | Switchover | Set the request time budgets |
| 16 | 6 adaptive concurrency | Implement | Add the governor |
| 17 | 6 adaptive concurrency | Switchover | Enable RTT adaptation |
| 18 | 6 adaptive concurrency | Cleanup | Remove the fixed per-worker cap |
| 19 | 7 single-owner batcher | Structure | Collapse the batcher into one event loop |
| 20 | 7 single-owner batcher | Cleanup | Remove the stream fences |
| 21 | 8 decoupled commits | Switchover | Switch completion to group granularity |
| 22 | 8 decoupled commits | Cleanup | Delete the per-poll completion path |
| 23 | 9 bounded replay | Implement | Add the budget accounting |
| 24 | 9 bounded replay | Switchover | Enable the budget |
| 25 | 9 bounded replay | Prepare | Put polling behind a strategy |
| 26 | 9 bounded replay | Implement | Build the continuous polling strategy |
| 27 | 9 bounded replay | Switchover | Poll continuously |
| 28 | 9 bounded replay | Cleanup | Delete the capped polling strategy |
| 29 | 10 clean handoff | Prepare | Add revoke and drained markers |
| 30 | 10 clean handoff | Implement | Build the drain |
| 31 | 10 clean handoff | Switchover | Enable the drain |
| 32 | 10 clean handoff | Cleanup | Delete the no-drain path |

## Cycle 1: one send origin

Outcome: the eager send path is gone.
This cycle has no switchover: the eager flush was never enabled.

**Verify:** the e2e suite. The change preserves behavior. The stash gauges (`ingestion_consumer_dispatcher_stashed_*`) must not change shape after the eager deletion.

### 1. Delete the dead eager flush (cleanup)

**Task:** Remove the eager deferred flush. The flag that enables it is off everywhere.

**Goal:** One send origin fewer before change 8 extracts the scheduler seam.

- `DISPATCHER_EAGER_DEFERRED_FLUSH` is default off, and no deployment sets it. Confirm against a fresh charts checkout and the live deployments before this ships.
- The completion-time flush already does all the draining in production. Behavior does not change.
- Carrying the eager path through the seam extraction would preserve code that does not run.

**Interfaces:**

- Remove `EagerFlush`, `run_eager_flush_loop`, `send_eager_flush`, and `DISPATCHER_EAGER_DEFERRED_FLUSH`.
- Modify `Dispatcher`: remove `set_eager_flush_sender`, `release_next_groups`, `eager_flush_*`, `take_eager_accepted`, and the eager pending and accepted accounting.

## Cycle 2: commits come from the frontier

Outcome: commit contiguity is a property of a data structure, not of completion order.

**Verify:** change 3 compares the frontier with every real commit on all lanes.
Exit criterion: `ingestion_consumer_ledger_mismatch_total` stays zero across deploys and rebalances, and `kafka_consumer_ledger_uncommitted_offsets` returns toward zero when a lane is idle — the ring drains.

### 2. Add the common Kafka consumer crate and offset ledger (implement)

**Task:** Create `rust/common/kafka-consumer` and add `ledger.rs` with a per-partition offset ring. Do not wire it into a consumer yet.

**Goal:** Make commit contiguity a reusable property of a data structure, not a feature of the ingestion consumer.

- Start from the config extraction in [Jose's branch](https://github.com/PostHog/posthog/compare/master...jose-sequeira/kafka-consumer-loop): move the current consumer config builder unchanged into `common-kafka-consumer`, retain its fixture coverage, and make `ingestion-consumer` depend on it.
- Copy only the cycle-2 domain primitives from Jose's second commit into the new crate: the offset wrapper and the charge carried by a ledger slot. Adapt its `OffsetLedger` representation to this plan's `complete`, non-mutating `frontier`, and consuming `take_frontier` contract: Jose's current `complete` advances and removes the prefix, so it cannot be copied unchanged into the shadow comparison.
- Do not take `Accumulator`, `Budget`, `PartitionDriver`, `PartitionManager`, or `CommitManager`; those implement later cycles and would make this PR cross several plan boundaries. The ledger module must not depend on `rdkafka`, `ingestion-consumer`, or service-specific metrics; it emits its own metrics under the crate prefix. The shared config module may retain its `rdkafka` dependency.

- One ledger per partition. The ledger is a dense ring of delivered offsets.
- Each slot records: complete or not, event count, byte count. The counts serve the budget in change 23.
- The byte count is the payload plus the key plus every header key and value: the bytes the process holds for the message. Today's `CONSUMER_BATCH_SIZE_KB` counts the payload only; the budget is a memory bound, so it counts what is retained.
- Operations: `charge` adds a delivered offset. `complete` marks an offset done. `frontier` returns one past the highest contiguous done offset and does not mutate. `take_frontier` consumes the done prefix below the frontier.
- The frontier is in Kafka's committed-offset representation: the next offset to read, not the last offset processed. The current commit path already commits in this representation (the poll's max offset plus one), so the frontier is commit-ready as returned — no call site adds or subtracts one.
- The read/consume split matters: the comparison read is idempotent and cannot consume state by accident. Consumption happens at commit points in every mode, so the ring holds only uncommitted offsets.
- Completions can arrive in any order. The frontier moves only over completed slots.
- Kafka can deliver offsets with gaps: transaction markers occupy offsets that consumers never receive, and compaction keeps offsets while removing records. Our ingestion topics have neither today, so a gap the frontier walks over (`kafka_consumer_ledger_gap_offsets_total`) is a real skip.
- The ledger still defines contiguity over delivered offsets, not offset arithmetic. A legitimate gap can then never block the frontier.
- The sentinel's gap alert and the ledger's gap handling cannot both stand. Once the frontier owns commits (change 4), a commit that walks over a legitimate gap is correct, and the sentinel would report it as a skip. The ledger therefore counts each gap it walked over (`kafka_consumer_ledger_gaps_total`), and the sentinel's gap alert retires in change 5. Until then the alert stays, because the ingestion topics have no legitimate gaps today and a gap is still a real skip.
- Add property tests: out-of-order completion, monotonic frontier, `frontier` idempotence, the ring drains after `take_frontier`, offset gaps, ring capacity.

**Interfaces:**

- Add workspace crate `common-kafka-consumer`, exporting the shared config builder, `Offset`, `Charge`, and `OffsetLedger`.
- Add `OffsetLedger` in `ledger.rs`: `charge`, `complete`, `frontier` (non-mutating), `take_frontier` (consuming). No runtime callers yet. The name avoids a clash with the stream runner's internal un-acked ledger.
- Modify `ingestion-consumer` to import the moved config builder from the common crate.

### 3. Run the ledger in shadow mode (verify)

**Task:** Wire the ledger next to the commit path. Compare its frontier with each real commit. Do not change what the consumer commits.

**Goal:** Prove the ledger against production traffic before it owns the commits.

- New config: the ledger mode, `off`, `shadow`, or `active`. This change ships `shadow`. Change 4 ships `active`.
- Charge every delivered offset into its partition ledger during `collect_batch`.
- When a poll completes, mark all its offsets complete.
- At each commit, compare the partition's `frontier` — the non-mutating read — with the offset the current path commits. Both are next-to-read offsets, so with oldest-first completion the two must be equal, with no offset arithmetic in the comparison.
- After the comparison, call `take_frontier` at the same commit point. The ledger drains identically in shadow and active modes. Without this, the shadow ring grows without bound.
- On a mismatch: increment a counter and log the partition with both offsets. Do not block the commit.
- On revoke, drop the partition's ledger. This mirrors the commit sentinel's `forget_partitions`.
- Soak on all lanes until the cycle's exit criterion is met.

**Interfaces:**

- Modify `Config`: add the ledger mode.
- Modify `IngestionConsumer`: own one `OffsetLedger` per partition. Charge in `collect_batch`, complete on poll completion, compare in `commit_offsets`.
- Modify the revoke path (`SentinelContext`): drop revoked partitions' ledgers.

**Metrics:**

- Add `ingestion_consumer_ledger_mismatch_total` (counter): frontier vs committed offset disagreement.
- Add `kafka_consumer_ledger_uncommitted_offsets` (gauge, per partition): ring depth. It must fall at commit points. A value that only grows is a drain bug (a leak).
- Add `kafka_consumer_ledger_gaps_total` (counter): offset gaps the ledger walked over. Expected to stay at zero on the ingestion topics; a non-zero value is the signal the sentinel's gap alert gave before change 5 retires it.

### 4. Commit from the ledger frontier (switchover)

**Task:** Set the ledger mode to `active`. The frontier becomes the committed offset. Keep oldest-first completion.

**Goal:** The frontier produces the same commits as the old code, and change 3 already proved that.

- Commit each partition's frontier instead of the poll's max offset plus one. Both are next-to-read offsets: with oldest-first completion, the committed value does not change.
- The ledger calls do not change: both modes already charge, complete, compare, and consume at the same points (change 3). This switchover changes only which value the consumer commits.
- With oldest-first completion, the output is identical to the old path.
- The commit sentinel stays on and checks contiguity and monotonicity.
- Rollback is the config switch back to `shadow`.

**Interfaces:**

- Modify `Config`: default the ledger mode to `active`.
- Modify `IngestionConsumer::commit_offsets`: read the committed offset from the ledger. The old computation survives as the shadow comparison until change 5.

### 5. Delete the old commit computation (cleanup)

**Task:** Remove the old commit computation after `active` is stable on all lanes.

**Goal:** The frontier is the only commit source.

- Remove the old per-poll commit computation and the shadow comparison.

**Interfaces:**

- Modify `IngestionConsumer::commit_offsets`: frontier only.
- Modify `Config`: remove the ledger mode.
- Remove `ingestion_consumer_ledger_mismatch_total`. The comparison it counts is gone; the commit sentinel remains the invariant check.

## Cycle 3: at most one request per key is in flight

Outcome: the scheduler sends at most one request per key at a time, and that alone preserves per-key order. Pins, the stash, and the flush paths are gone.

**Verify:** the deterministic seam tests in change 9 script arrivals, settlements, and failures.
A production shadow is impossible here: the scheduler's decisions change which sends exist, so state diverges immediately.
The canary in change 10 is the production proof.
Exit criterion: zero key-order sentinel violations, `ingestion_consumer_transport_duration_seconds` and the `ingestion_consumer_messages_processed_total` rate unchanged, and the no-progress watchdog quiet.

### 6. Demux polls into groups (prepare)

**Task:** Change `collect_batch` to output groups. A group is one poll's consecutive messages for one routing key on one partition.

**Goal:** Create the accumulator shape from the design doc.

- Group messages per partition first, then per routing key. Keep offset order inside each group.
- The dispatcher flattens the groups back into one message list. Sub-batch assembly does not change.
- Change 7 submits them to the batcher as the accumulator.
- The group is the seam vocabulary between the consumer loop and the batcher, so it lives in `common-kafka-consumer`, generic over the key and the message body. The crate's demux knows no routing key of its own: a keyless message is one group on its own, and the dispatcher keeps naming such a group with its synthetic per-message key.

**Interfaces:**

- Add `Partition` to the crate's `types.rs`, and `Group` and `Accumulator` in `accumulator.rs`: a group is a partition, an optional key, and its offsets and messages in offset order; the accumulator is the demux that builds one poll's groups.
- Modify `CollectedBatch`: carries `Vec<Group>` instead of a flat message list.
- Modify `Dispatcher::assign_and_send`: takes groups and flattens them. The demux moves to the collect path; the dispatcher keeps only the routing-key naming.

### 7. Encapsulate the worker batcher (prepare)

**Task:** Put today's dispatch orchestration behind one boundary. The consumer loop and the batcher exchange plain values.

**Goal:** The dispatch concurrency becomes an implementation detail behind one interface.

- Interface in: one accumulator per poll — the poll's demuxed groups, submitted on the consumer loop in poll order.
- Interface out: one completion event per group, with its partition, its assignment epoch, its offsets, and its accepted count.
- This is the design doc's boundary: accumulators in, completions out. It is the final shape and does not change again.
- No batch identity crosses the boundary. The facade creates an internal batch id per accumulator for the old machinery and the wire request. The consumer correlates completions by partition and offset — the same key the ledger uses.
- The facade breaks each resolved send into its groups. The send resolution in `scatter` already carries them (`routing_keys` and `key_offsets` on `PendingSubBatch`), and a send is all-or-nothing.
- Only orchestration moves inside the boundary: assignment, scatter with its send resolution, and the deferred flush.
- `GrpcTransport`, `Router`, and `WorkerRegistry` keep their construction and ownership in `main.rs`. The batcher takes shared handles. Readiness gating, discovery reconciliation, the reaper, and the debug endpoints do not change.
- The facade replicates today's behavior exactly, including the oldest-first flush pacing. This is code motion — moving code without changing it — not redesign.
- The consumer loop keeps: poll collection, commits, the sentinels, and the admission cap. It tracks each poll's offset spans and completes the poll when completions cover them, so completion and commit behavior do not change.
- The no-progress watchdog moves with the flush: the stall deadline lives in the batcher's flush driver, and only there. The clock suspends while a send is in flight and resets when messages land, exactly as today — a consumer-side completions-only timer cannot see the difference between a wedged flush and a slow send, and would fail drains that today survive. The batcher reports a stall (and the other fatal orchestration failures: shutdown while deferred work is unroutable, a batch with no usable workers) on an error channel beside the completions; the consumer fails the process on the first message, keeping the failure decision in the loop. Every later cycle keeps this bail until cycle 10 adds the per-partition stall deadline.
- Each completion carries the assignment epoch read once at submit, and `submit` returns it. The consumer correlates a completion to a poll by epoch plus partition and offset — within one epoch, poll spans are disjoint per partition — and discards and counts a completion that matches no in-flight poll. The epoch already exists on master. Carrying it on the completion from this change closes the window a partition-ownership check leaves open: a partition revoked, reassigned, and replayed while a group is out has two polls holding the same offsets, and the old incarnation's completion must not land in the new poll (nor, later, in its new ledger).
- Changes 8 and 9 extract the scheduler seam inside this boundary.

**Interfaces:**

- Submit the `Accumulator` from change 6 as one poll's groups, in poll order.
- Add `Batcher` in `batcher.rs`: `submit(Accumulator)` in (returning the stamped assignment epoch), a channel of `GroupCompletion` plus an error channel out. It owns `Dispatcher` and the send tasks, and holds shared handles to `GrpcTransport`, `Router`, and `WorkerRegistry`, plus a lifecycle handle and the deferred-flush timeout for its flush driver. It creates batch ids internally.
- Add `GroupCompletion` in the crate's `types.rs`: partition, assignment epoch, offsets, accepted count. No batch id and no messages: the batcher keeps the bodies for retry, and the ledger needs only the offsets.
- Add `AssignmentEpoch` to the crate: the named home of the assignment generation. `main.rs` creates it, the rebalance context bumps it, and the transport and the batcher read it — one counter, one bump site, two readers.
- Modify `IngestionConsumer`: drop `scatter` and `flush_deferred` — they move into the batcher. Keep collect, commit, and the admission cap. Correlate completions to polls by epoch, partition, and offset.
- Modify `main.rs`: construct one `Batcher` from the existing transport, registry, and router. The consumer no longer sees the dispatcher.
- Internalize `Dispatcher`'s resolve methods (`on_sub_batch_*`, `defer_failed`): only the batcher calls them in production code. The methods stay public because the e2e suite drives them directly, and that suite must pass unedited.

**Metrics:**

- Add `ingestion_consumer_group_completions_total` (counter) and its accepted-message sum, `ingestion_consumer_group_completion_accepted_messages_total`. Cross-check: the sum tracks `ingestion_consumer_messages_processed_total`.
- Add `ingestion_consumer_stale_group_completions_total` (counter): completions discarded because no in-flight poll matched.

### 8. Extract the scheduler seam (prepare)

**Task:** Move every ordering and placement decision inside the batcher behind one interface. Keep the current semantics.

**Goal:** Isolate the decision core from the plumbing, so the smallest valuable piece can swap.

- The scheduler decides which runs may go to a worker now, and where. Nothing else in the batcher decides that.
- Interface in: events. A group arrives. A request settles, with success or failure. A retry deadline fires.
- Interface out: dispatches. One dispatch is one run of one key on one worker.
- The first implementation preserves today's semantics: pins, the stash, deferral on drain, and the flush pacing. This is code motion from `assign`, `flush_deferred`, and `on_sub_batch_resolved`.
- The plumbing (tasks, channels, the mutex) stays as it is. Only the decisions move.
- The seam is event-shaped, by design: each call is one event, runs to completion, does no I/O, takes no locks, and returns its effects as data (the dispatches, the deferral counts, the evicted keys). This shape is what later makes change 19 mechanical: the seam's handlers become the loop's select arms.
- The no-locks rule needs the worker world as data: the dispatcher captures a `WorkerSnapshot` (healthy pool, aperture-narrowed candidates, per-worker health, the load table) before each seam call, and the scheduler decides over it. Change 19 already names this shape: the worker-health snapshot stays the only shared read.
- A failed send settles in one call: the settlement's failure arm carries the failed runs, and the scheduler requeues them before it releases the keys. This is the invariant change 9's key-table needs (requeue before release); the pin-stash implementation preserves today's stash-then-decrement order inside the one call. The two-step resolve methods stay public for the e2e suite, which must pass unedited.
- The seam makes today's implicit ordering rules explicit and reviewable in one place.

**Interfaces:**

- Add the `Scheduler` trait in `scheduler.rs`: `on_groups`, `on_settled`, `on_deadline` in; a `SchedulerEffects` out — the dispatches plus the deferral counts and evicted keys, so metrics and debug events stay in the plumbing. `on_deadline` names the batch to retry while the pacing is per batch; the key-table scheduler generalizes it to a parked-retry deadline.
- Add `Dispatch`: one run of one key, with the chosen worker and the send kind for the key-order sentinel.
- Add `WorkerSnapshot` and `Settlement` (with its delivered and failed arms) as the seam's input vocabulary.
- Add `PinStashScheduler`: the current semantics, moved out of `Dispatcher::assign`, `flush_deferred`, and `on_sub_batch_resolved`. It owns the pins, the `Stash`, and the `Router` unchanged — placement is a scheduling decision.
- Modify `Dispatcher`: shrinks to plumbing — the lock, in-flight load, metrics, sentinel calls, view capture, sub-batch assembly, and seam calls. `settle` is the one production resolve entry point.

### 9. Build the key-table scheduler (implement)

**Task:** Write the target scheduler as a second implementation of the seam. Do not select it.

**Goal:** The replacement for the ordering core exists, fully tested, before any behavior changes.

- The key table: one FIFO queue per key. A key is runnable when it has queued work and no outstanding request.
- On arrival: enqueue, and dispatch one contiguous run when the key is runnable. Dispatch marks the key outstanding.
- On settlement: clear the flag. Success dispatches the key's next run. Failure returns the run to the front of its queue, then clears the flag — requeue before release, in one seam call.
- A parked-retry deadline covers the keys no settlement can release: unroutable groups, and keys behind a failed send.
- Placement is stateless: the existing P2C and aperture pick a worker per dispatch. There are no pins.
- The seam is events in, dispatches out. Test the scheduler deterministically: script arrivals, settlements, and failures. Assert per-key order.

**Interfaces:**

- Add `KeyTableScheduler` and `KeyTable` in `key_table.rs`: per-key FIFO, outstanding flag, parked list. Implements `Scheduler`. Tests only, no production callers.
- Modify `Scheduler::on_deadline`: takes a `Deadline` — the per-batch flush deadline (the pin-stash pacing) or the parked-retry deadline (the key-table pacing). Each implementation answers its own arm; the other arm is a no-op. The dispatcher keeps firing per-batch deadlines.

**Metrics:**

- Add, emitted when selected: `ingestion_consumer_key_table_keys`, `ingestion_consumer_key_table_queued_messages`, `ingestion_consumer_key_table_queued_bytes`, `ingestion_consumer_key_table_outstanding_keys`, `ingestion_consumer_key_table_parked_keys` (gauges), `ingestion_consumer_parked_retries_total` (counter), and `ingestion_consumer_key_table_queue_wait_seconds` (histogram, by send kind): the head-of-line wait, the latency cost the one-request-per-key rule accepts. Queued bytes needs an alert before the switch: every key with an outstanding request buffers all later arrivals in full, and key cardinality is customer-controlled.

### 10. Switch to the key-table scheduler (switchover)

**Task:** Select the key-table scheduler with config. Canary one lane, then roll out.

**Goal:** At most one in-flight request per key replaces pins, the stash, and the flush paths.

- The switch changes the ordering rule, and with it the completion-accounting assumption: a merged run spans polls, so one completion no longer maps onto one poll. Placement and transport do not change.
- At most one outstanding request per key preserves per-key order. Nothing else does, and nothing else must.
- This is proposal 2 of the design doc: sticky pins are removed. Measure worker key-cache locality before and after (open question 3).
- Watch the cycle's exit metrics, and the key-table gauges for queue growth.
- Rollback is the config switch back to the old scheduler.
- The trait does not change, but the plumbing does: the dispatcher and batcher today honor only the subset of `SchedulerEffects` the pin-stash produces. The seam isolates implementations only when the caller applies the full effects from every seam call. The plumbing changes below must land before the scheduler selection — a bare config switch drops settlement dispatches and fatals on a poll whose keys are all outstanding.

**Interfaces:**

- Modify `Config`: add the scheduler selection.
- Modify the batcher construction: select the scheduler. Prefer an enum over a trait object: the dispatcher calls six pin-stash-only inherent methods (`register_batch`, `release_batch`, `has_batch`, `pin_count`, `stashed_messages`, `stashed_batches`) that must stay off the trait, and change 11 deletes one arm.
- Add `Dispatcher::settle_and_send`, called from both scatter arms: under the key table a delivered settlement dispatches the key's next run, so `settle` may no longer drop `effects.dispatches`. Dispatches are `begin_send`-ed under the lock, as in `assign_and_send`; sending from a settlement makes the scatter recursive.
- Modify `run_scatter`'s empty-pending guard: a poll whose keys are all outstanding dispatches nothing by design and is not "no healthy workers". The guard needs a scheduler-level retained-work answer (pin-stash: `has_batch`; key table: queued or outstanding keys).
- Replace the flush driver rather than retarget it: `run_flush_driver` is per-batch (ticket loop, `has_unfinished_flush`, per-batch stall deadline), and parked keys have no batch identity. The key table needs a global periodic `Deadline::ParkedRetry` pump plus a global stall watchdog, so a wedged key table restarts loudly instead of growing lag silently.
- Modify `apply_completion` in the consumer: credit each offset to the in-flight poll that contains it, instead of crediting the whole completion to the poll that contains its first offset. A merged run's completion spans polls in steady state; under first-offset crediting the first poll over-counts and the later poll never completes, and its wait loop reports healthy every second while stuck.
- Bound runs by epoch in the key table: stamp the assignment epoch on messages at enqueue, and stop `take_run` at an epoch boundary, so a run never mixes epochs and its completion carries one valid stamp. A cross-epoch completion has no correct stamp and one side is discarded as stale.
- Purge on rebalance: drop the key table's queued messages for revoked topic-partitions, and remember revocations for outstanding sends so a later failure cannot requeue their revoked messages. Clear that revocation state at settlement; kept partitions and newly reassigned work remain retryable. The new partition owner replays revoked work; sending it from the old owner too duplicates delivery.

### 11. Delete the old scheduler (cleanup)

**Task:** Remove the old scheduler implementation after change 10 is stable on all lanes.

**Goal:** The old concurrency goes in one deletion, not in edits.

- Removes: the pin table, the stash, the completion-time flush, and the scheduler switch.
- The plan never edits this machinery. It is isolated in change 8, bypassed in change 10, and deleted here.

**Interfaces:**

- Remove `PinStashScheduler`, `PinTable`, `Stash`, and `sticky_pin_for`.
- Remove the scheduler selection from `Config`.
- Modify `Dispatcher`: remove the dead resolve plumbing (`clears_deferral`, `send_failed`, the flush driver).
- Remove `Deadline`: with the per-batch arm gone, the parked retry is the only deadline left.
- Remove the pin and stash metrics (`ingestion_consumer_dispatcher_pins_total`, `ingestion_consumer_dispatcher_stashed_*`, the deferral counters, `ingestion_consumer_dispatcher_pin_evictions_total` — key-table evictions must not keep counting under a pin name). The key-table gauges replace them.

## Cycle 4: workers receive target-sized requests

Outcome: request size tracks target T, and a request forms only when there is work to fill it. No cleanup: body splitting stays as a defence.
This cycle sits directly after the scheduler on purpose: the win depends only on the key-table scheduler.
It needs cycle 3's switchover on all lanes, and can proceed while cycle 3's cleanup soaks.
A scheduler rollback also reverts packing: the packer exists only in the key-table scheduler.

**Verify:** with the pack budget at zero, the packer emits on arrival and the e2e suite passes unchanged.
Exit criterion after the targets: the request-size histograms center near T, and `ingestion_lag_ms` does not regress.

### 12. Add the packer (implement)

**Task:** Add the packer to the scheduler, with target size T and `PACK_LATENCY_BUDGET`. Ship with the pack budget at zero: send-on-arrival, behavior unchanged.

**Goal:** The packing machinery exists before it changes any request.

- Check the worker side first: a packed request spans polls and keys. Confirm the worker's `concurrentBatches` accounting and the meaning of `batch_id` still hold.
- Pack runs from multiple runnable keys into one request near T. T counts events and bytes.
- Emit immediately when the ready work can fill the free stream slots with near-T requests. Otherwise arm the pack deadline. The governor (cycle 6) replaces the slots with permits.
- When the deadline expires, emit partial requests. The deadline also bounds the wait when held groups keep polls open: packing adds latency, never a deadlock.
- Router order inside a pass: fill open requests on healthy workers first, then pick a worker with P2C from the aperture slice. Partition affinity is a tie-breaker only.

**Interfaces:**

- Add `Packer` inside `KeyTableScheduler`.
- Modify `Dispatch`: one request may carry runs from several keys.
- Modify `Config`: add T and `PACK_LATENCY_BUDGET`, default zero. The worker proto does not change.

**Metrics:**

- Add `ingestion_consumer_request_events` and `ingestion_consumer_request_bytes` (histograms): the size of each sent request.
- Add `ingestion_consumer_pack_emits_total` (counter, reason `arrival`, `full`, or `deadline`).

### 13. Set the packing targets (switchover)

**Task:** Set T and the pack budget per lane.

**Goal:** Workers receive target-sized requests.

- A charts values PR sets the targets lane by lane.
- Watch the request-size histograms, worker occupancy, and end-to-end latency. Rollback is a pack budget of zero.

**Interfaces:**

- None in this repository. Config values only.

## Cycle 5: a slow request redelivers only its remainder

Outcome: a worker stops a request at the consumer's time budget, acks the finished messages, and only the unfinished ones redeliver.
Today one slow message holds every message behind it until the ack watchdog fences the whole stream, and everything unacked replays with duplicate work.
This budget is time per request. It is not B, the uncommitted-work budget of cycle 9.

It needs [#115388](https://github.com/PostHog/posthog/pull/115388) merged on the worker side (`soft_budget_ms` on the wire, the `PARTIAL` ack with its `unfinished` list).
It needs cycle 3: with one outstanding request per key, no later request can pass a cut message of its key.
It sizes the budget against cycle 4's request size. Its cap on request RTT matters for cycle 6: set `REQUEST_LATENCY_BUDGET` below the soft budget, or the governor never shrinks.

**Verify:** a generous budget on one lane enforces rarely and exercises the real partial-ack path at negligible volume.
Exit criterion: partial acks resolve and their remainders redeliver in order, zero key-order sentinel violations, and ack-watchdog teardowns (`ingestion_consumer_worker_stream_teardowns_total`) fall.

### 14. Add partial settlement and the request time budget (implement)

**Task:** Teach the transport the `PARTIAL` ack and the batcher state machine a partial settlement. Ship with no budget set: absent means unlimited, today's behavior.

**Goal:** Partial redelivery exists as one settlement arm, not a new path.

- The transport parses `PARTIAL` and resolves the send with the accepted count and the `unfinished` messages, named by partition and offset, instead of fencing it as busy. An ack that does not match the request fails the stream.
- `BatcherStateMachine::on_request_partial` completes exactly the accepted set and returns each key's unfinished messages to the front of its queue, sent again at once as replay. The unfinished messages need not be the last of their key, because the worker groups by distinct id inside one Kafka key.
- The order sentinel's ACK mark stops below a run's lowest unfinished offset, so the resend is legal. The consumer refuses to commit a poll offset that no completion covered (`commit_violations_total{kind="uncredited"}`).
- A key resends without a budget once `INGESTION_REQUEST_BUDGET_ATTEMPTS` settles left its messages unfinished since it last finished a run, or at once when its request finished nothing, so a message that never fits the budget still lands. That request carries only such keys and goes ahead of budgeted replays.
- The prototype against the old machinery ([#91480](https://github.com/PostHog/posthog/pull/91480)) showed the cost of doing this earlier: concurrent polls and per-batch accounting push partial handling through the deferral paths. Behind the key table it is one settlement arm.
- Stamp `soft_budget_ms` from config on each key-table request that fits one frame. Unset sends no budget, and `pin_stash` rejects one.

**Interfaces:**

- Modify the ack handling in `grpc_transport.rs`: parse `PARTIAL`; resolve with the accepted count and the unfinished messages.
- Modify `BatcherStateMachine` and `KeyQueues`: add the partial arm and the per-key escalation count.
- Modify `Config`: add `INGESTION_REQUEST_SOFT_BUDGET_MS` (default unset) and `INGESTION_REQUEST_BUDGET_ATTEMPTS` (default 3), bounded at startup against the ack and stall timeouts.

**Metrics:**

- Add `ingestion_consumer_request_budget_partials_total` (counter) and `ingestion_consumer_request_budget_unfinished_messages_total` (counter). The names match the wire: a `PARTIAL` ack with an `unfinished` message list.
- Add `ingestion_consumer_request_budget_escalations_total` (counter), one per key that resends without a budget. A charts warning alert fires on a sustained rate per lane.

### 15. Set the request time budgets (switchover)

**Task:** Set the soft budget per lane: first generous, then real.

**Goal:** A slow request costs a partial redelivery, not a fenced stream and a full replay.

- A charts values PR sets the budget lane by lane. The generous stage is the cycle's verify.
- Watch the partial, unfinished and escalation counters, the key-order sentinel, and stream teardowns.
- Rollback is unsetting the values.

**Interfaces:**

- None in this repository. Config values only.

## Cycle 6: concurrency adapts to worker health

Outcome: request RTT governs the number of requests in flight.
It needs cycle 4: packing makes request sizes uniform, so the RTT signal tunes against comparable requests.
It comes after cycle 5, so the governor tunes once, against budget-capped RTT: set `REQUEST_LATENCY_BUDGET` below the soft budget, or it never shrinks.
The growth signal — ready work waiting on permits — comes from the key-table scheduler's ready queue.

**Verify:** with adaptation off, change 16 reports the decisions it would make.
Exit criterion: `ingestion_consumer_governor_adjustments_total` shows shrink signals under induced worker latency and stays quiet under normal load.

### 16. Add the governor (implement)

**Task:** Add the permit pool and the RTT EWMA (an exponentially weighted moving average). Ship with adaptation off: permits mirror the current per-worker cap.

**Goal:** The governor exists and observes before it constrains.

- The governor gates the pack pass: a dispatch takes a permit, and a settlement returns it. The integration surface is thin, and change 19 later moves the calls into the event loop unchanged.
- Grow the pool by one when ready work waits, no permit is free, and RTT is within budget.
- Shrink the pool by one when the RTT EWMA exceeds `REQUEST_LATENCY_BUDGET`.
- With adaptation off, compute and report every decision without applying it. The signal is verifiable before it constrains.
- Bound the pool with a configured minimum and maximum.
- Keep the 503 backoff in the transport. Exclude 503 waits from the RTT signal.
- Cap each stream channel at `DEPTH_MAX`.

**Interfaces:**

- Add `Governor` in the batcher: the permit pool and the RTT EWMA, adaptation off.
- Modify `Config`: add `REQUEST_LATENCY_BUDGET`, the permit bounds, and `DEPTH_MAX`.

**Metrics:**

- Add `ingestion_consumer_governor_permits` (gauge) and `ingestion_consumer_request_rtt_seconds` (gauge, the EWMA).
- Add `ingestion_consumer_governor_adjustments_total` (counter, direction `grow` or `shrink`). With adaptation off, it counts would-be decisions.

### 17. Enable RTT adaptation (switchover)

**Task:** Turn adaptation on. Request RTT governs the permit pool.

**Goal:** Concurrency shrinks when the worker pool is unhealthy.

- Canary one lane. Watch the permit gauge, the RTT EWMA, and throughput under induced worker latency.
- Rollback is the adaptation switch.

**Interfaces:**

- Modify `Config`: enable adaptation.

### 18. Remove the fixed per-worker cap (cleanup)

**Task:** Remove the per-worker `max_unacked` cap after adaptation is stable on all lanes.

**Goal:** Governor permits are the only in-flight bound.

**Interfaces:**

- Modify `GrpcTransport`: remove the per-worker cap and its config. Stream channels keep `DEPTH_MAX`.

## Cycle 7: the batcher is one single-owner event loop

Outcome: one task owns all batcher state. The mutex and the callback structure are gone.
This is a deliberate structural outcome, not routine cleanup: it is the largest single concurrency simplification in the plan.

**Verify:** the e2e suite and review. The change is behavior-identical, and the consumer-facing metrics must not move.

### 19. Collapse the batcher into one event loop (structure)

**Task:** Move the scheduler and its plumbing into one single-owner task.

**Goal:** Remove the mutex and the callback structure.

- The seam's events become the loop's events: accumulators, settlements, deadlines. The scheduler is already event-shaped, so the loop owns it directly.
- State becomes task-local. The worker-health snapshot stays the only shared read.
- This is the batcher event loop of the design doc. The decisions it drives are already simple (cycle 3), so the transformation is mechanical, but it lands as its own reviewed change.
- No config switch: the change is behavior-identical, and running two plumbing implementations side by side would cost more than it protects. Review and the e2e suite control the risk.

**Interfaces:**

- Modify `Batcher`: one single-owner task replaces the lock, the resolve callbacks, and the per-send tasks. `Dispatcher` dissolves into the loop and is removed.
- Keep `Scheduler` and `Governor` as the loop's components. The consumer-facing interface does not change.

### 20. Remove the stream fences (cleanup)

**Task:** Delete `FenceGuard` and the fence-settle loop from `grpc_transport.rs`.

**Goal:** Keep only the failure logic the new invariant needs.

- Fences go only after the batcher is single-owner. Change 11 makes requeue-before-release a scheduler invariant; change 19 makes it mechanical: one task performs settlement, requeue, and the next dispatch, so no window exists for a newer send to overtake a failure.
- A stream failure returns each request's messages to the key table. That is sufficient.
- This change is deferrable. With one send origin, fences are redundant protection; their only cost is the code.
- Keep: retry classification, busy (503) handling, the ack watchdog, and ack-prefix resolution.

**Interfaces:**

- Remove `FenceGuard` from `transport.rs` and `Fence` with its settle loop from `grpc_transport.rs`.
- Modify `SendError`: drop the fence-guard field.
- Keep `TransportError` and the `WorkerStreamRunner` reconnect logic.
- Remove `ingestion_consumer_worker_stream_fenced_sub_batches_total`. Stream teardowns stay counted.

## Cycle 8: a stalled key stalls only its partition

Outcome: commits advance per partition as groups complete. Needs cycles 2 and 3.

**Verify:** `kafka_consumer_ledger_errors_total` and `kafka_consumer_ledger_gap_offsets_total` stay flat, and `kafka_consumer_ledger_uncommitted_offsets` shows per-partition frontier lag.
Exit criterion at the canary: zero ledger errors and gap walks, and a stalled partition no longer moves the commit rate of other partitions.

### 21. Switch completion to group granularity (switchover)

**Task:** Add a completion granularity, `poll` or `group`. At `group` granularity, mark the ledger per group and stop waiting for whole polls.

**Goal:** A stalled key stalls only its own partition. Other partitions continue to commit.

- The granularity names the unit that completes. `poll`: a poll completes as a whole, oldest first — today's behavior. `group`: each group completes on its own, in any order.
- Cycles 2 and 3 are the prerequisites. Commits come from the frontier, and the old flush, whose per-key order depended on oldest-first completion, is gone. Only commits depend on completion order now, and the frontier gates those.
- At `group` granularity, mark each group's offsets in the ledger when its completion event arrives. Do not aggregate per poll before commits.
- The frontier gates each partition's commit.
- Keep `max_in_flight_batches` as the bound on outstanding work. A poll's slot frees when all its groups are accepted.
- Behavior change: commit timing decouples across partitions and polls. Replay exposure stays inside the admission cap.
- Rollback is the switch back to `poll`.
- Commit pacing is the seam for this cycle. The consumer already hands every taken frontier to a commit pacer (`commit_pacer.rs`) and commits what the pacer hands back. Today's pacer is `ImmediateCommitPacer`: everything handed over is due on the next take, so commits stay per poll. Per-partition commits at `group` granularity would commit on every group completion, which is too many commits, so this cycle gives the pacer an interval: it keeps the latest frontier per partition and hands them out at most once per `CONSUMER_COMMIT_INTERVAL_MS`, and a zero interval is today's immediate pacer. The loop then asks the pacer on a tick, not only after a poll settles, and the tick must not sit in a `select!` next to `collect_batch`, because a dropped collection loses messages before they reach the ledger; the interval bounds the commit delay only if the collection loop itself asks the pacer, otherwise the bound is the interval plus the batch timeout. `ingestion_consumer_committed_offset` is set when a commit is submitted to the client, so a frontier the pacer still holds is not reported as committed. On revoke the pacer forgets the partition; the drain in change 30 commits what the pacer still holds at shutdown. One `CommitPacer` with an interval covers both granularities; `poll` runs it at zero. The commit sentinel and the commit monitor retire here. The sentinel's contiguity check compared the span a poll delivered against the previous commit; at `group` granularity a take no longer maps to one poll's slice, and the ledger already rejects a redelivered offset at charge (`kafka_consumer_ledger_errors_total`) and counts the offsets a frontier walks over (`kafka_consumer_ledger_gap_offsets_total`). The monitor's broker comparison duplicated kminion's per-partition consumer group lag. Checking the take's own window base against the previous take is not a replacement: the ledger sets the base to the frontier it hands out, so that comparison holds by construction.

**Interfaces:**

- Modify `Config`: add the completion granularity and `CONSUMER_COMMIT_INTERVAL_MS`.
- Add `src/settlement/`: a `Settlement` trait (`settle_run`, `settle_poll`, `take_due`, `take_all`, `forget_partitions`) with one implementation per granularity, each owning its commit pacer; the consumer loop calls it unconditionally and has no granularity branches. The poll implementation stays for rollback.
- `CommitPacer::every(interval)` paces the group implementation; the poll implementation runs it at zero. `ImmediateCommitPacer` goes.
- Delete `commit_sentinel.rs` and `commit_monitor.rs`, with `ingestion_consumer_commit_violations_total{kind=gap|out_of_order|overlap}`, `ingestion_consumer_commits_checked_total`, `ingestion_consumer_broker_committed_offset`, `ingestion_consumer_commit_confirmation_lag`, `ingestion_consumer_last_successful_commit_timestamp_seconds` and `ingestion_consumer_commit_monitor_errors_total`. The rdkafka context moves to `rebalance.rs` as `RebalanceContext`, an event source with a revoke hook and an assign hook; the consumer's hooks forget a partition's ledger window and pending frontier together, on either path.

### 22. Delete the per-poll completion path (cleanup)

**Task:** Remove the per-poll completion path after `group` granularity is stable on all lanes.

**Goal:** Group completions are the only completion signal.

**Interfaces:**

- Remove `PollSettlement` and the completion granularity from `Config`.
- Keep the in-flight poll queue and its per-poll aggregation from change 7. The capped polling strategy waits on the oldest poll until change 28 deletes it.

## Cycle 9: replay exposure is bounded per partition

Outcome: no partition's uncommitted work exceeds its budget, in events and bytes. The poll-count admission cap is gone; a pod-wide in-flight limit bounds memory. Needs cycles 2 and 8.

**Verify:** the ledger's uncommitted gauges run on all lanes with no budget set.
Exit criterion: `kafka_consumer_ledger_uncommitted_events` summed per pod tracks the admission cap's occupancy.

The budget is per partition, and so is the pause. One budget for the whole assignment would let a stalled partition fill it and pause every other partition with it, which undoes cycle 8. Per-partition commits are a hard prerequisite for the same reason: at `poll` granularity a stalled partition holds the commits, and so the refunds, of every partition in its poll, so every budget fills together.

### 23. Make the uncommitted accounting exact (implement)

**Task:** Count each partition's uncommitted work in events and bytes exactly: everything polled and not yet covered by a submitted commit. No budget exists yet: the admission cap still governs alone.

**Goal:** The number the budget will bound exists and reports before anything constrains it.

- Charge each message to its partition on poll. The ledger slots already carry the costs (change 2).
- Refund the charge when the commit that covers the message goes out. The charge is always in one place: the ledger's window until a take, then the pacer with the frontier it covers until the settlement hands the frontier out, which is when the consumer submits the commit. Before this change the pacer kept only the offset, so the take itself was the refund and under the interval pacer the gauges ran up to one interval ahead of the commits. A revoked partition drops everything it holds in both places.
- The settlement gauges the result per partition, since it alone sees both places. The budget's config and its pause gauges arrive with change 24, where they are read.

**Interfaces:**

- Modify `CommitPacer`: keep each partition's pending frontier with the charge of every take since the last commit.
- Modify `Settlement`: `charge` charges the ledger and returns what the partition holds uncommitted; `forget_partitions` forgets the ledger too. Both granularities move charge between the ledger and the pacer under one lock and publish the gauges.
- Modify `TopicOffsetLedger`: stop publishing the uncommitted gauges.

**Metrics:**

- `kafka_consumer_ledger_uncommitted_offsets{topic,partition}`, `kafka_consumer_ledger_uncommitted_events{topic,partition}` and `kafka_consumer_ledger_uncommitted_bytes{topic,partition}` now include takes whose commit has not gone out, and the settlement publishes them. No new series.

### 24. Enable the budget (switchover)

**Task:** Set the budget per lane. Pause a partition at its limit and resume it on refund.

**Goal:** Replay exposure is bounded directly, per partition. A stalled partition stops only its own fetch.

- A charts values PR sets the budget lane by lane. The admission cap and the budget both bound work during the transition.
- Derive the first values from the current config: the cap times the batch size, divided by the partitions a pod holds, for events; the byte bound likewise for bytes. The per-pod bound then does not change at the switchover.
- Pause a partition when its outstanding charge reaches the budget on either axis. Resume it only when its charge is back at or under the low watermark on both axes. A pause purges that partition's fetched messages from librdkafka's queue and a resume refetches them, so a gate that reopens on the first refund refetches on every crossing.
- Keep polling while some partitions are paused. A paused partition still serves rebalance callbacks and keeps `max.poll.interval.ms` alive; an unpolled consumer does neither. While every partition is paused, the loop waits on completions without polling Kafka, as it already does when the cap is full; the continuous polling strategy (change 26) removes that wait. librdkafka keeps a partition's pause across a revoke and a reassignment, so the consumer resumes every partition it is assigned: a partition that arrives starts unpaused, with a fresh ledger generation and zero charge.
- Watch the paused-partitions gauge and `ingestion_lag_ms`. Rollback is unsetting the values.

- The budget is a fixed amount per partition, not a share of a pod-wide amount. A rebalance changes how many partitions a pod holds, not how much each one may expose, so the value does not move at rebalances.

**Interfaces:**

- Modify `Config`: add the budget per partition in events and in bytes, and the low watermark as a fraction of the budget (default 0.8). Unset means no constraint.
- Modify `IngestionConsumer`: pause and resume one partition at a time through the Kafka client, from what the settlement reports uncommitted per partition.

**Metrics:**

- Add `ingestion_consumer_budget_paused_partitions` (gauge) and `ingestion_consumer_budget_pauses_total{topic,partition}` (counter).

### 25. Put polling behind a strategy (prepare)

**Task:** Move the decisions of the poll-and-wait loop behind a polling strategy. The existing admission cap becomes the capped strategy.

**Goal:** A second strategy can replace the loop by config, and the capped strategy stays as its rollback.

- The loop and the cap change together. The old loop applies completions only while it waits for the oldest poll, and under steady traffic a full cap is what makes it wait. Without the cap and with the old loop, completions stay unread until every partition pauses at its budget. So the loop, not only the cap, changes.
- The consumer owns the only `recv()` and one `select!` over Kafka, the completions, the batcher's errors, the commit tick, shutdown, and the poll's batch timeout. It hands each event to the strategy, and the strategy returns steps: charge and submit a poll, submit a commit and resume its partitions, stop, or fail. The strategy is synchronous, so its tests feed it events without Kafka.
- Collection builds a poll message by message in a collector that the strategy keeps between events, so a branch that wins the `select!` drops no message. `StreamConsumer::recv` is cancellation safe.
- The rebalance callbacks run inside `recv()`, on the loop's task: rdkafka serves the rebalance event in the same poll that serves messages, and librdkafka delivers no fetched message of a revoked assignment after the revoke. After every wake the loop hands the revoked partitions to the strategy, before the event that woke it, also when the `select!` dropped the `recv()` that ran the callback. The strategy removes their messages from the poll in progress and from its in-flight state.
- A poll therefore holds messages of one assignment per partition, and nothing reads the ledger generation while a poll is built. The poll is charged under the current generation at submit; no `recv()` runs between the end of a poll and its charge.
- The capped strategy admits up to `max_in_flight_polls` polls and frees a slot when the oldest poll is covered. It reads Kafka and applies completions whenever the cap has room, also while every partition is paused.

**Interfaces:**

- Add the `PollingStrategy` trait: event handlers (`received`, `completed`, `revoked`, `ticked`, `shutdown`), `reading()`, `deadline()`, and `next_step() -> Option<Step>`. The consumer picks one implementation at construction and runs a loop generic over it, as it picks one `Settlement`. Add `CappedPolling`: the in-flight poll queue, the per-poll aggregation, and the admission cap.
- Add `Collector`: one poll's messages and per-partition deliveries, built one message at a time, with the batch bounds and timeout.
- Remove the per-message generation stamp from poll collection, and `FetchingPartitions`.
- Modify `IngestionConsumerOptions`: `polling` replaces `max_in_flight_batches`.

### 26. Build the continuous polling strategy (implement)

**Task:** Add a strategy that polls Kafka continuously and applies completions as they arrive. Config selects it per lane. The capped strategy stays the default.

**Goal:** With the continuous strategy, no wait on one poll holds back fetching, completions, or commits. The budget bounds each partition's replay exposure, and a pod-wide in-flight limit bounds memory.

- A poll is submitted when it reaches the batch size or the byte bound, or when the batch timeout passes after its first message. The collection bounds shape one poll, not the amount of admitted work.
- The commit tick fires at the commit interval, capped at 1s, so a refund and the resume it allows go out within one interval.
- Nothing waits on a poll after it is submitted. The consumer passes each partition's ledger generation to `Batcher::submit`, the batcher stamps it on the messages, and each `GroupCompletion` carries it back. The strategy settles a completion under that generation, so no per-poll state maps a completion to its assignment. The ledger rejects a completion of an older generation as stale. Shutdown commits everything settled and stops when no partition holds an uncommitted charge.
- `latest_processed_timestamp_ms` is set when a commit passes a poll's last offset, and the debug UI's `PollCompleted` is not emitted under the continuous strategy.
- The in-flight limit bounds the whole pod: the sum of every partition's uncommitted charge, as the budget counts it. It only gates reading, so the poll in progress still completes and the charge can pass the limit by one poll, which the batch size and the byte bound bound. The budget alone does not bound the pod, because the pod's total grows with the number of partitions it holds. The settlement returns a partition's uncommitted charge when it charges a poll and when a commit hands out offsets, and the poller keeps the latest value per partition. A poll is only the unit fed to the batcher: completions do not change the limit, and a commit frees room when it frees the budget.
- At the in-flight limit, the loop stops reading from Kafka until a commit frees room. While it waits, rebalance callbacks also wait, as they do under the capped strategy. The limit is a safety valve: size it above the budget times the partitions a pod holds, so that it does not bind in steady state.
- The continuous strategy needs `group` granularity, a budget, and an in-flight limit, each of the last two on both events and bytes: a message with no key, value or headers charges zero bytes, so a byte-only limit does not bound how many messages it admits. Without all three the consumer logs a warning and runs the capped strategy, so a lane rolled back to `poll` does not need its polling setting changed too.

**Interfaces:**

- Add `ContinuousPolling`.
- Modify `Config`: add the polling strategy (`capped` by default) and the in-flight limit in events and in bytes. Unset means no limit on that axis.

**Metrics:**

- Add `ingestion_consumer_in_flight_limit_reached_total` (counter, one per time the loop stops reading at the limit). The `kafka_consumer_ledger_uncommitted_*` gauges show each partition's share.

### 27. Poll continuously (switchover)

**Task:** After the budget is stable on all lanes, select the continuous strategy lane by lane, with an in-flight limit.

**Goal:** The budget and the in-flight limit are the only admission bounds on every lane.

- A charts values PR sets the strategy and the limit per lane. Rollback is selecting `capped`.
- Watch `ingestion_lag_ms`, the paused-partitions gauge, the in-flight gauges, and the limit counter. A limit counter that rises in steady state means the limit is too low.

### 28. Delete the capped polling strategy (cleanup)

**Task:** Remove the capped strategy after the continuous strategy is stable on all lanes.

**Goal:** One loop, and no poll-count admission cap.

**Interfaces:**

- Remove `CappedPolling`, the polling strategy setting, and `max_in_flight_batches` from `Config`.
- Remove `ingestion_consumer_in_flight_batches`. The budget gauges and the in-flight gauges replace it.

## Cycle 10: partitions hand off cleanly

Outcome: a revocation drains in bounded time, and a wedged partition fails the process instead of hanging. Needs cycle 3.
Until this cycle, revocation keeps today's behavior: no drain, uncommitted work replays on the new owner, and the old owner's in-flight sends finish as duplicate work. Nothing in cycles 1 to 9 changes that.

**Verify:** rebalance tests with the drain on, then the canary rebalance in change 31.
rdkafka's `MockCluster` runs cooperative rebalances with no broker container, so the drain ordering is testable in the crate. The mock coordinator delays the first join by 3 s and every later round by `session.timeout.ms` minus one second, so test consumers need a session timeout above 3 s.
Exit criterion: `ingestion_consumer_drain_duration_seconds` stays inside the deadline, and `ingestion_consumer_drain_dropped_messages_total` matches the expected replay volume.

### 29. Add revoke and drained markers (prepare)

**Task:** Extend the batcher boundary with a revoke marker in and a drained marker out. Nothing consumes them yet.

**Goal:** The boundary carries the drain protocol before any drain logic exists.

**Interfaces:**

- Modify `Batcher`: add the marker types to the submit and completion channels. `GroupCompletion` does not change shape.

### 30. Build the drain (implement)

**Task:** Implement the drain sequence from section 4 of the design doc, behind a config switch that ships off.

**Goal:** The drain exists and is tested. Off means today's behavior: replay without drain.

- rdkafka runs the rebalance callback inside `poll`, on the task that awaits `recv()`: the consumer loop's own task. The callback must not wait for the drain, because the loop that would end the drain is the one blocked in the callback. On revoke the callback only reports; the loop hands the partitions back later with `incremental_unassign`, which librdkafka allows outside the callback. On assign the callback still calls `incremental_assign` at once; an assignment has nothing to wait for.
- On revoke, send the in-band marker to the batcher, after earlier accumulators.
- The batcher drops queued unsent work for the partition. Kafka replays it for the next owner.
- Wait only for requests in flight. Send the drained marker after the final completion.
- The loop issues one final commit and refunds the remaining charge per partition. It hands the partitions back once every partition in the revoke set has drained, with one `incremental_unassign` carrying the list the callback received. A subset counts as the whole answer, and librdkafka re-revokes the rest in a later round.
- While a revoke waits for the hand-back, librdkafka pauses every assigned partition, not only the revoked ones. The drain window is a pod-wide fetch pause, bounded by the request timeout. Set the rebalance timeout (`max.poll.interval.ms`) above the request timeout, and keep polling through the wait so the callbacks and the liveness clock keep running.
- A lost assignment skips the final commit. When `assignment_lost()` is true at the revoke (the session or `max.poll.interval.ms` expired) or the callback reports an error, the broker has fenced the generation and the commit would fail. Drop the partition's ledger, refund its charge, hand it back at once, and still send the marker so the batcher clears its queues. Completions for it die by epoch.
- Closing the consumer revokes the whole assignment through the same callback, and rdkafka's `Drop` polls until the close completes. A deferred hand-back there never comes and the drop spins forever. A `closing` flag makes the callback answer inline; set it before any path that drops the consumer, the clean shutdown and the fatal-error exit alike.
- Shutdown is a drain of every assigned partition: a revoke marker per partition through the same path, the final commit per drained marker, then one synchronous commit of every partition's last attempted offset, then close. A drain cut short by the graceful-shutdown deadline replays its un-acked tail, bounded by each partition's budget.
- Empty assign events arrive after a hand-back and at the end of a rebalance round. They are no-ops.
- Check completions against the assignment epoch. The epoch already exists on master and rides on `GroupCompletion` since change 7.
- Add a stall deadline per partition, reset only when its frontier moves. Outside a rebalance, an expired deadline fails the process. A partition being drained stands down: its wait is bounded by the request timeout. Replay is at most B.

**Interfaces:**

- Modify `KeyTableScheduler`: drop queued work per partition on the revoke marker.
- Modify `IngestionConsumer` and `OffsetLedger`: the final commit, the refund of abandoned charge, and the stall deadline.
- Modify `RebalanceContext`: override `rebalance` so a revoke reports without unassigning, with the `closing` flag and the lost-assignment path above.
- Modify `Config`: add the drain switch, default off.

**Metrics:**

- Add `ingestion_consumer_drain_duration_seconds` (histogram) and `ingestion_consumer_drain_dropped_messages_total` (counter): drain time and replay volume per revocation.
- Add `ingestion_consumer_partition_stalls_total` (counter): stall-deadline expiries.

### 31. Enable the drain (switchover)

**Task:** Turn the drain on. Canary one lane through a rebalance.

**Goal:** Rebalances hand partitions off with a bounded drain.

- Watch the cycle's exit metrics and the drained markers. Rollback is the switch.

**Interfaces:**

- Modify `Config`: enable the drain.

### 32. Delete the no-drain path (cleanup)

**Task:** Remove the no-drain revoke path after the drain is stable on all lanes.

**Goal:** The drain is the only revoke behavior.

**Interfaces:**

- Remove the no-drain path and the drain switch from `Config`. Keep the epoch checks.

## Monitoring

The steady-state dashboard after the migration:

- Delivery: `ingestion_lag_ms`, the `ingestion_consumer_messages_processed_total` rate, and the two sentinel violation counters, which must stay at zero.
- Commits: `kafka_consumer_ledger_uncommitted_offsets` per partition (frontier lag, and the ring-leak detector) and the `ingestion_consumer_offset_commits_total` rate.
- Scheduling: the key-table gauges and `ingestion_consumer_parked_retries_total`.
- Admission: `kafka_consumer_ledger_uncommitted_events` and `kafka_consumer_ledger_uncommitted_bytes` per partition, and `ingestion_consumer_budget_paused_partitions`.
- Requests: the request-size histograms, `ingestion_consumer_transport_duration_seconds`, `ingestion_consumer_governor_permits`, `ingestion_consumer_request_rtt_seconds`, and `ingestion_consumer_request_budget_partials_total`.
- Rebalance: `ingestion_consumer_drain_duration_seconds` and `ingestion_consumer_drain_dropped_messages_total`.

The budget occupancy and the request-size histograms are also the worker-autoscaling signals from section 5 of the design doc.

## Cycle dependencies

The cycles do not have to run linearly.
A solid arrow is a hard dependency.
A dashed arrow is an ordering preference: its reason is stated in the target cycle's intro, and breaking it costs retuning or a larger diff, not correctness.

```mermaid
flowchart LR
    C1["1: one send origin"]
    C2["2: frontier commits"]
    C3["3: one request per key"]
    C4["4: target-sized requests"]
    C5["5: partial redelivery"]
    C6["6: adaptive concurrency"]
    C7["7: single-owner batcher"]
    C8["8: decoupled commits"]
    C9["9: bounded replay per partition"]
    C10["10: clean handoff"]
    PR(["#115388 worker side"])

    C1 --> C3
    C3 --> C4
    C3 --> C5
    C3 --> C6
    C3 --> C7
    C3 --> C8
    C3 --> C10
    C2 --> C8
    C2 --> C9
    PR --> C5
    C4 -.-> C5
    C4 -.-> C6
    C5 -.-> C6
    C6 -.-> C7
    C8 --> C9
    C9 -.-> C10
```

What the graph permits:

- Cycles 1 and 2 start in parallel. Neither depends on the other.
- After cycle 3, four tracks can run side by side: the request track (4, then 5, then 6), the collapse (7), decoupled commits (8, once cycle 2 is done), and the drain (10).
- Cycle 9 hard-depends on cycles 2 and 8. The budget and the pause are per partition, and only per-partition commits refund one partition without waiting for the others.
- The dashed edges into cycle 6 are the tune-once argument: packing makes request sizes uniform, and the time budget caps RTT, so the governor tunes against the final distribution.
- The dashed edge into cycle 7 saves a move: the loop takes the scheduler, packer, and governor in one transformation instead of re-homing components later.
- The dashed edge into cycle 10 covers one detail: the drain refunds budget charge, which exists after cycle 9. Without cycle 9 the drain refunds nothing and still works.

## Later work

- The keyless lane: today an unkeyed message gets a synthetic per-message key and its own group. A separate keyless lane per partition can remove that overhead.
- Partition affinity as a packing hint (open question 6). Measure frontier coupling first.
- Recover from a ledger violation without a restart. For now a violation stops the consumer, and the restart replays from the last commit. A seek back to the partition's last commit would keep the pod running, but it needs the revoke path for one partition (purge its queued messages, strip its in-flight slices, drop its pending frontier) and the offset of its last submitted commit, which nothing tracks yet. Worth it only if violations show up in practice.
