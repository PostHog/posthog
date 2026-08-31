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

## The cycle model

Work proceeds in cycles.
Each cycle delivers one outcome: a property of the system that holds from then on.
A cycle has four phases:

1. **Prepare**: structure changes that carve the seams. No behavior change.
2. **Implement**: build the new component, fully tested, not selected.
3. **Switchover**: config selects the new component. Staged where possible: shadow, then canary, then all lanes. The config is the rollback.
4. **Cleanup**: one deletion removes the old component and the switch.

Rules:

- Each change is one PR.
- Prepare, implement, and cleanup changes do not change behavior. The e2e tests must pass without edits.
- Only a switchover may change behavior. Some do not (a switchover with identical output is still staged and reversible).
- Old code is deleted in cleanup, never edited.
- Dead code is deleted before a seam is carved around it. A cleanup of a switch that never shipped can open a cycle (change 1).
- A structural outcome with no behavior change needs no switchover. Review and the e2e tests control its risk. The table labels such a change Structure (change 13).
- A cycle's cleanup lands only after its switchover holds on all lanes.
- Swap the smallest piece that removes the most complexity. Components that already match the target design are not rebuilt.
- The commit sentinel and the key-order sentinel stay enabled through every cycle.

Cycle 1 lands first: two fast, behavior-preserving complexity wins with no dependency on anything else.
After that, the cycles run in order, with one exception: cycle 3 does not depend on cycle 2, so it can proceed while cycle 2 soaks.
Cycle 5 needs cycles 2 and 3.

The swap unit in cycle 3 is the **scheduler**: the decision core that says which runs may go to a worker now, and where.
That is where the complexity concentrates — the pins, the stash, and the flush interplay.
The single-owner event loop follows as its own outcome (cycle 4), once the scheduler is simple.

Each change ends with its interface impact: the types it adds, modifies, or removes.

| # | Cycle | Phase | Change |
| --- | --- | --- | --- |
| 1 | 1 one resolve protocol | Cleanup | Delete the dead eager flush |
| 2 | 1 one resolve protocol | Prepare | Extract fence-safe send resolution |
| 3 | 2 frontier commits | Implement | Add the offset ledger module |
| 4 | 2 frontier commits | Switchover | Run the ledger in shadow mode |
| 5 | 2 frontier commits | Switchover | Commit from the ledger frontier |
| 6 | 2 frontier commits | Cleanup | Delete the old commit computation |
| 7 | 3 per-key order | Prepare | Demux polls into groups |
| 8 | 3 per-key order | Prepare | Encapsulate the worker batcher |
| 9 | 3 per-key order | Prepare | Extract the scheduler seam |
| 10 | 3 per-key order | Implement | Build the key-table scheduler |
| 11 | 3 per-key order | Switchover | Switch to the key-table scheduler |
| 12 | 3 per-key order | Cleanup | Delete the old scheduler |
| 13 | 4 single-owner batcher | Structure | Collapse the batcher into one event loop |
| 14 | 4 single-owner batcher | Cleanup | Remove the stream fences |
| 15 | 5 decoupled commits | Switchover | Complete polls in any order |
| 16 | 5 decoupled commits | Cleanup | Delete the ordered completion path |
| 17 | 6 bounded replay | Implement | Add the budget accounting |
| 18 | 6 bounded replay | Switchover | Enable the budget |
| 19 | 6 bounded replay | Cleanup | Remove the in-flight admission cap |
| 20 | 7 target-sized requests | Implement | Add the packer |
| 21 | 7 target-sized requests | Switchover | Set the packing targets |
| 22 | 8 adaptive concurrency | Implement | Add the governor |
| 23 | 8 adaptive concurrency | Switchover | Enable RTT adaptation |
| 24 | 8 adaptive concurrency | Cleanup | Remove the fixed per-worker cap |
| 25 | 9 clean handoff | Prepare | Add revoke and drained markers |
| 26 | 9 clean handoff | Implement | Build the drain |
| 27 | 9 clean handoff | Switchover | Enable the drain |
| 28 | 9 clean handoff | Cleanup | Delete the no-drain path |

## Cycle 1: one send origin, one resolve protocol

Outcome: the eager send path is gone, and every send resolves through one fence-safe helper.
This cycle has no switchover: the eager flush was never enabled, and the helper encodes the current order.

