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

| # | Type | Change |
| --- | --- | --- |
| 1 | Structure | Add the offset ledger module |
| 2 | Structure | Demux polls into groups |
| 3 | Structure | Commit from the ledger frontier |
| 4 | Logic | Complete batches in any order |
| 5 | Logic | Route every group through the key table |
| 6 | Structure | Remove the stream fences |
| 7 | Logic | Replace the batch window with budget B |
| 8 | Structure | Split into two single-owner event loops |
| 9 | Logic | Pack requests toward target T |
| 10 | Logic | Add the RTT dispatch governor |
| 11 | Logic | Add the bounded revocation drain |

### 1. Add the offset ledger module (structure)

**Task:** Create `ledger.rs` with a per-partition offset ring. Do not wire it in.

**Goal:** Make commit contiguity a property of a data structure.

- One ledger per partition. The ledger is a dense ring of delivered offsets.
- Each slot records: complete or not, event count, byte count. The counts serve the budget in change 7.
- Operations: `charge` adds a delivered offset. `complete` marks an offset done. `frontier` removes the contiguous done prefix and returns the highest removed offset.
- Completions can arrive in any order. The frontier moves only over completed slots.
- Add property tests: out-of-order completion, monotonic frontier, ring capacity.

### 2. Demux polls into groups (structure)

**Task:** Change `collect_batch` to output groups. A group is one poll's consecutive messages for one routing key on one partition.

**Goal:** Create the accumulator shape from the design doc.

- Group messages per partition first, then per routing key. Keep offset order inside each group.
- The dispatcher flattens the groups back into one message list. Sub-batch assembly does not change.
- Later changes use the group as the unit of dispatch and completion.

### 3. Commit from the ledger frontier (structure)

**Task:** Wire the ledger into the commit path. Keep oldest-first batch completion.

**Goal:** The frontier produces the same commits as the current code, and the sentinel proves it.

- Charge every delivered offset into its partition ledger during `collect_batch`.
- When a batch completes, mark all its offsets complete.
- Commit the frontier of each partition instead of the batch's max offset.
- With oldest-first completion, the frontier equals the old commit point. The output is identical.
- The commit sentinel stays on and checks contiguity and monotonicity.

### 4. Complete batches in any order (logic)

**Task:** Replace the oldest-first await with completion events.

**Goal:** A stalled batch stalls only its own partitions. Other partitions continue to commit.

- The consumer loop awaits all in-flight batches at once (a completion channel or `FuturesUnordered`).
- A completed batch marks its offsets in the ledger. The frontier gates each partition's commit.
- A batch with deferred work no longer blocks the commits of other batches.
- Keep `max_in_flight_batches` as the bound on outstanding work.
- Behavior change: commit timing decouples across partitions. Replay exposure stays inside the batch window.

### 5. Route every group through the key table (logic)

**Task:** Enqueue all groups into per-key FIFO queues. Dispatch only runnable keys. Remove the sticky pins.

**Goal:** One ordering rule remains: at most one outstanding request per key.

- Evolve `stash.rs` into the key table. All groups enter it, not only deferred ones.
- A key is runnable when it has queued work and no outstanding request.
- Dispatch takes one contiguous run per runnable key and marks the key outstanding.
- A settlement clears the outstanding flag and dispatches the key's next run. Reuse the eager-flush channel for this path.
- A failed request returns its runs to the front of their key queues.
- Report completions per group, with partition and offsets. Mark them in the ledger. Delete the per-batch accepted counters.
- Delete: the pin table, the deferred-flush loop, and the batch-sequence machinery in the stash. Append order is sufficient, because one enqueue site remains, on the consumer loop, in poll order.
- Route each request with the existing P2C and aperture. There is no stickiness.
- This is proposal 2 of the design doc. Ship it as a canary on one lane. Measure worker key-cache locality before and after (open question 3).

### 6. Remove the stream fences (structure)

**Task:** Delete `FenceGuard` and the fence-settle loop from `grpc_transport.rs`.

**Goal:** Keep only the failure logic the new invariant needs.

- After change 5, one send origin exists. A key with a failed request is not runnable. No newer send for that key can enter a stream.
- A stream failure returns each request's messages to the key table. That is sufficient.
- Keep: retry classification, busy (503) handling, the ack watchdog, and ack-prefix resolution.

### 7. Replace the batch window with budget B (logic)

**Task:** Poll only while uncommitted work is below B. B counts events and bytes.

**Goal:** Bound replay exposure directly. Poll continuously when workers keep up.

- Charge each message on poll. The ledger slots already carry the costs (change 1).
- Refund the charge when the commit that covers the message is issued.
- Remove `max_in_flight_batches`. The batch reduces to a per-poll accumulator.
- Pause and resume the poll at the budget limit. Do not stop servicing Kafka callbacks.
- New config: the budget in events and in bytes.

### 8. Split into two single-owner event loops (structure)

**Task:** Move the key table, dispatch, and settlement into one batcher task. The consumer loop and the batcher exchange accumulators and completions over channels.

**Goal:** Remove shared mutable state and lock ordering.

- The pin-table mutex disappears. All batcher state is task-local.
- Select order in each loop: clocks and rebalance events first, completions next, polls last.
- The worker-health snapshot stays the only shared read.

### 9. Pack requests toward target T (logic)

**Task:** Add the packer, with target size T and `PACK_LATENCY_BUDGET`.

**Goal:** Request size becomes deliberate. Fan-out becomes demand-driven.

- Pack runs from multiple runnable keys into one request near T. T counts events and bytes.
- Emit immediately when the ready work can fill the free permits with near-T requests. Otherwise arm the pack deadline.
- When the deadline expires, emit partial requests.
- `PACK_LATENCY_BUDGET = 0` restores send-on-arrival. That is the off switch.
- Router order inside a pass: fill open requests on healthy workers first, then pick a worker with P2C from the aperture slice. Partition affinity is a tie-breaker only.
- Check the worker side first: a request now spans polls and keys. Confirm the worker's `concurrentBatches` accounting and the meaning of `batch_id` still hold.

### 10. Add the RTT dispatch governor (logic)

**Task:** Replace the fixed per-worker un-acked cap with a permit pool that request RTT governs.

**Goal:** Reduce crash exposure when the worker pool is unhealthy.

- Grow the pool by one when ready work waits, no permit is free, and RTT is within budget.
- Shrink the pool by one when the RTT EWMA exceeds `REQUEST_LATENCY_BUDGET`.
- Bound the pool with a configured minimum and maximum.
- Keep the 503 backoff in the transport. Exclude 503 waits from the RTT signal.
- Cap each stream channel at `DEPTH_MAX`.

### 11. Add the bounded revocation drain (logic)

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
