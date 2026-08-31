# Driver-model implementation plan

Status: **draft, for discussion**.

This plan implements the [driver-model redesign](https://github.com/PostHog/posthog/blob/pl/ingestion/consumer-redesign-doc/rust/ingestion-consumer/docs/driver-model.md) (#89277) in small steps.
Each step is one PR.

## Starting point

The plan starts from current master.
Master already contains two parts of the design:

- The routing key is the opaque Kafka message key (#90282). A message without a key gets a synthetic per-message key.
- Each worker has one long-lived ordered gRPC stream (#85238, #90790). The stream runner keeps an un-acked ledger, resolves acks in send order, applies an ack watchdog, and fences on failure.

An assignment epoch also exists.
A rebalance increments it, and every sub-batch carries it.

These components stay as they are: the stream runners, the P2C router, the aperture, the worker registry, the commit sentinel, the commit monitor, and the key-order sentinel.

## Rules for the sequence

- Each change is one PR.
- A change is a structure change or a logic change, never both.
- A structure change does not change behavior. The e2e tests must pass without edits.
- Structure prepares logic. Every logic change comes after the structure changes that make it small. A new implementation ships unselected in a structure change; a logic change selects it.
- Swap the smallest piece that removes the most complexity. Components that already match the target design are not rebuilt.
- A logic change ships behind a config switch when a switch is possible. When a switch is not possible, it ships as a canary on one lane.
- Old code is deleted, not edited. When a cutover holds on all lanes, one structure change removes the old implementation whole.
- The commit sentinel and the key-order sentinel stay enabled through the migration. They verify each step in production.

## Changes

Part 1 prepares the structure (changes 1 to 6).
Behavior does not change.
The offset ledger and the key-table scheduler are both built here, tested, and left unselected.

Part 2 cuts over and simplifies (changes 7 to 16).
Each cutover is a switch flip made small by part 1, with the switch as the rollback.
Each deletion follows its cutover.

The swap unit inside the batcher is the **scheduler**: the decision core that says which runs may go to a worker now, and where.
That is where the complexity concentrates — the pins, the stash, and the flush interplay.
Placement (P2C, aperture) and send execution (stream runners) already match the target design and are not rebuilt.
The single-owner event loop is only plumbing once the scheduler is simple, so it moves last.

Each change ends with its interface impact: the types it adds, modifies, or removes.

| # | Type | Change |
| --- | --- | --- |
| 1 | Structure | Add the offset ledger module |
| 2 | Structure | Run the ledger in shadow mode |
| 3 | Structure | Demux polls into groups |
| 4 | Structure | Encapsulate the worker batcher |
| 5 | Structure | Extract the scheduler seam |
| 6 | Structure | Build the key-table scheduler |
| 7 | Structure | Commit from the ledger frontier |
| 8 | Logic | Switch to the key-table scheduler |
| 9 | Structure | Delete the old scheduler |
| 10 | Structure | Remove the stream fences |
| 11 | Structure | Collapse the batcher into one event loop |
| 12 | Logic | Complete batches in any order |
| 13 | Logic | Replace the batch window with budget B |
| 14 | Logic | Pack requests toward target T |
| 15 | Logic | Add the RTT dispatch governor |
| 16 | Logic | Add the bounded revocation drain |

### 1. Add the offset ledger module (structure)

**Task:** Create `ledger.rs` with a per-partition offset ring. Do not wire it in.

**Goal:** Make commit contiguity a property of a data structure.

- One ledger per partition. The ledger is a dense ring of delivered offsets.
- Each slot records: complete or not, event count, byte count. The counts serve the budget in change 13.
- Operations: `charge` adds a delivered offset. `complete` marks an offset done. `frontier` removes the contiguous done prefix and returns the highest removed offset.
- Completions can arrive in any order. The frontier moves only over completed slots.
- Kafka delivers offsets with gaps (transactions, compaction). Contiguity means the prefix of delivered offsets, not offset arithmetic.
- Add property tests: out-of-order completion, monotonic frontier, offset gaps, ring capacity.

**Interfaces:**

- Add `OffsetLedger` in `ledger.rs`: `charge`, `complete`, `frontier`. No callers yet. The name avoids a clash with the stream runner's internal un-acked ledger.

### 2. Run the ledger in shadow mode (structure)

**Task:** Wire the ledger next to the commit path. Compare its frontier with each real commit. Do not change what the consumer commits.

**Goal:** Prove the ledger against production traffic before it owns the commits.

- New config: the ledger mode, `off`, `shadow`, or `active`. This change ships `shadow`. Change 7 ships `active`.
- Charge every delivered offset into its partition ledger during `collect_batch`.
- When a batch completes, mark all its offsets complete.
- At each commit, compare the partition's frontier with the offset the current path commits. With oldest-first completion, the two must be equal.
- On a mismatch: increment a counter and log the partition with both offsets. Do not block the commit.
- On revoke, drop the partition's ledger. This mirrors the commit sentinel's `forget_partitions`.
- Soak on all lanes. The exit criterion is a mismatch count of zero across deploys and rebalances.

**Interfaces:**

- Modify `Config`: add the ledger mode.
- Modify `IngestionConsumer`: own one `OffsetLedger` per partition. Charge in `collect_batch`, complete on batch completion, compare in `commit_offsets`.
- Modify the revoke path (`SentinelContext`): drop revoked partitions' ledgers.

### 3. Demux polls into groups (structure)

**Task:** Change `collect_batch` to output groups. A group is one poll's consecutive messages for one routing key on one partition.

**Goal:** Create the accumulator shape from the design doc.

- Group messages per partition first, then per routing key. Keep offset order inside each group.
- The dispatcher flattens the groups back into one message list. Sub-batch assembly does not change.
- Change 4 submits them to the batcher as the accumulator.

**Interfaces:**

- Add `Group` in `types.rs`: partition, routing key, messages in offset order.
- Modify `CollectedBatch`: carries `Vec<Group>` instead of a flat message list.
- Modify `Dispatcher::assign_and_send`: takes groups and flattens them. `group_messages_by_routing_key` moves to the collect path.

### 4. Encapsulate the worker batcher (structure)

**Task:** Put today's dispatch machinery behind one boundary. The consumer loop and the batcher exchange plain values.

**Goal:** The dispatch concurrency becomes an implementation detail behind one interface.

- Interface in: one accumulator per poll — the poll's demuxed groups, submitted on the consumer loop in poll order.
- Interface out: one completion event per group, with its partition, offsets, and accepted count.
- This is the design doc's boundary: accumulators in, completions out. It is the final shape and does not change again.
- No batch identity crosses the boundary. The facade mints an internal batch id per accumulator for the old machinery and the wire request. The consumer correlates completions by partition and offset — the same key the ledger uses.
- The facade breaks each resolved send into its groups. The resolution paths already carry them (`routing_keys`, `key_offsets`), and a send is all-or-nothing.
- Move inside the boundary: assignment, scatter, the deferred flush, the eager flush, the worker registry, the router, and the stream runners.
- The facade replicates today's behavior exactly, including the oldest-first flush pacing. This is code motion, not redesign.
- The consumer loop keeps: poll collection, commits, the sentinels, and the batch window. It tracks each poll's offset spans and completes the poll when completions cover them, so completion and commit behavior do not change.
- Changes 5 and 6 carve the scheduler seam inside this boundary.

**Interfaces:**

- Add `Accumulator`: one poll's groups, in poll order.
- Add `Batcher` in `batcher.rs`: `submit(Accumulator)` in, a channel of `GroupCompletion` out. It owns `Dispatcher`, `GrpcTransport`, `WorkerRegistry`, and the send tasks. It mints batch ids internally.
- Add `GroupCompletion`: partition, offsets, accepted count. No batch id.
- Modify `IngestionConsumer`: drop `scatter`, `flush_deferred`, and the eager-flush loop — they move into the batcher. Keep collect, commit, and the window. Correlate completions to polls by partition and offset.
- Modify `main.rs`: construct one `Batcher`. The consumer no longer sees the dispatcher or the transport.
- Internalize `Dispatcher`'s resolve and accounting methods (`on_sub_batch_*`, `defer_failed`, `eager_flush_*`, `take_eager_accepted`): only the batcher calls them.

### 5. Extract the scheduler seam (structure)

**Task:** Move every ordering and placement decision inside the batcher behind one interface. Keep the current semantics.

**Goal:** Isolate the decision core from the plumbing, so the smallest valuable piece can swap.

- The scheduler decides which runs may go to a worker now, and where. Nothing else in the batcher decides that.
- Interface in: events. A group arrives. A request settles, with success or failure. A retry deadline fires.
- Interface out: dispatches. One dispatch is one run of one key on one worker.
- The first implementation preserves today's semantics: pins, the stash, deferral on drain, the flush pacing, and the eager release. This is code motion from `assign`, `flush_deferred`, `on_sub_batch_resolved`, and the eager path.
- The plumbing (tasks, channels, the mutex) stays as it is. Only the decisions move.
- The seam makes today's implicit ordering rules explicit and reviewable in one place.

**Interfaces:**

- Add the `Scheduler` trait in `scheduler.rs`: `on_groups`, `on_settled`, `on_deadline` in; `Vec<Dispatch>` out.
- Add `Dispatch`: one run of one key, with the chosen worker.
- Add `PinStashScheduler`: the current semantics, moved out of `Dispatcher::assign`, `flush_deferred`, `on_sub_batch_resolved`, and the eager release. It owns `PinTable` and `Stash` unchanged.
- Modify `Dispatcher`: shrinks to plumbing — the lock, in-flight load, metrics, and seam calls.

### 6. Build the key-table scheduler (structure)

**Task:** Write the target scheduler as a second implementation of the seam. Do not select it.

**Goal:** The replacement for the ordering core exists, fully tested, before any behavior changes.

- The key table: one FIFO queue per key. A key is runnable when it has queued work and no outstanding request.
- On arrival: enqueue, and dispatch one contiguous run when the key is runnable. Dispatch marks the key outstanding.
- On settlement: clear the flag. Success dispatches the key's next run. Failure returns the run to the front of its queue.
- A parked-retry deadline covers the keys no settlement can release: unroutable groups, and keys behind a failed send.
- Placement is stateless: the existing P2C and aperture pick a worker per dispatch. There are no pins.
- The seam is events in, dispatches out. Test the scheduler deterministically: script arrivals, settlements, and failures. Assert per-key order.

**Interfaces:**

- Add `KeyTableScheduler` and `KeyTable` in `key_table.rs`: per-key FIFO, outstanding flag, parked list. Implements `Scheduler`. Tests only, no production callers.

### 7. Commit from the ledger frontier (structure)

**Task:** Set the ledger mode to `active`. The frontier becomes the committed offset. Keep oldest-first batch completion.

**Goal:** The frontier produces the same commits as the old code, and change 2 already proved that.

- Commit each partition's frontier instead of the batch's max offset.
- With oldest-first completion, the output is identical to the old path.
- The commit sentinel stays on and checks contiguity and monotonicity.
- Rollback is the config switch back to `shadow`.
- Delete the old commit computation after `active` holds on all lanes.

**Interfaces:**

- Modify `Config`: default the ledger mode to `active`.
- Modify `IngestionConsumer::commit_offsets`: read the committed offset from `OffsetLedger::frontier`. The old computation survives only as the shadow comparison, then is deleted.

### 8. Switch to the key-table scheduler (logic)

**Task:** Select the key-table scheduler with config. Canary one lane, then roll out.

**Goal:** One ordering rule replaces pins, the stash, and the flush paths.

- The switch changes the ordering rule and nothing else. Placement, transport, and completion accounting do not change in this PR.
- At most one outstanding request per key preserves per-key order. Nothing else does, and nothing else must.
- This is proposal 2 of the design doc: sticky pins are removed. Measure worker key-cache locality before and after (open question 3).
- Watch: the key-order sentinel, ack latency, and the no-progress watchdog.
- Rollback is the config switch back to the old scheduler.

**Interfaces:**

- Modify `Config`: add the scheduler selection.
- Modify the batcher construction: select `KeyTableScheduler` or `PinStashScheduler`.
- No interface shapes change.

### 9. Delete the old scheduler (structure)

**Task:** Remove the old scheduler implementation after change 8 holds on all lanes.

**Goal:** The old concurrency goes in one deletion, not in edits.

- Removes: the pin table, the stash, both flush drivers, the eager-flush channel and its credits, `DISPATCHER_EAGER_DEFERRED_FLUSH`, and the scheduler switch.
- The plan never edits this machinery. It is isolated in change 5, bypassed in change 8, and deleted here.

**Interfaces:**

- Remove `PinStashScheduler`, `PinTable`, `Stash`, `sticky_pin_for`, `EagerFlush`, and the eager credits.
- Remove from `Config`: `DISPATCHER_EAGER_DEFERRED_FLUSH` and the scheduler selection.
- Modify `Dispatcher`: remove the dead resolve plumbing (`clears_deferral`, `send_failed`, the flush drivers).

### 10. Remove the stream fences (structure)

**Task:** Delete `FenceGuard` and the fence-settle loop from `grpc_transport.rs`.

**Goal:** Keep only the failure logic the new invariant needs.

- After change 9, the scheduler blocks every key with a failed request: the key is not runnable, so no newer send for it can enter a stream.
- A stream failure returns each request's messages to the key table. That is sufficient.
- Keep: retry classification, busy (503) handling, the ack watchdog, and ack-prefix resolution.

**Interfaces:**

- Remove `FenceGuard` from `transport.rs` and `Fence` with its settle loop from `grpc_transport.rs`.
- Modify `SendError`: drop the fence-guard field.
- Keep `TransportError` and the `WorkerStreamRunner` reconnect logic.

### 11. Collapse the batcher into one event loop (structure)

**Task:** Move the scheduler and its plumbing into one single-owner task.

**Goal:** Remove the mutex and the callback structure.

- The seam's events become the loop's events: accumulators, settlements, deadlines. The scheduler is already event-shaped, so the loop owns it directly.
- State becomes task-local. The worker-health snapshot stays the only shared read.
- This is the batcher event loop of the design doc. It is plumbing now: the decisions it drives are already simple.

**Interfaces:**

- Modify `Batcher`: one single-owner task replaces the lock, the resolve callbacks, and the per-send tasks. `Dispatcher` dissolves into the loop and is removed.
- Keep `Scheduler` as the loop's decision component. The consumer-facing interface does not change.

### 12. Complete batches in any order (logic)

**Task:** Replace the oldest-first await with completion events.

**Goal:** A stalled batch stalls only its own partitions. Other partitions continue to commit.

- Changes 7 and 9 are the prerequisites. Commits come from the frontier, and the old flush, whose per-key order depended on oldest-first completion, is gone. Only commits depend on completion order now, and the frontier gates those.
- Mark each group's offsets in the ledger when its completion event arrives. Stop aggregating completions per poll before commits.
- The frontier gates each partition's commit.
- Keep `max_in_flight_batches` as the bound on outstanding work. A batch slot frees when all its groups are accepted.
- Behavior change: commit timing decouples across partitions and batches. Replay exposure stays inside the batch window.

**Interfaces:**

- Modify `IngestionConsumer::process`: select over `GroupCompletion` events. Remove the ordered `InFlightBatch` queue and the per-poll aggregation from change 4.
- Modify the batch bookkeeping: a batch is only a window slot that frees when its groups are accepted.

### 13. Replace the batch window with budget B (logic)

**Task:** Poll only while uncommitted work is below B. B counts events and bytes.

**Goal:** Bound replay exposure directly. Poll continuously when workers keep up.

- Charge each message on poll. The ledger slots already carry the costs (change 1).
- Refund the charge when the commit that covers the message is issued.
- Remove `max_in_flight_batches`. The batch reduces to a per-poll accumulator.
- Pause and resume the poll at the budget limit. Do not stop servicing Kafka callbacks.
- New config: the budget in events and in bytes.

**Interfaces:**

- Modify `Config`: add the budget; remove `max_in_flight_batches`.
- Modify `IngestionConsumer`: gate polling on the outstanding charge. Refund from `OffsetLedger` on commit. Remove the window-slot bookkeeping from change 12.

### 14. Pack requests toward target T (logic)

**Task:** Add the packer to the scheduler, with target size T and `PACK_LATENCY_BUDGET`.

**Goal:** Request size becomes deliberate. Fan-out becomes demand-driven.

- Pack runs from multiple runnable keys into one request near T. T counts events and bytes.
- Emit immediately when the ready work can fill the free permits with near-T requests. Otherwise arm the pack deadline.
- When the deadline expires, emit partial requests.
- `PACK_LATENCY_BUDGET = 0` restores send-on-arrival. That is the off switch.
- Router order inside a pass: fill open requests on healthy workers first, then pick a worker with P2C from the aperture slice. Partition affinity is a tie-breaker only.
- Check the worker side first: a request now spans polls and keys. Confirm the worker's `concurrentBatches` accounting and the meaning of `batch_id` still hold.

**Interfaces:**

- Add `Packer` inside `KeyTableScheduler`.
- Modify `Dispatch`: one request may carry runs from several keys.
- Modify `Config`: add T and `PACK_LATENCY_BUDGET`. The worker proto does not change.

### 15. Add the RTT dispatch governor (logic)

**Task:** Replace the fixed per-worker un-acked cap with a permit pool that request RTT governs.

**Goal:** Reduce crash exposure when the worker pool is unhealthy.

- Grow the pool by one when ready work waits, no permit is free, and RTT is within budget.
- Shrink the pool by one when the RTT EWMA exceeds `REQUEST_LATENCY_BUDGET`.
- Bound the pool with a configured minimum and maximum.
- Keep the 503 backoff in the transport. Exclude 503 waits from the RTT signal.
- Cap each stream channel at `DEPTH_MAX`.

**Interfaces:**

- Add `Governor` in the batcher loop: the permit pool and the RTT EWMA.
- Modify `GrpcTransport`: governor permits replace the per-worker `max_unacked` cap. Stream channels get `DEPTH_MAX` capacity.
- Modify `Config`: add `REQUEST_LATENCY_BUDGET`, the permit bounds, and `DEPTH_MAX`.

### 16. Add the bounded revocation drain (logic)

**Task:** Implement the drain sequence from section 4 of the design doc.

**Goal:** A revoked partition hands off cleanly. A wedged partition fails the process instead of hanging forever.

- On revoke, send an in-band marker to the batcher, after earlier accumulators.
- The batcher drops queued unsent work for the partition. Kafka replays it for the next owner.
- Wait only for requests in flight. Send a drained marker after the final completion.
- The loop issues one final commit, refunds the remaining charge, and unassigns the partition.
- Check completions against the assignment epoch. The epoch already exists on master.
- Add a stall deadline per partition. Outside a rebalance, an expired deadline fails the process. Replay is at most B.

**Interfaces:**

- Modify `Batcher`: add a revoke marker input and a drained marker output. `GroupCompletion` does not change shape.
- Modify `KeyTableScheduler`: drop queued work per partition on revoke.
- Modify `IngestionConsumer` and `OffsetLedger`: the final commit, the refund of abandoned charge, and the per-partition stall deadline.

## Later work

- The keyless lane: today an unkeyed message gets a synthetic per-message key and its own group. A separate keyless lane per partition can remove that overhead.
- Partition affinity as a packing hint (open question 6). Measure frontier coupling first.