### 1. Delete the dead eager flush (cleanup)

**Task:** Remove the eager deferred flush. The flag that enables it is off everywhere.

**Goal:** One send origin fewer before any seam is carved.

- `DISPATCHER_EAGER_DEFERRED_FLUSH` is default off, and no deployment sets it. Confirm against a fresh charts checkout before this ships.
- The completion-time flush already does all the draining in production. Behavior does not change.
- Carrying the eager path through the seam extraction would preserve code that does not run.

**Interfaces:**

- Remove `EagerFlush`, `run_eager_flush_loop`, `send_eager_flush`, and `DISPATCHER_EAGER_DEFERRED_FLUSH`.
- Modify `Dispatcher`: remove `set_eager_flush_sender`, `release_next_groups`, `eager_flush_*`, `take_eager_accepted`, and the eager pending and accepted accounting.

### 2. Extract fence-safe send resolution (prepare)

**Task:** Move the send-and-resolve protocol into one helper. Every send path uses it.

**Goal:** Fence handling exists in one place and cannot be forgotten.

- The protocol is spread over the scatter and flush paths today: begin the send at the ordering point, await the pending send, then resolve.
- On success: ack the key offsets, resolve the dispatcher state, record health.
- On failure: defer the messages, then drop the `fence_guard`, then resolve, then record health. This order is the contract. A guard dropped early lets newer work leapfrog a fenced failure.
- No behavior change. The helper encodes the current order.

**Interfaces:**

- Add a resolve helper in `consumer.rs` that owns the success and failure sequences.
- Modify `scatter` and the flush path to call it. `SendError` and `PendingSubBatch` do not change.

## Cycle 2: commits come from the frontier

Outcome: commit contiguity is a property of a data structure, not of completion order.

### 3. Add the offset ledger module (implement)

**Task:** Create `ledger.rs` with a per-partition offset ring. Do not wire it in.

**Goal:** Make commit contiguity a property of a data structure.

- One ledger per partition. The ledger is a dense ring of delivered offsets.
- Each slot records: complete or not, event count, byte count. The counts serve the budget in change 17.
- Operations: `charge` adds a delivered offset. `complete` marks an offset done. `frontier` returns the highest contiguous done offset and does not mutate. `take_frontier` consumes the done prefix up to the frontier.
- The read/consume split matters: shadow comparison reads `frontier` repeatedly without consuming state. Only an issued commit calls `take_frontier`.
- Completions can arrive in any order. The frontier moves only over completed slots.
- Kafka delivers offsets with gaps (transactions, compaction). Contiguity means the prefix of delivered offsets, not offset arithmetic.
- Add property tests: out-of-order completion, monotonic frontier, `frontier` idempotence, offset gaps, ring capacity.

**Interfaces:**

- Add `OffsetLedger` in `ledger.rs`: `charge`, `complete`, `frontier` (non-mutating), `take_frontier` (consuming). No callers yet. The name avoids a clash with the stream runner's internal un-acked ledger.

### 4. Run the ledger in shadow mode (switchover)

**Task:** Wire the ledger next to the commit path. Compare its frontier with each real commit. Do not change what the consumer commits.

**Goal:** Prove the ledger against production traffic before it owns the commits.

- New config: the ledger mode, `off`, `shadow`, or `active`. This change ships `shadow`. Change 5 ships `active`.
- Charge every delivered offset into its partition ledger during `collect_batch`.
- When a poll completes, mark all its offsets complete.
- At each commit, compare the partition's `frontier` — the non-mutating read — with the offset the current path commits. With oldest-first completion, the two must be equal.
- On a mismatch: increment a counter and log the partition with both offsets. Do not block the commit.
- On revoke, drop the partition's ledger. This mirrors the commit sentinel's `forget_partitions`.
- Soak on all lanes. The exit criterion is a mismatch count of zero across deploys and rebalances.

**Interfaces:**

- Modify `Config`: add the ledger mode.
- Modify `IngestionConsumer`: own one `OffsetLedger` per partition. Charge in `collect_batch`, complete on poll completion, compare in `commit_offsets`.
- Modify the revoke path (`SentinelContext`): drop revoked partitions' ledgers.

### 5. Commit from the ledger frontier (switchover)

**Task:** Set the ledger mode to `active`. The frontier becomes the committed offset. Keep oldest-first completion.

