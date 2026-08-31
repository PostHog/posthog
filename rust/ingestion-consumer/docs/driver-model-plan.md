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
- A logic change ships behind a config switch when a switch is possible. When a switch is not possible, it ships as a canary on one lane.
- Old code is deleted, not edited. When a cutover holds on all lanes, one structure change removes the old implementation whole.
- The commit sentinel and the key-order sentinel stay enabled through the migration. They verify each step in production.

## Changes

Part 1 prepares the structure (changes 1 to 5).
Behavior does not change.
The offset ledger and the key-table batcher are both built here, tested, and left unselected.

Part 2 cuts over and simplifies (changes 6 to 14).
Each cutover is a switch flip made small by part 1, with the switch as the rollback.
Each deletion follows its cutover.

| # | Type | Change |
| --- | --- | --- |
| 1 | Structure | Add the offset ledger module |
| 2 | Structure | Run the ledger in shadow mode |
| 3 | Structure | Demux polls into groups |
| 4 | Structure | Encapsulate the worker batcher |
| 5 | Structure | Build the key-table batcher |
| 6 | Structure | Commit from the ledger frontier |
| 7 | Logic | Switch to the key-table batcher |
| 8 | Structure | Delete the old batcher implementation |
| 9 | Structure | Remove the stream fences |
| 10 | Logic | Complete batches in any order |
| 11 | Logic | Replace the batch window with budget B |
| 12 | Logic | Pack requests toward target T |
| 13 | Logic | Add the RTT dispatch governor |
| 14 | Logic | Add the bounded revocation drain |

### 1. Add the offset ledger module (structure)

**Task:** Create `ledger.rs` with a per-partition offset ring. Do not wire it in.

**Goal:** Make commit contiguity a property of a data structure.

- One ledger per partition. The ledger is a dense ring of delivered offsets.
- Each slot records: complete or not, event count, byte count. The counts serve the budget in change 11.
- Operations: `charge` adds a delivered offset. `complete` marks an offset done. `frontier` removes the contiguous done prefix and returns the highest removed offset.
- Completions can arrive in any order. The frontier moves only over completed slots.
- Kafka delivers offsets with gaps (transactions, compaction). Contiguity means the prefix of delivered offsets, not offset arithmetic.
- Add property tests: out-of-order completion, monotonic frontier, offset gaps, ring capacity.

### 2. Run the ledger in shadow mode (structure)

**Task:** Wire the ledger next to the commit path. Compare its frontier with each real commit. Do not change what the consumer commits.

**Goal:** Prove the ledger against production traffic before it owns the commits.

- New config: the ledger mode, `off`, `shadow`, or `active`. This change ships `shadow`. Change 6 ships `active`.
- Charge every delivered offset into its partition ledger during `collect_batch`.
- When a batch completes, mark all its offsets complete.
- At each commit, compare the partition's frontier with the offset the current path commits. With oldest-first completion, the two must be equal.
- On a mismatch: increment a counter and log the partition with both offsets. Do not block the commit.
- On revoke, drop the partition's ledger. This mirrors the commit sentinel's `forget_partitions`.
- Soak on all lanes. The exit criterion is a mismatch count of zero across deploys and rebalances.

### 3. Demux polls into groups (structure)

**Task:** Change `collect_batch` to output groups. A group is one poll's consecutive messages for one routing key on one partition.

**Goal:** Create the accumulator shape from the design doc.

- Group messages per partition first, then per routing key. Keep offset order inside each group.
- The dispatcher flattens the groups back into one message list. Sub-batch assembly does not change.
- Change 4 uses the groups as the unit of the batcher interface.

### 4. Encapsulate the worker batcher (structure)

**Task:** Put today's dispatch machinery behind one boundary. The consumer loop and the batcher exchange plain values.

**Goal:** The dispatch concurrency becomes an implementation detail behind one interface.

- Interface in: one poll's groups, submitted on the consumer loop in poll order.
- Interface out: one completion event per batch, with the accepted count. Group-level events come later, when the budget needs them.
- Move inside the boundary: assignment, scatter, the deferred flush, the eager flush, the worker registry, the router, and the stream runners.
- The facade replicates today's behavior exactly, including the oldest-first flush pacing. This is code motion, not redesign.
- The consumer loop keeps: poll collection, commits, the sentinels, and the batch window.
- The boundary is the seam for change 5: two implementations can stand behind it.

### 5. Build the key-table batcher (structure)

**Task:** Write the target batcher as a second implementation behind the change-4 boundary. Do not select it.

**Goal:** The replacement exists, fully tested, before any behavior changes.

- One single-owner event loop task. State is task-local. There is no shared mutex. Events: accumulators, request settlements, deadlines. This is the batcher of the design doc.
- The key table: one FIFO queue per key. A key is runnable when it has queued work and no outstanding request. Dispatch takes one contiguous run and marks the key outstanding.
- A settlement clears the outstanding flag and dispatches the key's next run. A failed request returns its runs to the front of their key queues.
- A parked-retry deadline covers the keys no settlement can release: unroutable groups, and keys behind a failed send.
- Route each request with the existing P2C and aperture. There is no pin table and no stickiness.
- The boundary is values in, values out. Test the batcher deterministically without Kafka: submit groups, script settlements and failures, assert per-key order and completions.

### 6. Commit from the ledger frontier (structure)

**Task:** Set the ledger mode to `active`. The frontier becomes the committed offset. Keep oldest-first batch completion.

