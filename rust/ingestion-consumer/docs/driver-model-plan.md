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
- A logic change ships behind a config flag when a flag is possible. When a flag is not possible, it ships as a canary on one lane.
- The commit sentinel and the key-order sentinel stay enabled through the migration. They verify each step in production.

## Changes

The ledger track comes first (changes 1 to 3).
It is isolated from the dispatch path, and shadow mode tests it against the current implementation in production before the cutover.

The concurrency track follows (changes 4 to 6).
Settlement events become the only drain for deferred work, batch completion stops flushing, and then batches complete in any order.
The order matters: the completion-time flush keeps per-key order only because batches complete oldest first, so it must go before completion order can change.

| # | Type | Change |
| --- | --- | --- |
| 1 | Structure | Add the offset ledger module |
| 2 | Structure | Run the ledger in shadow mode |
| 3 | Structure | Commit from the ledger frontier |
| 4 | Logic | Drain deferred work on settlement events |
| 5 | Logic | Batch completion stops flushing |
| 6 | Logic | Complete batches in any order |
| 7 | Structure | Demux polls into groups |
| 8 | Logic | Route every group through the key table |
| 9 | Structure | Remove the stream fences |
| 10 | Logic | Replace the batch window with budget B |
| 11 | Structure | Split into two single-owner event loops |
| 12 | Logic | Pack requests toward target T |
| 13 | Logic | Add the RTT dispatch governor |
| 14 | Logic | Add the bounded revocation drain |

### 1. Add the offset ledger module (structure)

**Task:** Create `ledger.rs` with a per-partition offset ring. Do not wire it in.

**Goal:** Make commit contiguity a property of a data structure.

- One ledger per partition. The ledger is a dense ring of delivered offsets.
- Each slot records: complete or not, event count, byte count. The counts serve the budget in change 10.
- Operations: `charge` adds a delivered offset. `complete` marks an offset done. `frontier` removes the contiguous done prefix and returns the highest removed offset.
- Completions can arrive in any order. The frontier moves only over completed slots.
- Kafka delivers offsets with gaps (transactions, compaction). Contiguity means the prefix of delivered offsets, not offset arithmetic.
- Add property tests: out-of-order completion, monotonic frontier, offset gaps, ring capacity.

### 2. Run the ledger in shadow mode (structure)

**Task:** Wire the ledger next to the commit path. Compare its frontier with each real commit. Do not change what the consumer commits.

**Goal:** Prove the ledger against production traffic before it owns the commits.

- New config: the ledger mode, `off`, `shadow`, or `active`. This change ships `shadow`. Change 3 ships `active`.
- Charge every delivered offset into its partition ledger during `collect_batch`.
- When a batch completes, mark all its offsets complete.
- At each commit, compare the partition's frontier with the offset the current path commits. With oldest-first completion, the two must be equal.
- On a mismatch: increment a counter and log the partition with both offsets. Do not block the commit.
- On revoke, drop the partition's ledger. This mirrors the commit sentinel's `forget_partitions`.
- Soak on all lanes. The exit criterion is a mismatch count of zero across deploys and rebalances.

### 3. Commit from the ledger frontier (structure)

**Task:** Set the ledger mode to `active`. The frontier becomes the committed offset. Keep oldest-first batch completion.

**Goal:** The frontier produces the same commits as the old code, and change 2 already proved that.

- Commit each partition's frontier instead of the batch's max offset.
- With oldest-first completion, the output is identical to the old path.
- The commit sentinel stays on and checks contiguity and monotonicity.
- Rollback is the config switch back to `shadow`.
- Delete the old commit computation after `active` holds on all lanes.

### 4. Drain deferred work on settlement events (logic)

**Task:** Make the settlement release reach every deferred group. The completion-time flush stays as the backstop.

**Goal:** Deferred work drains at ack speed, on one primary path.

- The settlement release exists behind `DISPATCHER_EAGER_DEFERRED_FLUSH`, default off and not set in production. A charts PR enables it first. Rollback is that values change.
- Two cases never see a settlement today: a group that was unroutable (its key had no send in flight), and a key whose failed send suppressed the release.
- Add a parked-retry deadline for them: a timer retries every deferring key that has no send in flight, with backoff.
- Count drains per path. After this change, the completion-time flush must find an empty stash in normal operation.

### 5. Batch completion stops flushing (logic)

**Task:** Add a flush mode, `batch` or `settlement`. In `settlement` mode, batch completion waits for its accepted count and does not flush.