**Goal:** The frontier produces the same commits as the old code, and change 4 already proved that.

- Commit each partition's frontier instead of the poll's max offset.
- Call `take_frontier` only when the commit is issued. Shadow mode keeps reading `frontier` and never consumes.
- With oldest-first completion, the output is identical to the old path.
- The commit sentinel stays on and checks contiguity and monotonicity.
- Rollback is the config switch back to `shadow`.

**Interfaces:**

- Modify `Config`: default the ledger mode to `active`.
- Modify `IngestionConsumer::commit_offsets`: read the committed offset from the ledger. The old computation survives as the shadow comparison until change 6.

### 6. Delete the old commit computation (cleanup)

**Task:** Remove the old commit computation after `active` holds on all lanes.

**Goal:** The frontier is the only commit source.

- Remove the old per-poll commit computation and the shadow comparison.

**Interfaces:**

- Modify `IngestionConsumer::commit_offsets`: frontier only.
- Modify `Config`: remove the ledger mode.

## Cycle 3: one rule preserves per-key order

Outcome: at most one outstanding request per key is the only ordering mechanism. Pins, the stash, and the flush paths are gone.

### 7. Demux polls into groups (prepare)

**Task:** Change `collect_batch` to output groups. A group is one poll's consecutive messages for one routing key on one partition.

**Goal:** Create the accumulator shape from the design doc.

- Group messages per partition first, then per routing key. Keep offset order inside each group.
- The dispatcher flattens the groups back into one message list. Sub-batch assembly does not change.
- Change 8 submits them to the batcher as the accumulator.

**Interfaces:**

- Add `Group` in `types.rs`: partition, routing key, messages in offset order.
- Modify `CollectedBatch`: carries `Vec<Group>` instead of a flat message list.
- Modify `Dispatcher::assign_and_send`: takes groups and flattens them. `group_messages_by_routing_key` moves to the collect path.

### 8. Encapsulate the worker batcher (prepare)

**Task:** Put today's dispatch orchestration behind one boundary. The consumer loop and the batcher exchange plain values.

**Goal:** The dispatch concurrency becomes an implementation detail behind one interface.

- Interface in: one accumulator per poll — the poll's demuxed groups, submitted on the consumer loop in poll order.
- Interface out: one completion event per group, with its partition, offsets, and accepted count.
- This is the design doc's boundary: accumulators in, completions out. It is the final shape and does not change again.
- No batch identity crosses the boundary. The facade mints an internal batch id per accumulator for the old machinery and the wire request. The consumer correlates completions by partition and offset — the same key the ledger uses.
- The facade breaks each resolved send into its groups. The resolve helper (change 2) already carries them (`routing_keys`, `key_offsets`), and a send is all-or-nothing.
- Only orchestration moves inside the boundary: assignment, scatter, the deferred flush, and the resolve helper.
- `GrpcTransport`, `Router`, and `WorkerRegistry` keep their construction and ownership in `main.rs`. The batcher takes shared handles. Readiness gating, discovery reconciliation, the reaper, and the debug endpoints do not change.
- The facade replicates today's behavior exactly, including the oldest-first flush pacing. This is code motion, not redesign.
- The consumer loop keeps: poll collection, commits, the sentinels, and the admission cap. It tracks each poll's offset spans and completes the poll when completions cover them, so completion and commit behavior do not change.
- Changes 9 and 10 carve the scheduler seam inside this boundary.

**Interfaces:**

- Add `Accumulator`: one poll's groups, in poll order.
- Add `Batcher` in `batcher.rs`: `submit(Accumulator)` in, a channel of `GroupCompletion` out. It owns `Dispatcher` and the send tasks, and holds shared handles to `GrpcTransport`, `Router`, and `WorkerRegistry`. It mints batch ids internally.
- Add `GroupCompletion`: partition, offsets, accepted count. No batch id.
- Modify `IngestionConsumer`: drop `scatter` and `flush_deferred` — they move into the batcher. Keep collect, commit, and the admission cap. Correlate completions to polls by partition and offset.
- Modify `main.rs`: construct one `Batcher` from the existing transport, registry, and router. The consumer no longer sees the dispatcher.
- Internalize `Dispatcher`'s resolve methods (`on_sub_batch_*`, `defer_failed`): only the batcher calls them.

### 9. Extract the scheduler seam (prepare)

