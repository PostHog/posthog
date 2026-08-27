# Driver-model redesign

Status: **draft, for discussion** — nothing here is implemented.

This doc proposes a restructuring of the ingestion consumer around components shaped like its invariants (partitions and routing keys) instead of around the Kafka batch. It is written against the code as of the gRPC worker-stream work (#85238, since merged); the mechanisms it discusses are those in `consumer.rs`, `dispatcher.rs`, `stash.rs`, `transport.rs`, and `grpc_transport.rs`. Terms are used as defined in §8 (Nomenclature); §2 keeps the names the code has today. It is a companion to the elastic-dispatch plan (target-sized worker batches, demand-proportional concurrency, one-signal worker autoscaling): the redesign is the shape in which those goals stop needing a controller at all.

The argument, in one paragraph: the consumer enforces two invariants — per-key send order and per-partition contiguous commits — but its unit of everything (ownership, completion, commit, flush pacing, concurrency) is the Kafka batch, which appears in neither invariant. Bridging that mismatch is what the stash, the deferral rules, the eager-flush accounting, the worker-stream fences, and the oldest-first completion serialization are for. Re-founding the consumer on partition- and key-shaped components makes most of that machinery either disappear or shrink to a local rule, and yields the elastic-dispatch scaling behavior as a side effect of the structure rather than as a feedback loop bolted on top.

## 1. The two invariants

Everything the consumer does serves two guarantees, plus one delivery contract:

1. **Per-key send order.** For every routing key (`token:distinct_id`), messages reach workers — and are ACKed — in Kafka offset order. A key's newer messages must never overtake its older ones, across any failure, re-route, or retry.
2. **Per-partition commit contiguity.** Offsets are committed contiguously and monotonically per partition: an offset is committed only when every offset below it has been accepted by a worker.
3. **At-least-once.** Nothing is committed until accepted; on a crash, uncommitted offsets replay. Duplication is legal, loss is not.

Every construct inventoried below exists to uphold these three under some adverse condition (worker death, drains, 503s, oversized payloads, hot keys, rebalances). The question the redesign asks about each one is: *is this mechanism essential to the invariant, or is it the cost of enforcing a partition/key-shaped invariant through batch-shaped machinery?*

## 2. Inventory: what exists today and why

An index, then a subsection per construct. Each subsection states the problem, the mechanism, and the coupling cost — the part that makes the whole hard to reason about.

| # | Construct | Problem it solves |
|---|-----------|-------------------|
| 2.1 | Batch collection + in-flight window | throughput vs bounded uncommitted work |
| 2.2 | Oldest-first completion + commit | commit contiguity |
| 2.3 | Commit sentinel + commit monitor | verifying commits actually land |
| 2.4 | Sticky pins (pin table) | per-key order across concurrent batches |
| 2.5 | Stash / deferral | order across worker drain, death, unroutability |
| 2.6 | Completion-time flush | draining the stash; commit gate; stall watchdog |
| 2.7 | Eager deferred flush | breaking the hot-key deferral cascade |
| 2.8 | gRPC worker streams, ledger, fences | feed order on the wire; failure atomicity |
| 2.9 | Transport retry / 503 handling | transient faults vs deliberate backpressure |
| 2.10 | Body splitting + 413 handling | worker body limits without reordering |
| 2.11 | Worker registry | health, drains, dead workers, discovery |
| 2.12 | Routing strategies + aperture | worker spread, herd resistance, consolidation |
| 2.13 | Key-order sentinel | verifying what the design can't make impossible |

### 2.1 Batch collection and the in-flight window

The loop collects up to `CONSUMER_BATCH_SIZE` messages (or `CONSUMER_BATCH_SIZE_KB`, or `CONSUMER_BATCH_TIMEOUT_MS`) into a batch, and runs at most `CONSUMER_MAX_BACKGROUND_TASKS` batches concurrently — the **in-flight window** (the field is `max_in_flight_batches`; one *slot* below means one in-flight batch). The in-flight window bounds uncommitted work — the crash-replay exposure — and is the *only* source of dispatch concurrency.

**Cost:** concurrency is a fixed constant. Per-pod throughput is capped at `slots × batch / round-trip` regardless of backlog depth, and the consumer spends its wall time awaiting ACKs at low CPU — which blinds a CPU-based HPA and starves the worker pool's in-flight-based HPA at the same time: a deep backlog can sit for hours with both autoscalers reading "idle", until an operator raises `minPods` by hand. The batch is also the unit of *ownership*: every downstream mechanism (stash entries, flush loops, eager accounting) is keyed by which batch a message arrived in, a fact neither invariant cares about.

### 2.2 Oldest-first completion and commit

Batches complete strictly oldest-first (`complete_oldest_batch`): await the batch's sends, flush its deferred groups, verify every message accepted, then commit its offsets. Serializing completion is how commit contiguity is enforced — batch N+1's offsets never commit before batch N's.

**Cost:** head-of-line blocking across *everything*. One wedged key in one partition holds the commits of all partitions, all batches behind it, and — once the window fills — stops collection entirely. Contiguity is a per-partition property, but it is enforced with a global serialization.

### 2.3 Commit sentinel and commit monitor

`CommitSentinel` checks each commit for gaps, out-of-order, and overlaps per partition; a background monitor polls the broker's committed offsets because librdkafka drops the result of manual async commits. Pure observers.

**Cost:** none — but note *why* the sentinel earns its keep: contiguity today is an emergent property of the completion serialization plus the all-accepted check, not something any component computes. The sentinel verifies what nothing constructs.

### 2.4 Sticky pins

While a key has sends in flight, it is pinned to one worker with a ref-count (`PinTable`). Pins keep a key's concurrent batches on one worker (order), are evicted at ref-count zero when nothing is deferred, and are abandoned at flush time when the pinned worker is drastically overloaded (`STICKY_PIN_LOAD_FACTOR`/`SLACK`).

**Cost:** the pin table is correct only in concert with the stash: eviction must check `is_deferring`, resolution must skip stale pins after re-points, and the ref-count discipline spans `assign`, both flush paths, and the eager path. The rules are right, but they are distributed.

### 2.5 The stash (deferral)

When a key can't be sent — pinned to a draining/dead worker, or the whole pool unroutable — its group is *stashed* rather than re-routed, because its earlier messages are still in flight and re-routing would reorder the key. Critically, once a key defers once, **every newer group for it must also defer** (the cascade rule), or it would race ahead of the stashed ones. The stash orders a key's entries by batch *sequence* (registered on the consumer loop, because deferrals can arrive out of batch order), keeps per-batch live counts (so batches can complete), and per-key outstanding counts (which stay elevated from `defer` until the flushed group actually *lands*, closing the race window where a flushed-but-unACKed group could be overtaken — this is why `is_deferring` answers *does this key have unlanded work*, not *is anything physically stashed*).

**Cost:** the stash is a second queue system living beside the primary send path, with its own ordering key (batch sequence), its own occupancy accounting, and subtle state ("outstanding" ≠ "physically stashed"). All of it is per-key queueing — expressed batch-scoped.

### 2.6 Completion-time flush

`flush_deferred` runs inline in `complete_oldest_batch`: re-route and send the completing batch's stashed groups, serialized oldest-batch-first (which is what preserves a key's cross-batch order), pacing retries at 200 ms when nothing is routable, and failing the process — replay from uncommitted offsets — when no progress happens for `CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS`. It is simultaneously the stash's drain path, the batch's commit gate, and the stall watchdog.