**Goal:** The frontier produces the same commits as the old code, and change 2 already proved that.

- Commit each partition's frontier instead of the batch's max offset.
- With oldest-first completion, the output is identical to the old path.
- The commit sentinel stays on and checks contiguity and monotonicity.
- Rollback is the config switch back to `shadow`.
- Delete the old commit computation after `active` holds on all lanes.

### 7. Switch to the key-table batcher (logic)

**Task:** Select the key-table batcher with config. Canary one lane, then roll out.

**Goal:** One ordering rule replaces pins, the stash, and the flush paths.

- At most one outstanding request per key preserves per-key order. Nothing else does, and nothing else must.
- This is proposal 2 of the design doc: sticky pins are removed. Measure worker key-cache locality before and after (open question 3).
- Watch: the key-order sentinel, ack latency, and the no-progress watchdog.
- Rollback is the config switch back to the old implementation.

### 8. Delete the old batcher implementation (structure)

**Task:** Remove the old implementation after change 7 holds on all lanes.

**Goal:** The old concurrency goes in one deletion, not in edits.

- Removes: the pin table, the stash, the eager-flush channel and its credits, the completion-time flush, `DISPATCHER_EAGER_DEFERRED_FLUSH`, and the implementation switch.
- The plan never edits this machinery. It is encapsulated in change 4, bypassed in change 7, and deleted here.

### 9. Remove the stream fences (structure)

**Task:** Delete `FenceGuard` and the fence-settle loop from `grpc_transport.rs`.

**Goal:** Keep only the failure logic the new invariant needs.

- After change 8, one send origin exists. A key with a failed request is not runnable. No newer send for that key can enter a stream.
- A stream failure returns each request's messages to the key table. That is sufficient.
- Keep: retry classification, busy (503) handling, the ack watchdog, and ack-prefix resolution.

### 10. Complete batches in any order (logic)

**Task:** Replace the oldest-first await with completion events.

**Goal:** A stalled batch stalls only its own partitions. Other partitions continue to commit.

- Changes 6 and 8 are the prerequisites. Commits come from the frontier, and the old flush, whose per-key order depended on oldest-first completion, is gone. Only commits depend on completion order now, and the frontier gates those.
- The consumer loop awaits all in-flight batches at once (a completion channel or `FuturesUnordered`).
- A completed batch marks its offsets in the ledger. The frontier gates each partition's commit.
- Keep `max_in_flight_batches` as the bound on outstanding work.
- Behavior change: commit timing decouples across partitions. Replay exposure stays inside the batch window.

### 11. Replace the batch window with budget B (logic)

**Task:** Poll only while uncommitted work is below B. B counts events and bytes.

**Goal:** Bound replay exposure directly. Poll continuously when workers keep up.

- Charge each message on poll. The ledger slots already carry the costs (change 1).
- Refund the charge when the commit that covers the message is issued.
- Upgrade the batcher interface to group-level completion events, so the ledger marks groups as they settle.
- Remove `max_in_flight_batches`. The batch reduces to a per-poll accumulator.
- Pause and resume the poll at the budget limit. Do not stop servicing Kafka callbacks.
- New config: the budget in events and in bytes.

### 12. Pack requests toward target T (logic)

**Task:** Add the packer to the key-table batcher, with target size T and `PACK_LATENCY_BUDGET`.

**Goal:** Request size becomes deliberate. Fan-out becomes demand-driven.

- Pack runs from multiple runnable keys into one request near T. T counts events and bytes.
- Emit immediately when the ready work can fill the free permits with near-T requests. Otherwise arm the pack deadline.
- When the deadline expires, emit partial requests.
- `PACK_LATENCY_BUDGET = 0` restores send-on-arrival. That is the off switch.
- Router order inside a pass: fill open requests on healthy workers first, then pick a worker with P2C from the aperture slice. Partition affinity is a tie-breaker only.
- Check the worker side first: a request now spans polls and keys. Confirm the worker's `concurrentBatches` accounting and the meaning of `batch_id` still hold.

### 13. Add the RTT dispatch governor (logic)

**Task:** Replace the fixed per-worker un-acked cap with a permit pool that request RTT governs.

**Goal:** Reduce crash exposure when the worker pool is unhealthy.

- Grow the pool by one when ready work waits, no permit is free, and RTT is within budget.
- Shrink the pool by one when the RTT EWMA exceeds `REQUEST_LATENCY_BUDGET`.
- Bound the pool with a configured minimum and maximum.
- Keep the 503 backoff in the transport. Exclude 503 waits from the RTT signal.
- Cap each stream channel at `DEPTH_MAX`.

### 14. Add the bounded revocation drain (logic)

**Task:** Implement the drain sequence from section 4 of the design doc.

**Goal:** A revoked partition hands off cleanly. A wedged partition fails the process instead of hanging forever.

- On revoke, send an in-band marker to the batcher, after earlier accumulators.
- The batcher drops queued unsent work for the partition. Kafka replays it for the next owner.
- Wait only for requests in flight. Send a drained marker after the final completion.
- The loop issues one final commit, refunds the remaining charge, and unassigns the partition.
- Check completions against the assignment epoch. The epoch already exists on master.
- Add a stall deadline per partition. Outside a rebalance, an expired deadline fails the process. Replay is at most B.

## Later work

- The keyless lane: today an unkeyed message gets a synthetic per-message key and its own group. A separate keyless lane per partition can remove that overhead.
- Partition affinity as a packing hint (open question 6). Measure frontier coupling first.