**Task:** Move every ordering and placement decision inside the batcher behind one interface. Keep the current semantics.

**Goal:** Isolate the decision core from the plumbing, so the smallest valuable piece can swap.

- The scheduler decides which runs may go to a worker now, and where. Nothing else in the batcher decides that.
- Interface in: events. A group arrives. A request settles, with success or failure. A retry deadline fires.
- Interface out: dispatches. One dispatch is one run of one key on one worker.
- The first implementation preserves today's semantics: pins, the stash, deferral on drain, and the flush pacing. This is code motion from `assign`, `flush_deferred`, and `on_sub_batch_resolved`.
- The plumbing (tasks, channels, the mutex) stays as it is. Only the decisions move.
- The seam makes today's implicit ordering rules explicit and reviewable in one place.

**Interfaces:**

- Add the `Scheduler` trait in `scheduler.rs`: `on_groups`, `on_settled`, `on_deadline` in; `Vec<Dispatch>` out.
- Add `Dispatch`: one run of one key, with the chosen worker.
- Add `PinStashScheduler`: the current semantics, moved out of `Dispatcher::assign`, `flush_deferred`, and `on_sub_batch_resolved`. It owns `PinTable` and `Stash` unchanged.
- Modify `Dispatcher`: shrinks to plumbing — the lock, in-flight load, metrics, and seam calls.

### 10. Build the key-table scheduler (implement)

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

### 11. Switch to the key-table scheduler (switchover)

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

### 12. Delete the old scheduler (cleanup)

**Task:** Remove the old scheduler implementation after change 11 holds on all lanes.

**Goal:** The old concurrency goes in one deletion, not in edits.

- Removes: the pin table, the stash, the completion-time flush, and the scheduler switch.
- The plan never edits this machinery. It is isolated in change 9, bypassed in change 11, and deleted here.

**Interfaces:**

- Remove `PinStashScheduler`, `PinTable`, `Stash`, and `sticky_pin_for`.
- Remove the scheduler selection from `Config`.
- Modify `Dispatcher`: remove the dead resolve plumbing (`clears_deferral`, `send_failed`, the flush driver).

## Cycle 4: the batcher is one single-owner event loop

Outcome: one task owns all batcher state. The mutex and the callback structure are gone.
This is a deliberate structural outcome, not tidy-up: it is the largest single concurrency simplification in the plan.

### 13. Collapse the batcher into one event loop (structure)

**Task:** Move the scheduler and its plumbing into one single-owner task.

**Goal:** Remove the mutex and the callback structure.

- The seam's events become the loop's events: accumulators, settlements, deadlines. The scheduler is already event-shaped, so the loop owns it directly.
- State becomes task-local. The worker-health snapshot stays the only shared read.
- This is the batcher event loop of the design doc. The decisions it drives are already simple (cycle 3), so the transformation is mechanical, but it lands as its own reviewed change.
- No config switch: the change is behavior-identical, and running two plumbing implementations side by side would cost more than it protects. Review and the e2e suite control the risk.

**Interfaces:**

- Modify `Batcher`: one single-owner task replaces the lock, the resolve callbacks, and the per-send tasks. `Dispatcher` dissolves into the loop and is removed.
- Keep `Scheduler` as the loop's decision component. The consumer-facing interface does not change.

### 14. Remove the stream fences (cleanup)

**Task:** Delete `FenceGuard` and the fence-settle loop from `grpc_transport.rs`.

**Goal:** Keep only the failure logic the new invariant needs.

- Fences go only after the batcher is single-owner. Change 12 makes requeue-before-release a scheduler invariant; change 13 makes it mechanical: one task performs settlement, requeue, and the next dispatch, so no window exists for a newer send to leapfrog a failure.
- A stream failure returns each request's messages to the key table. That is sufficient.
- This change is deferrable. With one send origin, fences are inert insurance whose only cost is code.
- Keep: retry classification, busy (503) handling, the ack watchdog, and ack-prefix resolution.

**Interfaces:**

- Remove `FenceGuard` from `transport.rs` and `Fence` with its settle loop from `grpc_transport.rs`.
- Modify `SendError`: drop the fence-guard field.
- Keep `TransportError` and the `WorkerStreamRunner` reconnect logic.

## Cycle 5: a stalled key stalls only its partition

Outcome: commits advance per partition as groups complete. Needs cycles 2 and 3.