**Cost:** the drain is paced by batch completion and runs *on the consumer loop*. A continuously-sending hot key drains one group per completion while every collection adds one — it never exits deferral — and every batch's completion carries the flush round-trips inline, taxing all traffic.

### 2.7 Eager deferred flush

`DISPATCHER_EAGER_DEFERRED_FLUSH` (default off) attacks 2.6's pacing problem: the moment the send blocking a key resolves (pin ref-count zero, stash non-empty, send succeeded), the dispatcher pops the key's *oldest* stashed group, re-routes it, and hands it to the eager-flush task to send. Each ACK releases the next group — the chain drains at ACK round-trip speed instead of completion speed, which is what lets a hot key actually catch up and exit deferral.

**Cost:** a second drain path over the same stash, reconciled with the first through dedicated glue: `eager_pending` (batches can't commit with eager sends in flight), `eager_accepted` / `take_eager_accepted` (acceptances credited across paths), stall-deadline resets on eager progress, and `send_failed` suppression so a flapping worker doesn't tight-loop between the paths. Every subtle interaction in the dispatcher today lives at this seam. The eager path is the *correct* drain model — the completion path is what forces it to be an add-on rather than the design.

### 2.8 gRPC worker streams, the ledger, and fences (#85238)

One ordered stream per worker: enqueue order is send order is the worker's feed order — the per-key guarantee concurrent HTTP requests can't give, which is why `begin_send` must be called synchronously where send order is decided (the consumer loop, the serialized flush paths, the eager loop's receive-order). The stream's ledger resolves ACKs only as a consecutive prefix (a later send must not release its keys while an earlier one can still fail), and a failure **fences the whole worker stream**: every queued and un-ACKed item is resolved in order with its messages handed back, and each carries a `FenceGuard` — the stream refuses new work until every guard is dropped, closing the race where the consumer loop could enqueue a fenced key's next group before the failure finished re-stashing.

**Cost:** the fence machinery exists because send *origination is distributed*: scatter tasks, two flush paths, and the eager-flush task all enqueue concurrently, so the stream cannot know when a failure's cleanup is complete except by explicit guard hand-off. The ledger's resolve-in-send-order rule exists because many sends ride the stream concurrently on behalf of batch-scoped callers.

### 2.9 Transport retry and 503 handling

The transport distinguishes deliberate backpressure from faults: HTTP 503 (`WorkerBusy`) and stream-busy get a longer, jittered backoff (250 ms·2ⁿ capped at 5 s + jitter, vs 100 ms·2ⁿ for errors) and are **excluded from passive health** (`is_backpressure`), so a worker at capacity is throttled but not marked sick. 4xx is non-retriable; retries mark `replay` so worker-side sentinels count repeats correctly; per-worker semaphores softly cap in-flight requests to match the worker's `concurrentBatches`.

**Cost:** essentially none — this layer is well-factored and survives the redesign intact.

### 2.10 Body splitting and 413

Sub-batches have no construction-time size bound, so the transport compensates: estimated-oversize bodies split into sequential order-preserving chunks under one permit, a 413 halves and resends, a single un-splittable message fails cleanly, and failures reassemble the *entire* original message set for deferral (all-or-nothing contract).

**Cost:** request size is an emergent accident of `batch ÷ fan-out` — nobody chose it. The splitting is a downstream repair for an upstream non-decision.

### 2.11 Worker registry

Passive send outcomes (rolling window) combined with active `/_ready` probes drive Healthy/Degraded/Unhealthy with anti-flap dwell times. Draining workers (left the pool, e.g. a deploy) take no new work, have probe failures ignored but send failures still escalate, and are reaped when their in-flight hits zero or a deadline passes. Discovery is static or EndpointSlice-driven.

**Cost:** none structurally — but note that the *consequence* of a drain (the key must wait for in-flight, then re-route in order) is implemented far away, in the stash and its two flush paths.

### 2.12 Routing strategies and the aperture

Unpinned keys route by BinPack (exclusive pools), P2C (shared pools, herd resistant), or deterministic Aperture: each consumer routes fresh keys only within its slice of the worker ring, slices tiling the pool without coordination, floored at `ceil(pool/consumers)` for coverage.

**Cost:** the aperture floor makes fan-out *topology-shaped, not load-shaped*: a batch shatters across the slice width whether it holds 40 events or 5,000. Few consumers over a large pool ⇒ many tiny requests, maximum per-request fixed cost exactly when efficiency matters most (a 5,000-event batch spread over a 32-wide slice floor comes out as ~150-event requests).

### 2.13 Key-order sentinel

`KeyOrderSentinel` verifies per-key send order at assignment time and ACK regressions, distinguishing legal at-least-once replays from violations, re-baselining on rebalances.

**Cost:** none — but like 2.3, it verifies a property that emerges from discipline (synchronous `begin_send` placement, register-before-assign, credit-before-resolve orderings) rather than from structure. The codebase enforces its invariants by the *care with which calls are placed*; the sentinels are the tax on that.

## 3. Diagnosis

Four structural findings fall out of the inventory:

1. **The batch is the unit of everything, and no invariant is batch-shaped.** Ownership, completion, commit, stash scoping, flush pacing, and concurrency are all batch-scoped; the invariants are key- and partition-scoped. Every construct in §2.4–2.8 is bridge machinery between those two shapes.
2. **Two drain paths over one stash, plus reconciliation glue.** The eager path (2.7) is the right model; the completion path (2.6) is the incumbent it must coexist with. The cross-path accounting, credits, and suppression rules exist only because there are two.
3. **Ordering by discipline, not by structure.** Per-key order holds because `begin_send` is called in the right places in the right order across four call sites on three tasks. The worker-stream fences (2.8) are the cost of distributed origination; the sentinels (2.3, 2.13) are the audit of it.
4. **Concurrency and request size are constants and accidents.** The slot count can't respond to backlog (the autoscaling blindness), and request size is whatever division produces (the fan-out inversion).

## 4. The driver model

### 4.1 Components

```text
consumer driver                   (1 per pod)
  ├── partition manager           (1 per pod; assignments + work distribution)
  │     └── partition driver      (1 per assigned partition)
  │           └── key driver      (1 per active routing key, passive)
  ├── sender                      (1 per event loop; the transport's intake)
  │     ├── router/aperture       (placement — §4.3)
  │     ├── packer + size defense (request composition; §2.10 kept below it)
  │     └── stream runners        (1 task per worker; depth-1 ordered send)
  ├── result stream               (1 per event loop; the transport's outlet)
  ├── commit manager              (1 per pod; frontiers → one batched commit)
  └── budget · timer service      (the B poll gate; one deadline heap)

shared services: worker registry + discovery · transport classifier ·
                 sentinels (asserts) · debug recorder
```

The hierarchy follows containment in the *data*: a partition contains per-key message sequences; a key's sequence is consumed in **groups** (one poll's messages for one key — the code's `MessageGroup`). The Kafka batch is demoted to an input format: it exists during collection and **dissolves at demux**. Nothing downstream tracks it. A *driver* here means exactly one thing: the single owner of one unit's state, advanced only by events.

Below the consumer driver the tree has exactly two sides: the **domain side** (partition manager down to key drivers) and the **transport side** (the sender and the result stream, with everything under them). Each direction across the seam has its own value-carrying face: the domain pushes **releases** into the sender — a one-method sink, the domain's entire view of the transport — and the transport hands **request results** up through the result stream, drained by the loop (§4.7). Neither side holds a reference into the other's state.

- **Consumer driver** — polls rdkafka, applies backpressure (§4.4), drains the result stream, and feeds both event kinds down to the partition manager — which pushes the releases they produce straight into the sender. What remains for the loop itself is sequencing: the trigger nudges (`flush_touched`, `refire`, §4.3) after the domain has run. Owns nothing partition- or worker-shaped itself.
- **Partition manager** — the domain side's root. Owns the partition drivers and their lifecycle: partition assigned ⇒ create a driver; revoked ⇒ tear it down wholesale, with its key drivers and pending state (the rebalance unit and the component unit coincide). Distributes work: demuxes each poll to its partition drivers, routes each request result's groups back to the partition driver that owns them, discards results whose assignment epoch is dead, and pushes every release its drivers hand up into the sender's sink. Everything it passes down and collects up is a value; the sink is the only thing it writes into.
- **Partition driver** — splits its messages by routing key into groups and hands them to key drivers; owns the **offset ledger**: the set of pending offsets and the highest contiguous completed offset (the **frontier**), which is what gets committed, on a cadence. Contiguity becomes *constructive* — the ledger computes exactly the committable frontier — instead of a property to verify after the fact.
- **Key driver** — a passive state machine (a struct in a map, not a task; key cardinality is unbounded): a FIFO of groups, **at most one group released at a time** (buffered in a worker stream's bin or in flight), the rest queued behind it. On ACK: report offsets to the partition ledger, remember which worker served it (the sticky pin), release the next group. On failure: take the group back, arm a backoff timer, release again on expiry. It names a *preference*, never a worker — placement is the sender's. Created on first group, evicted when idle and empty.
- **Sender** — the transport's intake, and the domain's entire view of it: `push(release)` places the group (router + pins-as-preferences, §4.3), bins it per worker, and fires target-sized requests down the ordered streams. The sink is total — a release no worker can take is not handed back to the caller but posted to the result stream as an `Unroutable` result (§4.5). It never calls a driver. The packer and the §2.10 size defense sit below it, as do the stream runners: one task per worker — connect, greet with the assignment epoch, transmit, await ACKs, depth 1 — and the transport classifier, §2.9 unchanged (backpressure vs fault vs non-retriable, backpressure excluded from passive health).
- **Result stream** — the transport's outlet: one **request result** at a time — every group a resolved request carried, with its outcome — and nothing else escapes. Runners post their resolutions into it, the sender posts its `Unroutable` releases, and the loop drains it and feeds the partition manager.
- **Commit manager** — on the commit cadence, reads each partition driver's frontier, issues one batched manual commit, and refunds the budget for the retired work. The §2.3 verification rides here unchanged: the commit sentinel as a cheap assert, the commit monitor because librdkafka still drops async commit results.
- **Budget and timer service** — the `B` accounting (charged at poll, refunded at commit and at revoke teardown), and one deadline heap for key backoffs and linger timers. Key cardinality is unbounded, so a timer is an entry in the heap the loop polls — never a per-key task.

### 4.2 One event loop, synchronous cascades

All state transitions run on a single event loop (sharding noted in §4.6) driven by three event sources:

1. **Poll delivered** — the partition manager demuxes to partition drivers → key drivers enqueue and hand back released groups → the partition manager pushes them into the sender, which places and bins them → the loop fires every *idle* stream touched this cycle.
2. **Request resolved** — the loop drains one **request result** from the result stream (everything the request carried, with its outcome) and feeds it to the partition manager: ACK ⇒ ledgers update, key drivers advance, their next groups are pushed into the sender; failure ⇒ groups go back to their key drivers' queue heads, backoff timers arm; unroutable ⇒ the same, at a gentler pace (§4.5). Then the loop refires the freed stream.
3. **Timer fired** — key backoff expiry (the partition manager re-releases the key into the sender), linger-timer expiry (fire an undersized bin), commit cadence.

The only spawned tasks are the send path itself, inside the sender: one worker stream runner per worker — encode, transmit, await the ACK, post the resolution to the result stream. Because every enqueue and every failure cleanup runs to completion on one thread, **ordering is a property of the structure**: nothing can slip a newer group past a failure being processed, which is exactly the race the worker-stream fences exist to close today. Send origination has one call site instead of four. And the decoupling is in the shape of the seam: releases go into the sender's sink, results come out of the result stream, both as plain values — the transport has no path to a driver at all, and the domain none to a bin, a channel, or a stream.

### 4.3 The sender: packing, placement, composition

**Trigger conditions** (no linger timer in the common path):

- *Idle stream, end of demux cycle*: fire the accumulated bin as one request. Coalescing comes from the synchronous demux of a whole poll — this reproduces today's one-sub-batch-per-worker-per-batch behavior with zero added latency.
- *Busy stream, on resolution*: groups accumulate while a request is in flight; when it resolves, fire what accumulated. Adaptive batching: fast workers get small low-latency requests, slow workers automatically get fuller ones instead of deeper queues. This *is* the eager chain, generalized from one key to the whole stream.
- *Target cap `TARGET_REQUEST_EVENTS` / `_KB`*: a bin at target fires immediately; an over-target bin splits into consecutive requests.
- *Linger timer*: bounds latency for undersized bins at low traffic. Set well under end-to-end latency budgets; the one timer the trigger design needs.

**Placement** (which worker a group's key uses): pins are placement *preferences* carried on each release — honored unless the pinned worker is draining, dead, or drastically overloaded (`slack(T)` — pin abandonment). A preference, not a constraint, is safe here because a key releases only while nothing of its own is in flight (§4.7), so re-picking cannot reorder; the pinned group's volume still counts toward that bin's fill. Fresh keys fill open, in-slice, below-target bins first (load-checked), then rotating P2C opens further slice workers. A release *no* worker can take — pool-wide unroutability only — leaves through the result stream as an `Unroutable` result (§4.5); the sink hands nothing back. Fan-out is **emergent**: demand ÷ target, clamped below by the aperture coverage floor, with slice coverage achieved over seconds by rotation rather than within every batch. The elastic-dispatch fan-out formula stops being a formula.

**Composition** (which groups ride together): each group carries an opaque **affinity** hint — stamped by the partition driver with the partition id, but the sender knows only the preference rule: *minimize distinct affinities per request, choosing affinities oldest-head-first*. A stream's bin holds at most one group per key (key drivers release one at a time), and cross-key order is unconstrained, so composition is free to pack. Affinity-pure requests mean a failed request wounds one partition's frontier, not eight (blast radius), and a slow request delays few frontiers (frontier coupling). Oldest-first keeps the packing strictly latency-safe. The affinity hint also acts as a placement *tie-break* among otherwise-equivalent bins — never overriding load or fill, so a hot partition cannot become a hot worker.

**Stream depth: 1.** One un-ACKed request per worker stream. The stream still provides ordered delivery; depth 1 means a failure's cleanup involves exactly one request's groups, no ledger of un-ACKed successors, no fence. Pipelining depth becomes a tunable only if ACK round-trip proves to be the ceiling.

### 4.4 Two constants instead of a controller

- **`T`** — target request size (`TARGET_REQUEST_EVENTS` / `_KB`, whichever binds), at the sender. Chosen from the knee where per-request fixed cost stops mattering; sized under the worker body limit so §2.10's splitting becomes a rarely-hit defense instead of a routine repair.
- **`B`** — the uncommitted-work budget (`CONSUMER_UNCOMMITTED_BUDGET_EVENTS` / `_BYTES`), at the consumer driver: **poll only while total uncommitted work < B.**

Concurrency then self-clocks. Fast workers: ACKs return quickly, frontiers advance, uncommitted stays low, the poll gate never closes — throughput is CPU-limited and consumer CPU is a truthful autoscaling signal. Slow workers or backlog: uncommitted fills to B, polling pauses, up to ~B/T target-sized requests sit in flight at the workers — which is the worker pool's HPA signal, now denominated in a meaningful unit because every request is target-normalized. The elastic-dispatch controller (EWMA smoothing, ±1/tick slot stepping, the batch-duration budget) existed to steer batch slots toward exactly this behavior; with B and T it is the only behavior the structure can produce.

`B` is also the **crash-replay window, enforced directly**. The elastic plan bounded replay through a duration budget because Little's law was the only handle batch slots offered; here the bound is the number itself. The memory provisioning contract becomes literal — `baseline + librdkafka caps + B_bytes + headroom`, verified at boot — with no ×2 estimation.

### 4.5 Failure handling in the new shape

- **503 / stream busy**: unchanged — the transport's jittered backoff absorbs deliberate backpressure below the model, excluded from passive health.
- **Send failure (fault)**: the request result returns the request's groups whole; the partition manager hands each back to its key driver, which holds it at queue head, arms backoff, and releases again on expiry — placement then re-routes it against current health. This replaces `defer_failed` + re-stash + both flush paths' retry pacing with one local rule. The order argument is trivial: the key's queue *is* the order, and nothing for that key was in flight behind the failure (depth-1 streams, one-release key drivers).
- **Draining/dead worker**: the registry is unchanged; the *consequence* becomes local. A key whose sticky worker is draining simply gets re-placed at its next release — nothing of the key's is in flight at that moment, so re-routing cannot reorder. The cascade rule is the queue: newer groups are behind older ones by construction. No stash, no batch-sequence bookkeeping, no outstanding-count subtlety.
- **Unroutable pool**: placement finds no healthy worker, and the sink has no way to hand work back — the sender posts the release to the result stream as an `Unroutable` result, and it comes home through the one result path like everything else. Its key driver holds the group at queue head (sticky kept — the pool, not the pin, failed) and paces re-releases with a backoff timer; the partition frontiers stall; the watchdog below bounds it.
- **Stall watchdog**: per-partition — a frontier stuck for the timeout while work is pending fails the process, replaying that exposure (≤ B). Today's `deferred_flush_timeout` semantics, at the granularity where a wedge actually lives. A wedged key stalls *its partition's* frontier while healthy partitions keep committing — today it stalls every partition on the pod.
- **Rebalance**: revoke tears down the partition driver via the partition manager; in-flight requests containing its groups resolve and their results are discarded there by epoch; the assignment-epoch stamp (from #85238) keeps worker-side sentinels re-baselined. No batch-scoped state cuts across the revocation.

### 4.6 CPU concurrency

The event loop stays pure bookkeeping; CPU parallelism lives in two places. **Leaves:** encode/compress on the worker stream runners, which already ride the multi-threaded runtime. **Shards:** partition is the natural sharding unit — both invariants are per-partition — so the loop can be sharded by partition (one partition manager and one sender + result stream pair per shard; worker streams then per shard×worker; registry load read as snapshots) with no cross-shard ordering concerns. Ship single-shard with the boundary designed in (no shared mutable state between partition drivers), instrument loop occupancy the way `assign_duration_seconds` is watched today, and shard only when the metric says the loop is the ceiling. Fleet-level parallelism remains partition assignment across pods.

### 4.7 The drivers in pseudocode

Rust-ish pseudocode in §8's vocabulary. The concurrency inventory is deliberately small: **one event-loop task** owning every driver by value, **one long-lived stream runner task per worker**, and two read-only background tasks (the commit monitor, the health probes). Exactly two channel families cross task boundaries, both **private to the transport side**, and requests move through them **by value**:

```text
resolutions   mpsc, unbounded           runners + sender → result stream   posting never blocks the loop; occupancy is
                                                                           structural: ≤1 unreported per runner, plus
                                                                           ≤1 Unroutable per in-flight release (≤ B)
requests[w]   mpsc, capacity 1          sender → runner w                  depth 1 *is* the capacity; try_send never fails
health        snapshot (ArcSwap-style)  probes → router                    the only cross-task shared read
```

The sender and the result stream are built as a pair around the `resolutions` channel: the result stream holds its receive side; the sender holds every `requests[w]` send side plus a `resolutions` send side of its own — cloned to each runner at spawn (`on_worker_discovered` below), and carrying the sender's `Unroutable` posts. Nothing outside the pair touches a channel. The domain's view of the transport is one trait, the loop's is `next() -> RequestResult`, and the values crossing the seam are:

```rust
trait ReleaseSink {                          // the domain's write-only face of the transport;
    fn push(&mut self, release: Release);    //   the sender implements it — a test's is a Vec
}

struct Release {                             // one group, ready to send
    group: Group,                            // carries partition (affinity), epoch, offsets
    sticky: Option<WorkerId>,                // the key's last worker: a placement preference,
}                                            //   honored unless draining/dead/overloaded (§4.3)

struct RequestResult {                       // one resolved request, whole
    outcome: Outcome,                        // transport-classified (§2.9); backpressure and
    groups: Vec<Group>,                      //   413 splits are absorbed below the sender
}

enum Outcome {
    Ack { worker: WorkerId },                // served in full — the worker becomes the pin
    Failure { worker: WorkerId },            // a fault; the groups come home whole
    Unroutable,                              // no worker could take it — pool-wide only (§4.5)
}
```

There is no `Mutex`, no `Arc`'d mutable state, and no atomic in the model: every struct below is owned by the event loop and mutated under plain `&mut`, so lock ordering stops being a concept. The loop has exactly one await point (its `select!`); the runners block only on their own channel and their own socket. And each direction across the seam has exactly one face: the domain writes releases into the sink — threaded down as a plain `&mut` parameter, and only as far as the partition manager; the drivers below it stay pure and hand releases up as return values — while the transport surfaces results only through the result stream.

**Consumer driver — the event loop.** Backpressure is the *absence of the poll branch*, not a check inside it.

```rust
// One task. Sole owner of everything below; mutation is plain &mut, no locks.
struct ConsumerDriver {
    partitions: PartitionManager,            // the domain side: assignments + distribution
    sender: Sender,                          // the transport's intake: placement, bins, streams
    results: ResultStream,                   // the transport's outlet: resolved requests
    timers: BinaryHeap<(Deadline, Timer)>,   // loop-owned deadline heap (§4.1)
    budget: Budget,                          // uncommitted events+bytes — the B gate (§4.4)
    commits: CommitManager,                  // frontiers → one batched commit; tick() below
    kafka: KafkaConsumer,                    // rdkafka client: poll, commits, rebalance events
}

loop {
    select! {                                // the loop's ONLY await point; arms run to
        biased;                              //   completion — drain before taking new work

        result = results.next() => {         // one resolved request, whole — a value, not
            let freed = result.outcome.worker();     //   a callback into the drivers;
            partitions.apply(result, &mut sender);   // successors first, pushed inside —
            if let Some(w) = freed {                 //   then the freed stream: the
                sender.refire(w)                     //   busy-stream trigger (§4.3);
            }                                        //   Unroutable freed no stream
        }

        _ = sleep_until(timers.peek()) => {
            match timers.pop() {
                KeyBackoff(p, key) => partitions.retry(p, key, &mut sender),
                Linger(w)          => sender.fire(w),
                CommitTick         => { commits.tick(); partitions.check_stalls() }
            }
        }

        msgs = kafka.recv(), if budget.used < B => {
            // the gate is rdkafka pause/resume, not an unpolled consumer: polling must
            // continue for rebalance callbacks and max.poll.interval liveness at B
            budget.charge(msgs);
            partitions.accept(msgs, &mut sender);    // the Kafka batch dissolves here
            sender.flush_touched();          // idle-stream trigger: end-of-demux flush
        }

        ev = kafka.rebalance() => {          // surfaces via the same client, serialized
            match ev {                       //   with every other arm: no teardown race
                Assigned(p) => partitions.assign(p, epoch),
                Revoked(p)  => budget.refund(partitions.revoke(p)),  // late results for p
            }                                //   discard by epoch in apply()
        }
    }
}
```

**Partition manager — assignments and work distribution.** The domain side's root: the only component that maps a group back to the state that must act on it. The sink stops here — the drivers below it hand releases up as return values.

```rust
// Loop-owned. Owns every partition driver; passes values down, pushes releases into
// the sink.
struct PartitionManager {
    partitions: Map<Partition, PartitionDriver>,
}

fn assign(p, epoch) { partitions.insert(p, PartitionDriver::new(epoch)) }

fn revoke(p) -> Refund {                     // wholesale: key drivers and pending state go
    partitions.remove(p).teardown()          //   with it; returns the budget to refund
}

fn accept(msgs, sink) {                      // one poll, demuxed to its partitions
    for (p, part) in msgs.by_partition() {
        partitions[p].accept(part).for_each(|r| sink.push(r))
    }
}

fn apply(result, sink) {                     // one request result, distributed
    for group in result.groups {
        if group.epoch.dead() { continue }   // results for revoked partitions die here
        if let Some(r) = partitions[group.partition].apply(group, result.outcome) {
            sink.push(r)
        }
    }
}

fn retry(p, key, sink) { partitions[p].retry(key).for_each(|r| sink.push(r)) }
fn check_stalls() { for p in partitions { p.check_stall() } }
```

**Partition driver — demux, the offset ledger, and acting on results.** A plain struct owned by its partition manager, mutated under `&mut`.

```rust
// Loop-owned (via the partition manager); methods are synchronous and never block.
struct PartitionDriver {
    keys: Map<RoutingKey, KeyDriver>,
    ledger: OffsetLedger,                    // pending offsets (+sizes) · completed · frontier
    stall_deadline: Deadline,
}

fn accept(msgs) -> Vec<Release> {            // one poll's messages for this partition
    ledger.add_pending(msgs);
    msgs.by_routing_key()                    // offset order preserved; groups stamped:
        .filter_map(|(key, group)|           //   affinity = partition, epoch
            keys.entry(key).or_create().enqueue(group))
}

fn apply(group, outcome) -> Option<Release> {    // one group of one resolved request
    match outcome {
        Ack { worker } => {
            ledger.complete(group.offsets);
            if ledger.advance_frontier() {   // highest contiguous completed offset
                stall_deadline = now + STALL_TIMEOUT;
            }
            keys[group.key].acked(worker)    // learn the pin, release the next group
        }
        Failure { .. } => keys[group.key].failed(group),  // back to queue head, backoff arms
        Unroutable     => keys[group.key].hold(group),    // pool-wide (§4.5): gentler pace
    }
}

fn retry(key) -> Vec<Release> { keys[key].try_release().into() }   // backoff expiry

fn check_stall() {
    if ledger.has_pending() && now > stall_deadline {
        fail_process()                       // replay ≤ B; this partition's wedge only (§4.5)
    }
}
```

**Commit manager — frontiers to one batched commit.** The §2.3 verification rides here unchanged.

```rust
// The consumer driver's `commits` field; tick() runs synchronously on the commit cadence.
fn tick() {
    let batch = partitions.filter(frontier advanced).map(|p| (p, p.frontier + 1));
    kafka.commit(batch);                     // manual, async, fire-and-forget: never blocks
    budget.refund(retired_by(batch));        //   the loop; commit exactly the frontier —
    commit_sentinel.assert(batch);           //   B = polled minus committed
}

// Separate long-lived task: read-only against the broker, owns nothing of the loop's.
task commit_monitor {
    loop {
        compare(broker.committed().await, issued);   // unchanged §2.3 — librdkafka drops
        sleep(MONITOR_INTERVAL).await;               //   async commit results
    }
}
```

**Key driver — a passive state machine.** The deferral cascade, the pin, and the retry pacing are all this struct — a plain entry in its partition driver's map: no task, no lock, no ref-count. It hands releases up as return values; it calls nothing.

```rust
// A plain entry in its partition driver's map. No task, no lock, no ref-count.
// Methods run on the loop and never block: "waiting" is an entry in the timer heap.
struct KeyDriver {
    queue: FifoQueue<Group>,
    in_flight: bool,                         // at most one release out at a time
    worker: Option<WorkerId>,                // the sticky pin — learned from ACK results
    backoff: Option<Deadline>,               // armed = an entry in the loop's timer heap
}

fn enqueue(group) -> Option<Release> {
    queue.push_back(group);
    try_release()
}

fn try_release() -> Option<Release> {        // on enqueue, after ACK, on backoff expiry
    if in_flight || queue.is_empty() || backoff.is_some() { return None }
    in_flight = true;
    Some(Release { group: queue.pop_front(), sticky: worker })
}                                            // placement is the sender's — the pin is a
                                             //   preference; safe: nothing of ours in flight

fn acked(worker) -> Option<Release> {
    self.worker = worker;                    // stickiness for the next release
    in_flight = false;
    try_release()                            // then maybe_evict when idle and empty —
}                                            //   the pin dies with the driver

fn failed(group) -> Option<Release> {
    queue.push_front(group);                 // back to head — the key's queue *is* the order
    in_flight = false;
    worker = None;                           // let placement re-pick at the retry
    backoff = arm(RETRY_BACKOFF);            // expiry → retry(p, key) → try_release
    None
}

fn hold(group) {                             // unroutable pool: like failed, gentler pace
    queue.push_front(group);
    in_flight = false;
    backoff = arm(UNROUTABLE_PAUSE);         // sticky kept: the pool, not the pin, failed
}
```

**Sender — the transport's intake.** Placement, bins, triggers, and packing live behind the sink; the loop's nudges are `fire`/`refire`/`flush_touched`. It never calls a driver, and nothing comes back to a `push` caller — an unplaceable release leaves through the result stream.

```rust
// Loop-owned. Nothing outside the transport pair touches a channel, a bin, or a
// stream; nothing inside it holds a reference to a driver.
struct Sender {
    bins: Map<WorkerId, Bin>,                // bin: ordered groups, events/bytes, affinities
    busy: Map<WorkerId, bool>,               // its own record of stream state — set on fire,
    touched: Set<WorkerId>,                  //   cleared in refire(); never shared with runners
    router: Router,                          // aperture + P2C over the health snapshot (§4.3)
    requests: Map<WorkerId, Tx<Request>>,    // send side per runner, capacity 1
    results: Tx<Resolution>,                 // into the result stream — cloned to each runner
}                                            //   at spawn; carries the Unroutable posts too

fn on_worker_discovered(w) {                 // from registry discovery; a reaped worker's
    let (tx, rx) = channel(capacity: 1);     //   runner and channel are torn down with it
    requests.insert(w, tx);
    spawn(stream_runner(w, rx, results.clone()));
}

impl ReleaseSink for Sender {
    fn push(release) {                       // total — nothing is handed back
        match router.place(release.sticky, &bins) {      // §4.3: sticky honored unless
            None =>                                      //   draining/dead/overloaded
                results.send(unroutable(release)),       // pool-wide unroutable (§4.5):
            Some(w) => {                                 //   leaves via the result stream
                bins[w].push(release.group);     // ≤1 group per key per bin: key drivers
                touched.insert(w);               //   release one at a time
                if bins[w].size >= T { try_fire(w) }     // target cap: fires now if idle
                else if !busy[w] && !in_demux_cycle {
                    arm_linger(w)                // covers releases via ACK-advance and
                }                                //   backoff expiry — no demux flush follows
            }
        }
    }
}

fn flush_touched() {
    for w in touched.drain() { try_fire(w) } // idle-stream trigger: one request per
}                                            //   worker per poll, zero added latency

fn fire(w) { try_fire(w) }                   // linger expiry: an undersized idle bin

fn refire(w) {                               // once per drained result for w — the stream
    busy[w] = false;                         //   is free again; fire what accumulated: the
    try_fire(w)                              //   busy-stream trigger, the eager chain
}                                            //   generalized from one key to the stream

fn try_fire(w) {                             // the single send-origination site
    if busy[w] || bins[w].is_empty() { return }
    let request = pack(bins[w]);             // §4.3: take ≤ T, minimize distinct affinities,
                                             //   oldest-head-first; remainder stays binned
    requests[w].try_send(request).unwrap();  // non-blocking; capacity 1, provably never full:
    busy[w] = true;                          //   sends happen only while !busy, and busy
}                                            //   clears only in refire(), after this
                                             //   request's resolution has been applied
```

**Result stream — the transport's outlet.** One resolved request at a time; the loop applies it to the partition manager, then refires the freed stream.

```rust
// Loop-owned; the receive half of the pair. Everything a resolved request carried,
// with its outcome — nothing else escapes the transport side.
struct ResultStream {
    resolutions: Rx<Resolution>,             // posted by runners and by the sender
}

async fn next() -> RequestResult {           // the loop's one view of transport progress
    let (outcome, groups) = resolutions.recv().await;
    RequestResult { outcome, groups }
}
```

**Router placement** (§4.3) — inside the sender; `sticky` is the release's preference, not a constraint:

```rust
fn place(sticky, bins) -> Option<WorkerId> {
    let health = registry.snapshot();        // published by the probe task; the model's
                                             //   only cross-task shared read — no lock
    if let Some(w) = sticky {
        if healthy(w) && !overloaded_beyond_slack(w, T) { return Some(w) }
    }                                        // else fall through: pin abandonment — safe,
                                             //   nothing of that key is in flight (§4.3)
    let slice = aperture.slice(health);      // in-slice candidates
    let open = slice.healthy, below-target bins, load-checked;
    if open is non-empty {
        pick by fill, affinity overlap as tie-break   // never overriding load or fill
    } else {
        rotating_p2c(slice)                  // opens further slice workers
    }
    // none healthy → None: push turns it into an Unroutable result; its key driver
}   //   backs off (§4.5)
```

**Worker stream runner — one task per worker, depth 1.** The machinery below the sender, which hands it both channel ends at spawn.

```rust
// One long-lived task per worker. Owns its connection; shares only the two channels
// (received from on_worker_discovered), and both hand data over by value.
task stream_runner(w, requests: Rx<Request>, resolutions: Tx<Resolution>) {
    loop {
        connect_and_greet(epoch).await;      // BLOCKS (its own socket); on failure:
                                             //   backoff, then reconnect
        while connected {
            let request = requests.recv().await;     // BLOCKS — the depth-1 wait lives
                                                     //   here, in the runner, not the loop
            encode_and_transmit(request).await;      // CPU + I/O off the loop (§4.6 leaves)
            let outcome = select! { ack | stream_error | ack_timeout }.await;
            resolutions.send(classify(w, outcome), request.take_groups());  // never blocks
        }
        // stream break: the in-hand request (if any) reports Failure the same way — one
        // request's groups, handed back whole; no successor ledger, no fence
    }
}

fn classify(w, outcome) {                    // the transport classifier, §2.9 unchanged
    match outcome {
        Ack          => Ack { worker: w },
        Busy | 503   => Backpressure,        // long jittered backoff; excluded from
                                             //   passive health
        Fault        => Failure { worker: w },   // counts against passive health; the
                                             //   result stream hands the groups back whole
        Oversize413  => split_halve_resend() // §2.10 defense below the model — rare
    }                                        //   once T is under the worker body limit
}
```

What is *not* here is the point: no stash, no batch-sequence bookkeeping, no fences or `FenceGuard`, no eager reconciliation, no completion serialization — and no locks: today's `PinTable` mutex and its lock-ordering discipline have no successor, because nothing is shared to lock. The order argument is visible as four structural facts — one origination site (`try_fire`), at most one released group per key, capacity-1 request channels, and a loop that finishes each event's cascade before starting the next. And the coupling argument is a fifth: each direction across the seam has its own value-carrying face — releases go into the sender's sink, results come out of the result stream — so neither side can observe, or corrupt, the other mid-transition, and the transport has no path to a driver even to misuse.

## 5. Construct-by-construct disposition

| Today | In the driver model |
|-------|---------------------|
| Batch collection | Unchanged as input format; batch dissolves at demux |
| In-flight batch window (2.1) | Retired; replaced by budget `B` (poll gate) |
| Oldest-first completion (2.2) | Retired; per-partition offset ledger commits the contiguous frontier |
| Commit sentinel (2.3) | Kept as a cheap assert; contiguity is now constructed, not emergent |
| Commit monitor (2.3) | Kept as-is (librdkafka async-commit blindness is unchanged) |
| Sticky pins (2.4) | The key driver's current-worker field; eviction = driver eviction |
| Stash + cascade rule (2.5) | The key driver's FIFO; the cascade is the queue |
| Completion-time flush (2.6) | Retired; commit gate → ledger, retry pacing → per-key backoff timers, watchdog → per-partition stall deadline |
| Eager flush + its accounting (2.7) | Becomes the *only* drain mechanism (resolution cascade + stream refill); `eager_pending`/`eager_accepted`/`take_eager_accepted` deleted |
| Worker-stream ledger + fences (2.8) | Depth-1 streams + single-threaded origination; ordered stream kept, fences and consecutive-prefix resolution deleted |
| 503/backoff/backpressure classification (2.9) | Unchanged |
| Body split + 413 (2.10) | Kept as defense; `T` makes routine splitting stop happening |
| Worker registry (2.11) | Unchanged; drain consequences become key-driver-local |
| Aperture + P2C (2.12) | Kept for placement; fan-out formula retired (emergent from demand ÷ `T`); `STICKY_PIN_LOAD_SLACK` re-derived against `T` |
| Key-order sentinel (2.13) | Kept as a cheap assert; order is now structural (one origination site, one-release key drivers, depth-1 streams) |
| Debug recorder | Kept; event points move to the drivers (arguably richer: per-key and per-partition state is now first-class) |

The through-line: the mechanisms that survive are the ones facing the outside world (transport classification, registry, discovery, sentinels-as-audit). The mechanisms that dissolve are the ones that bridged batch-shaped machinery to key/partition-shaped invariants.

## 6. How this drives the autoscaling plan

The elastic-dispatch plan's three changes map onto the model as follows:

1. **Target-sized worker batches** — the sender's `T` and packing rules (§4.3) *are* stage 1 of the plan, with the fan-out clamp formula replaced by emergence and the pins-as-preferences packing expressed structurally.
2. **Demand-proportional concurrency** — the plan's controller (fill-EWMA → slots, duration budget, shed policy) is subsumed by `B` + self-clocking (§4.4). The behaviors the controller had to *steer toward* — MIN concurrency when drained, MAX under backlog, held pressure during worker saturation, bounded replay window, walk-down during a wedge (per-partition stalls now localize it) — are the only behaviors the structure permits. No EWMA, no tick, no shed policy, nothing to mis-tune.
3. **One-signal worker HPA** (the elastic plan's "processor HPA") — unchanged from the plan (`ingestion_api_event_seconds_in_flight_total`, time-weighted in-flight events per pod), and *strengthened*: every request is target-normalized, so in-flight work per worker is an honest, comparable unit.

The two scaling regimes the plan demands fall out of the poll gate:

- **Workers fast, backlog draining**: the gate stays open, the consumer is CPU-bound (demux, packing, encode), its CPU-only HPA is truthful — pods scale when the consumer is the bottleneck, and only then.
- **Workers slow / pool undersized**: uncommitted work fills `B`, polling pauses at low CPU (the consumer fleet correctly *doesn't* scale), and B/T requests held in flight drive the worker pool out. The transport's jittered backoff bounds futile traffic; a 503'd request never counts as worker occupancy, so the scale-out signal can't be starved — same reasoning as the plan's "no congestion input" argument, unchanged.

## 7. Open questions

1. **Build order.** The elastic plan's stages 1–2 can land on the current architecture (they're specced that way); the driver model delivers the same behavior by structure. Options: (a) elastic stages on the current code first, redesign later — two migrations, faster relief; (b) build the driver model and ship the elastic behavior with it — one migration, longer lead. The controller-free shape argues for (b) if the incident pressure allows; the stage 1 packing changes are the piece most worth doing early either way, since the packer carries over almost verbatim.
2. **Linger timer default** — small enough not to show in end-to-end latency; exact value from stream traffic percentiles.
3. **Stream pipelining depth** — start at 1; revisit only if ACK round-trip caps a stream's throughput below what one worker can absorb.
4. **Partition fairness at the poll gate** — one global `B` lets a deep partition monopolize the budget. Levers, in escalation order: none (watch it), rdkafka per-partition pause/resume, isolating hot partitions on dedicated pods at the assignment level. Don't build until observed.
5. **Shard count** — single-shard until loop occupancy says otherwise (§4.6).
6. **`B` and `T` defaults** — `T` from the per-request-cost knee (the elastic plan's stage 1 calibration, unchanged); `B` from the acceptable replay window and the memory contract, with the plan's ~"MAX × batch" residual exposure as the anchor.

## 8. Nomenclature

The consumer's vocabulary has to survive three audiences at once: this crate, the Node.js worker across the wire, and the rest of PostHog — where `lane`, `group`, `chunk`, `cohort`, and `fence` already mean things. The rules of this doc: §2 describes today's constructs under the names the code actually uses; §4 onward uses only the canonical terms below. A "never" entry reserves the word — new type, config, metric, and proto names must not reuse it for another concept.

### 8.1 Canonical terms

| Term | Means | Never |
|---|---|---|
| `lane` | the deployment axis (`INGESTION_LANE`; global `ingestion_lane` metric label) | anything consumer-internal |
| `worker` | one Node.js ingestion-api process (proto `WorkerIngest`) | processor |
| `worker stream` | the ordered gRPC connection to one worker (`WorkerStream`) | lane |
| `batch` | one Kafka collection unit; dissolves at demux | the worker-facing unit |
| `sub-batch` | today's worker-facing unit (proto `SubBatch`); retired by this design | — |
| `request` | this design's worker-facing unit: one target-sized send | batch, sub-batch |
| `group` | one routing key's messages from one poll (`MessageGroup`) | chunk |
| `consumer group` | the Kafka sense, always spelled in full | bare "group" |
| `chunk` | a body-size split of one request (the transport's 413 path) | the per-key unit |
| `routing key` | `token:distinct_id`, the per-key order unit | "distinct_ids" when counting keys |
| `defer` | hold a key's newer work until its older work lands | stash, in new names |
| `frontier` | highest contiguous completed offset, per partition | watermark |
| `watermark` | highest ACKed offset, per key (the order sentinel's sense) | high-water mark |
| `ledger` | the partition driver's offset accounting | the eager-flush accounting |
| `fence` | the worker stream's failure barrier (`FenceGuard`) | partition→pod isolation |
| `affinity` | the sender's composition hint (today: the partition id) | cohort |
| `linger timer` | the undersized-bin latency bound (Kafka's `linger.ms` sense) | gather timer |
| `bin` | the sender's per-stream accumulation buffer | — |
| `resolve` | a send finished, success or failure | settle |
| `eager-flush task` | the ACK-speed drain task (`run_eager_flush_loop`) | sidecar |
| `window` | always qualified: in-flight, passive, stall, replay window | bare "the window" |
| `driver` | the single owner of one unit's state, advanced only by events | — |
| `partition manager` | the domain side's root: assignment lifecycle + work distribution | — |
| `release` | one group handed to the sender, with its placement preference | the ship-a-version sense |
| `request result` | one resolved request, whole: groups + outcome | resolution, outside the transport side |
| `sender` | the transport's intake: placement, bins, triggers, stream runners | a channel end — write `Tx` / "send side" |
| `result stream` | the transport's outlet: resolved requests, drained by the loop | — |
| `sink` | the domain's write-only face of the sender (`push(release)`) | — |

### 8.2 Why these words are reserved

- **`lane`** is claimed three times over: capture's `Lane { Main, Overflow, Historical }` routing enum (plus the AI lane's topics), the Node deployment lanes (`INGESTION_LANE`, one namespace per lane, the `ingestion_lane` Prometheus label), and this binary stamps that label on every metric it emits. Drafts of #85238 called the gRPC construct a lane; the merged code says `WorkerStream`, and this doc follows the code.
- **`worker`, not `processor`**: every artifact of the downstream fleet says worker — the proto package `ingestion.worker.v1`, `INGESTION_WORKER_CONCURRENT_BATCHES`, `rust/ingestion-worker-proto`, the `worker` metric label. "Processor" is the elastic-dispatch plan's word for the same fleet (kept there, mapped in §6); in code, `*Processor` already means an in-process pipeline stage in both Rust and Node. One fleet, one name.
- **`group`, not `chunk`**, for the per-key unit: this crate's `MessageGroup`/`DeferredGroup` and the Node framework's `concurrentlyPerGroup(getTokenAndDistinctId, …)` are the same concept with the same key on both ends of the wire. `chunk` is doubly taken: the transport's 413 split (kept by §5), and the Node framework's per-stage unit (`ChunkPipeline`, whose docs explicitly contrast chunks with batches). The price is that the Kafka sense must always be written "consumer group".
- **`cohort` → `affinity`**: cohort is a core product noun (user cohorts, the cohorts API, five `rust/cohort-*` crates). The hint is the partition id used as a packing preference; affinity says exactly that.
- **`fence`** stays only because the merged worker-stream code uses it in the same sense personhog does — a barrier that stops the old flow before new work may start. Partition→pod placement (§7.4) is *isolation*, not fencing.
- **`frontier` vs `watermark`**: the code already uses watermark for the per-key ACK point (order sentinel); the per-partition commit point gets its own word instead of overloading it. Earlier drafts used the two interchangeably.
- **`linger`, not `gather`**: `gather` is this crate's scatter/gather verb — failed sends "land in gather order" — and the timer is Kafka's `linger.ms` concept, which every reader of an ingestion codebase already knows.
- **`sender` vs channel ends**: the component is the sender; a channel's ends are `Tx`/`Rx` ("send side"/"receive side") in code and prose, so the two never collide. Earlier drafts called the whole transport side the "worker batcher"; the split into sender and result stream (§4.1) retired that name.

### 8.3 Cleanups this implies in today's code

Independent of the redesign; each is a small standalone chore PR.

1. Metrics `ingestion_consumer_stashed_{batches,groups,messages}` → `deferred_*` — one queue is graphed under two prefixes today, while the config surface (`CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS`, `DISPATCHER_EAGER_DEFERRED_FLUSH`) only says deferred.
2. `Stash::completed` → `routed` — its own docstring says "mark … as routed"; every other `complete_*` in the crate means finished.
3. `Stash::is_deferring` → `has_unlanded_work` — deliberately true while the queue is empty (§2.5); the name should state the predicate callers branch on.
4. `PinTable` → `DispatchState` — it holds pins, in-flight counts, the stash, and the eager accounting; its own doc comment calls it "mutable assignment state".
5. `intra_group_disorder` → `intra_key_disorder`; the `distinct_ids` debug fields and `ingestion_consumer_distinct_ids_per_batch` count routing keys, so name them that (one distinct_id under two tokens is two keys).
6. `send_batch` → `send_sub_batch`; document `IngestBatchRequest.batch_id` as a provenance tag (one Kafka batch fans out across workers, splits, and retries), not a request identity.
7. Comment drift: one dispatcher comment calls a group's flushed work a "chunk"; the `on_sub_batch_resolved` contract comment sits on `on_sub_batch_acked`; `retry_backoff`'s docstring sits on `make_consumer_id`; the `SubBatchResolved` debug event says "(ACK)" but fires on failures too.

### 8.4 Enforcement

Vocabulary rules decay unless something checks them.

1. **A vocabulary test in the crate**: a `#[test]` that scans `src/` for reserved words out of place — `lane` outside the `INGESTION_LANE` sites, `cohort` or `processor` anywhere, `chunk` outside the transport's split path — each entry carrying a one-line reason, so the failure message teaches the rule it enforces.
2. **A metric-name fixture test**: assert the crate's emitted metric names against a checked-in list, so every new or renamed metric is a reviewed diff; the list doubles as the dashboard author's index.
3. **`lib.rs` points here**: one paragraph in the crate docstring naming this section as the vocabulary authority, because that is the first file a new reader opens.
4. **Names come from the table**: a new env var, metric, type, or proto field either reuses a canonical term or extends the table in the same PR — never a new synonym for an existing concept.