**Goal:** Batch completion only waits and counts. One flush path remains.

- In `settlement` mode, a batch completes when its accepted count reaches its batch size. The credit path for settled sends exists (`take_eager_accepted`).
- Per-key order holds without the oldest-first rule: each key queue orders its entries by batch sequence, and the release always takes the oldest entry.
- Keep the no-progress watchdog: fail the process when a batch sees no acceptance for a full timeout window.
- Rollback is the mode switch back to `batch`.
- Delete `batch` mode after `settlement` holds on all lanes. That removes `flush_deferred` in the consumer and the dispatcher, and `Stash::take_batch`.

### 6. Complete batches in any order (logic)

**Task:** Replace the oldest-first await with completion events.

**Goal:** A stalled batch stalls only its own partitions. Other partitions continue to commit.

- Change 5 is the prerequisite. The completion-time flush kept per-key order only because batches completed oldest first: `Stash::take_batch` on a newer batch pulls a key's entries past an older batch's entries. The settlement release orders by key queue instead.
- The consumer loop awaits all in-flight batches at once (a completion channel or `FuturesUnordered`).
- A completed batch marks its offsets in the ledger. The frontier gates each partition's commit.
- A batch with deferred work no longer blocks the commits of other batches.
- Keep `max_in_flight_batches` as the bound on outstanding work.
- Behavior change: commit timing decouples across partitions. Replay exposure stays inside the batch window.

### 7. Demux polls into groups (structure)

**Task:** Change `collect_batch` to output groups. A group is one poll's consecutive messages for one routing key on one partition.

**Goal:** Create the accumulator shape from the design doc.

- Group messages per partition first, then per routing key. Keep offset order inside each group.
- The dispatcher flattens the groups back into one message list. Sub-batch assembly does not change.
- Later changes use the group as the unit of dispatch and completion.

### 8. Route every group through the key table (logic)

**Task:** Enqueue all groups into per-key FIFO queues. Dispatch only runnable keys. Remove the sticky pins.

**Goal:** One ordering rule remains: at most one outstanding request per key.

- Evolve `stash.rs` into the key table. All groups enter it, not only deferred ones.
- A key is runnable when it has queued work and no outstanding request.
- Dispatch takes one contiguous run per runnable key and marks the key outstanding.
- A settlement clears the outstanding flag and dispatches the key's next run. Change 4 made this the primary drain. This change extends it to all groups.
- A failed request returns its runs to the front of their key queues.
- Report completions per group, with partition and offsets. Mark them in the ledger. Delete the per-batch accepted counters.
- Delete: the pin table and the batch-sequence machinery in the stash. Append order is sufficient, because one enqueue site remains, on the consumer loop, in poll order.
- Route each request with the existing P2C and aperture. There is no stickiness.
- This is proposal 2 of the design doc. Ship it as a canary on one lane. Measure worker key-cache locality before and after (open question 3).

### 9. Remove the stream fences (structure)

**Task:** Delete `FenceGuard` and the fence-settle loop from `grpc_transport.rs`.

**Goal:** Keep only the failure logic the new invariant needs.

- After change 8, one send origin exists. A key with a failed request is not runnable. No newer send for that key can enter a stream.
- A stream failure returns each request's messages to the key table. That is sufficient.
- Keep: retry classification, busy (503) handling, the ack watchdog, and ack-prefix resolution.

### 10. Replace the batch window with budget B (logic)

**Task:** Poll only while uncommitted work is below B. B counts events and bytes.

**Goal:** Bound replay exposure directly. Poll continuously when workers keep up.

- Charge each message on poll. The ledger slots already carry the costs (change 1).
- Refund the charge when the commit that covers the message is issued.
- Remove `max_in_flight_batches`. The batch reduces to a per-poll accumulator.
- Pause and resume the poll at the budget limit. Do not stop servicing Kafka callbacks.
- New config: the budget in events and in bytes.

### 11. Split into two single-owner event loops (structure)

**Task:** Move the key table, dispatch, and settlement into one batcher task. The consumer loop and the batcher exchange accumulators and completions over channels.

**Goal:** Remove shared mutable state and lock ordering.

- The pin-table mutex disappears. All batcher state is task-local.
- Select order in each loop: clocks and rebalance events first, completions next, polls last.
- The worker-health snapshot stays the only shared read.

### 12. Pack requests toward target T (logic)

**Task:** Add the packer, with target size T and `PACK_LATENCY_BUDGET`.

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