### 15. Complete polls in any order (switchover)

**Task:** Add a completion mode, `ordered` or `any`. In `any` mode, mark the ledger per group and stop waiting for whole polls.

**Goal:** A stalled key stalls only its own partition. Other partitions continue to commit.

- Cycles 2 and 3 are the prerequisites. Commits come from the frontier, and the old flush, whose per-key order depended on oldest-first completion, is gone. Only commits depend on completion order now, and the frontier gates those.
- In `any` mode, mark each group's offsets in the ledger when its completion event arrives. Do not aggregate per poll before commits.
- The frontier gates each partition's commit.
- Keep `max_in_flight_batches` as the bound on outstanding work. A poll's slot frees when all its groups are accepted.
- Behavior change: commit timing decouples across partitions and polls. Replay exposure stays inside the admission cap.
- Rollback is the mode switch back to `ordered`.

**Interfaces:**

- Modify `Config`: add the completion mode.
- Modify `IngestionConsumer::process`: in `any` mode, select over `GroupCompletion` events. The ordered path stays for rollback.

### 16. Delete the ordered completion path (cleanup)

**Task:** Remove the ordered completion path after `any` holds on all lanes.

**Goal:** Group completions are the only completion signal.

**Interfaces:**

- Remove the ordered `InFlightBatch` queue, the per-poll aggregation from change 8, and the completion mode from `Config`.

## Cycle 6: replay exposure is bounded by B

Outcome: uncommitted work never exceeds the budget, in events and bytes. The in-flight admission cap is gone.

### 17. Add the budget accounting (implement)

**Task:** Track uncommitted work in events and bytes. Ship with no budget set: the admission cap still governs alone.

**Goal:** The budget exists and reports before it constrains.

- Charge each message on poll. The ledger slots already carry the costs (change 3).
- Refund the charge when the commit that covers the message is issued.
- Gauge the outstanding charge per partition and in total.
- New config: the budget in events and in bytes. Unset means no constraint.

**Interfaces:**

- Modify `Config`: add the budget, default unset.
- Modify `IngestionConsumer`: track charge and refund through `OffsetLedger`. No polling change while the budget is unset.

### 18. Enable the budget (switchover)

**Task:** Set the budget per lane. Pause the poll at the limit and resume on refund.

**Goal:** Replay exposure is bounded directly.

- A charts values PR sets the budget lane by lane. The admission cap and the budget both bound work during the transition.
- Derive the first values from the current config: events near the batch size times the cap, bytes from the byte bound. The effective bound then does not change at the switchover.
- Pause and resume the poll at the budget limit. Do not stop servicing Kafka callbacks.
- Watch the pause gauge and consumer lag. Rollback is unsetting the values.

**Interfaces:**

- None in this repository. Config values only.

### 19. Remove the in-flight admission cap (cleanup)

**Task:** Remove `max_in_flight_batches` after the budget holds on all lanes.

**Goal:** The budget is the only admission bound.

- Only admission control goes. The collection bounds — batch size and batch timeout — stay: they shape one poll, not the amount of admitted work.

**Interfaces:**

- Remove `max_in_flight_batches` from `Config` and the admission bookkeeping from `IngestionConsumer`.

## Cycle 7: workers receive target-sized requests

Outcome: request size tracks target T, and fan-out is demand-driven. No cleanup: body splitting stays as a defence.

### 20. Add the packer (implement)

**Task:** Add the packer to the scheduler, with target size T and `PACK_LATENCY_BUDGET`. Ship with the pack budget at zero: send-on-arrival, behavior unchanged.

**Goal:** The packing machinery exists before it changes any request.

- Check the worker side first: a packed request spans polls and keys. Confirm the worker's `concurrentBatches` accounting and the meaning of `batch_id` still hold.
- Pack runs from multiple runnable keys into one request near T. T counts events and bytes.
- Emit immediately when the ready work can fill the free permits with near-T requests. Otherwise arm the pack deadline.
- When the deadline expires, emit partial requests.
- Router order inside a pass: fill open requests on healthy workers first, then pick a worker with P2C from the aperture slice. Partition affinity is a tie-breaker only.

**Interfaces:**

- Add `Packer` inside `KeyTableScheduler`.
- Modify `Dispatch`: one request may carry runs from several keys.
- Modify `Config`: add T and `PACK_LATENCY_BUDGET`, default zero. The worker proto does not change.

### 21. Set the packing targets (switchover)

**Task:** Set T and the pack budget per lane.

**Goal:** Workers receive target-sized requests.

- A charts values PR sets the targets lane by lane.
- Watch request size, worker occupancy, and end-to-end latency. Rollback is a pack budget of zero.

**Interfaces:**

- None in this repository. Config values only.

## Cycle 8: concurrency adapts to worker health

Outcome: request RTT governs the number of requests in flight.

### 22. Add the governor (implement)

**Task:** Add the permit pool and the RTT EWMA. Ship with adaptation off: permits mirror the current per-worker cap.

**Goal:** The governor exists and observes before it constrains.

- Grow the pool by one when ready work waits, no permit is free, and RTT is within budget.
- Shrink the pool by one when the RTT EWMA exceeds `REQUEST_LATENCY_BUDGET`.
- Bound the pool with a configured minimum and maximum.
- Keep the 503 backoff in the transport. Exclude 503 waits from the RTT signal.
- Cap each stream channel at `DEPTH_MAX`.

**Interfaces:**

- Add `Governor` in the batcher loop: the permit pool and the RTT EWMA, adaptation off.
- Modify `Config`: add `REQUEST_LATENCY_BUDGET`, the permit bounds, and `DEPTH_MAX`.

### 23. Enable RTT adaptation (switchover)

**Task:** Turn adaptation on. Request RTT governs the permit pool.

**Goal:** Concurrency shrinks when the worker pool is unhealthy.

- Canary one lane. Watch permit counts, RTT, and throughput under induced worker latency.
- Rollback is the adaptation switch.

**Interfaces:**

- Modify `Config`: enable adaptation.

### 24. Remove the fixed per-worker cap (cleanup)

**Task:** Remove the per-worker `max_unacked` cap after adaptation holds on all lanes.

**Goal:** Governor permits are the only in-flight bound.

**Interfaces:**

- Modify `GrpcTransport`: remove the per-worker cap and its config. Stream channels keep `DEPTH_MAX`.

## Cycle 9: partitions hand off cleanly

Outcome: a revocation drains in bounded time, and a wedged partition fails the process instead of hanging. Needs cycle 3.

### 25. Add revoke and drained markers (prepare)

**Task:** Extend the batcher boundary with a revoke marker in and a drained marker out. Nothing consumes them yet.

**Goal:** The boundary carries the drain protocol before any drain logic exists.

**Interfaces:**

- Modify `Batcher`: add the marker types to the submit and completion channels. `GroupCompletion` does not change shape.

### 26. Build the drain (implement)

**Task:** Implement the drain sequence from section 4 of the design doc, behind a config switch that ships off.

**Goal:** The drain exists and is tested. Off means today's behavior: replay without drain.

- On revoke, send the in-band marker to the batcher, after earlier accumulators.
- The batcher drops queued unsent work for the partition. Kafka replays it for the next owner.
- Wait only for requests in flight. Send the drained marker after the final completion.
- The loop issues one final commit, refunds the remaining charge, and unassigns the partition.
- Check completions against the assignment epoch. The epoch already exists on master.
- Add a stall deadline per partition. Outside a rebalance, an expired deadline fails the process. Replay is at most B.

**Interfaces:**

- Modify `KeyTableScheduler`: drop queued work per partition on the revoke marker.
- Modify `IngestionConsumer` and `OffsetLedger`: the final commit, the refund of abandoned charge, and the stall deadline.
- Modify `Config`: add the drain switch, default off.

### 27. Enable the drain (switchover)

**Task:** Turn the drain on. Canary one lane through a rebalance.

**Goal:** Rebalances hand partitions off with a bounded drain.

- Watch rebalance duration, replay volume, and the drained markers. Rollback is the switch.

**Interfaces:**

- Modify `Config`: enable the drain.

### 28. Delete the no-drain path (cleanup)

**Task:** Remove the no-drain revoke path after the drain holds on all lanes.

**Goal:** The drain is the only revoke behavior.

**Interfaces:**

- Remove the no-drain path and the drain switch from `Config`. Keep the epoch checks.

## Later work

- The keyless lane: today an unkeyed message gets a synthetic per-message key and its own group. A separate keyless lane per partition can remove that overhead.
- Partition affinity as a packing hint (open question 6). Measure frontier coupling first.
