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
consumer loop                     (1 per pod; the event pump)
  ├── partition manager           (1 per pod; assignments + work distribution)
  │     ├── partition driver      (1 per assigned partition)
  │     │     └── key driver      (1 per active routing key, passive)
  │     └── accumulator           (one cascade's releases; released to the batcher)
  ├── worker batcher              (1 background task; the transport side, whole)
  │     ├── router/aperture       (placement — §4.3)
  │     ├── packer + size defense (request composition; §2.10 kept below it)
  │     └── stream runners        (1 task per worker; depth-1 ordered send)
  ├── result stream               (batcher → loop; the transport's outlet)
  ├── commit manager              (1 per pod; frontiers → one batched commit)
  └── budget                      (the B poll gate; charged at poll, refunded at commit)

shared services: worker registry + discovery · transport classifier ·
                 sentinels (asserts) · debug recorder
```

The hierarchy follows containment in the *data*: a partition contains per-key message sequences; a key's sequence is consumed in **groups** (one poll's messages for one key — the code's `MessageGroup`). The Kafka batch is demoted to an input format: it exists during collection and **dissolves at demux**. Nothing downstream tracks it. A *driver* here means exactly one thing: the single owner of one unit's state, advanced only by events.

Below the consumer loop the tree has exactly two sides — the **domain side** (partition manager down to key drivers) and the **transport side** (the worker batcher and everything under it, with the result stream as its outlet) — and the seam between them is two channels of plain values: **accumulators** of releases go down, **request results** come back up (§4.7). During a cascade the accumulator is exclusively borrowed (`&mut`) — there is no locking anywhere; the only coordination in the whole hand-off is the release itself, one channel send per cascade. Neither side holds a reference into the other, and because the transport runs as its own task, placement and packing overlap the loop's next cascade.

- **Consumer loop** — polls rdkafka, applies backpressure (§4.4), drains the result stream, watches assignment events, and hands each of them to the partition manager; between events it sleeps until the earliest deadline any component owns. Deliberately not a *driver* — it owns no unit's state (§8). With the transport behind the accumulator hand-off and every firing trigger event-driven inside the batcher (§4.3), it is a pure event pump: it owns nothing partition- or worker-shaped and knows no timer kinds.
- **Partition manager** — the domain side's root. Owns the partition drivers and their lifecycle: partition assigned ⇒ create a driver; revoked ⇒ tear it down wholesale, with its key drivers and pending state (the rebalance unit and the component unit coincide). Owns the per-cascade **accumulator** and its send side toward the worker batcher — a test just reads the buffer, no transport required — and the domain's only clock, the stall-sweep cadence. Distributes work: demuxes each poll to its partition drivers, routes each request result's groups back to the partition driver that owns them, discards results whose assignment epoch is dead, collects every release its drivers hand up into the accumulator (under `&mut`, no locking), and ends every producing cascade by **releasing** it — one channel send, the hand-off's only coordination. Everything it passes down and collects up is a value.
- **Partition driver** — splits its messages by routing key into groups and hands them to key drivers; owns the **offset ledger**: the set of pending offsets and the highest contiguous completed offset (the **frontier**), which is what gets committed, on a cadence. Contiguity becomes *constructive* — the ledger computes exactly the committable frontier — instead of a property to verify after the fact.
- **Key driver** — a passive state machine (a struct in a map, not a task; key cardinality is unbounded): a FIFO of groups, **at most one group released at a time** (binned, parked, or in flight), the rest queued behind it. On ACK: report offsets to the partition ledger, remember which worker served it (the sticky pin), release the next group. On failure: take the group back at queue head and release it again in the same cascade — re-placement, not waiting, is the response, because retry pacing lives in the transport (§2.9, §4.5). It names a *preference*, never a worker — placement is the batcher's. Created on first group, evicted when idle and empty.
- **Worker batcher** — the transport side, whole, as one background task. Each received accumulator is placed (router + pins-as-preferences, §4.3), binned per worker, and fired as target-sized requests down the ordered streams; each runner resolution frees its stream, is forwarded to the result stream, and refills the stream from its bin at once. A release no worker can take is **parked** inside the batcher and re-placed on its next wake (§4.5) — nothing is ever handed back. It never calls a driver. The packer and the §2.10 size defense sit below it, as do the stream runners: one task per worker — connect, greet with the assignment epoch, transmit, await ACKs, depth 1 — and the transport classifier, §2.9 unchanged (backpressure vs fault vs non-retriable, backpressure excluded from passive health).
- **Result stream** — the transport's outlet: one **request result** at a time — every group a resolved request carried, with its outcome — and nothing else escapes. The batcher forwards each resolution the moment it arrives; the loop drains it and feeds the partition manager.
- **Commit manager** — on the commit cadence, reads each partition driver's frontier, issues one batched manual commit, and refunds the budget for the retired work. The §2.3 verification rides here unchanged: the commit sentinel as a cheap assert, the commit monitor because librdkafka still drops async commit results.
- **Budget** — the `B` accounting (charged at poll, refunded at commit and at revoke teardown). There is no timer service: the design has two standing clocks — the stall sweep in the partition manager, the commit cadence in the commit manager; the loop just sleeps until the earlier `next_deadline()` — plus the batcher's park-retry, armed only while an unroutable pool leaves releases parked (§4.5). Key drivers own no deadlines at all: retry pacing is transport-level, so unbounded key cardinality meets no per-key timer anywhere.

### 4.2 Two tasks, synchronous cascades

State transitions split across two single-threaded tasks — the domain's on the consumer loop, the transport's on the worker batcher (sharding noted in §4.6) — each driven by three event sources, each finishing one cascade before taking the next event. The loop's:

1. **Poll delivered** — the partition manager demuxes to partition drivers → key drivers enqueue and hand back released groups → the manager collects them into the accumulator and ends the cascade by releasing it to the batcher.
2. **Request resolved** — the loop drains one **request result** from the result stream and hands it to the partition manager: ACK ⇒ ledgers update, key drivers advance, their next groups accumulate; failure ⇒ groups go back to their key drivers' queue heads and re-release in the same cascade (§4.5). The cascade ends the same way: release the accumulator.
3. **Deadline reached** — the loop sleeps until the earlier of the two standing deadlines, then wakes both owners: the partition manager runs its stall sweep, the commit manager its cadence. A wake with nothing due is a no-op.

And the batcher's:

1. **Accumulator received** — re-place anything parked (health may have changed), place and bin each release, fire every idle stream the batch touched.
2. **Resolution received** — mark the runner's stream idle, forward the request result to the result stream, refill the stream from its bin at once; the resolved keys' successors arrive with a later accumulator.
3. **Park-retry due** — re-place the parked releases against the current health snapshot; armed only while something is parked (§4.5).

The spawned tasks are the batcher and, below it, one worker stream runner per worker — encode, transmit, await the ACK, post the resolution back. Because every structure is owned by exactly one task and each task finishes a cascade before its next event, **ordering is a property of the structure**: a key has at most one release out anywhere in the system, so nothing can slip a newer group past a failure being processed — exactly the race the worker-stream fences exist to close today. Send origination has one call site instead of four. And the two sides overlap in time: while the batcher places one cascade's releases, the loop is already demuxing the next.

### 4.3 The batcher: packing, placement, composition

**Trigger conditions** (no linger timer; the transport's one clock is the park-retry, §4.5):

- *Accumulator arrival*: place and bin the batch, then fire each idle stream it touched. For a poll's cascade this reproduces today's one-sub-batch-per-worker-per-batch behavior with zero added latency; for a result's cascade it coalesces one ACK's successors the same way.
- *Busy stream, on resolution*: groups accumulate in the bin while a request is in flight; the moment the resolution arrives the batcher refills the stream from its bin — the resolved keys' successors ride a later accumulator. Adaptive batching: fast workers get small low-latency requests, slow workers automatically get fuller ones instead of deeper queues. This *is* the eager chain, generalized from one key to the whole stream.
- *Target cap `TARGET_REQUEST_EVENTS` / `_KB`*: a bin at target fires mid-batch; an over-target bin splits into consecutive requests.

A linger timer is unnecessary: every release arrives inside an accumulator whose arrival is itself the flush, so no bin ever waits on a clock — the undersized-bin case fires on arrival with zero added latency, and only a busy stream holds a bin back, paced by its own resolution.

**Placement** (which worker a group's key uses): pins are placement *preferences* carried on each release — honored unless the pinned worker is draining, dead, or drastically overloaded (`slack(T)` — pin abandonment). A preference, not a constraint, is safe here because a key releases only while nothing of its own is in flight (§4.7), so re-picking cannot reorder; the pinned group's volume still counts toward that bin's fill. Fresh keys fill open, in-slice, below-target bins first (load-checked), then rotating P2C opens further slice workers. A release *no* worker can take — pool-wide unroutability only — parks in the batcher and is re-placed at its next wake (§4.5); nothing is ever handed back. Fan-out is **emergent**: demand ÷ target, clamped below by the aperture coverage floor, with slice coverage achieved over seconds by rotation rather than within every batch. The elastic-dispatch fan-out formula stops being a formula.

**Composition** (which groups ride together): each group carries an opaque **affinity** hint — stamped by the partition driver with the partition id, but the batcher knows only the preference rule: *minimize distinct affinities per request, choosing affinities oldest-head-first*. A stream's bin holds at most one group per key (key drivers release one at a time), and cross-key order is unconstrained, so composition is free to pack. Affinity-pure requests mean a failed request wounds one partition's frontier, not eight (blast radius), and a slow request delays few frontiers (frontier coupling). Oldest-first keeps the packing strictly latency-safe. The affinity hint also acts as a placement *tie-break* among otherwise-equivalent bins — never overriding load or fill, so a hot partition cannot become a hot worker.

**Stream depth: 1.** One un-ACKed request per worker stream. The stream still provides ordered delivery; depth 1 means a failure's cleanup involves exactly one request's groups, no ledger of un-ACKed successors, no fence. Pipelining depth becomes a tunable only if ACK round-trip proves to be the ceiling.

### 4.4 Two constants instead of a controller

- **`T`** — target request size (`TARGET_REQUEST_EVENTS` / `_KB`, whichever binds), at the worker batcher. Chosen from the knee where per-request fixed cost stops mattering; sized under the worker body limit so §2.10's splitting becomes a rarely-hit defense instead of a routine repair.
- **`B`** — the uncommitted-work budget (`CONSUMER_UNCOMMITTED_BUDGET_EVENTS` / `_BYTES`), at the consumer loop: **poll only while total uncommitted work < B.**

Concurrency then self-clocks. Fast workers: ACKs return quickly, frontiers advance, uncommitted stays low, the poll gate never closes — throughput is CPU-limited and consumer CPU is a truthful autoscaling signal. Slow workers or backlog: uncommitted fills to B, polling pauses, up to ~B/T target-sized requests sit in flight at the workers — which is the worker pool's HPA signal, now denominated in a meaningful unit because every request is target-normalized. The elastic-dispatch controller (EWMA smoothing, ±1/tick slot stepping, the batch-duration budget) existed to steer batch slots toward exactly this behavior; with B and T it is the only behavior the structure can produce.

`B` is also the **crash-replay window, enforced directly**. The elastic plan bounded replay through a duration budget because Little's law was the only handle batch slots offered; here the bound is the number itself. The memory provisioning contract becomes literal — `baseline + librdkafka caps + B_bytes + headroom`, verified at boot — with no ×2 estimation.

### 4.5 Failure handling in the new shape

- **503 / stream busy**: unchanged — the transport's jittered backoff absorbs deliberate backpressure below the model, excluded from passive health.
- **Send failure (fault)**: the request result returns the request's groups whole; the partition manager hands each back to its key driver, which puts it back at queue head and re-releases it in the same cascade — placement re-picks against current health. No domain backoff: the transport already retried transient faults with its own backoff below the model (§2.9), and passive health has already marked the failing worker, so waiting again in the key driver would be double pacing. This replaces `defer_failed` + re-stash + both flush paths' retry pacing with one local rule. The order argument is trivial: the key's queue *is* the order, and nothing for that key was in flight behind the failure (depth-1 streams, one-release key drivers).
- **Draining/dead worker**: the registry is unchanged; the *consequence* becomes local. A key whose sticky worker is draining simply gets re-placed at its next release — nothing of the key's is in flight at that moment, so re-routing cannot reorder. The cascade rule is the queue: newer groups are behind older ones by construction. No stash, no batch-sequence bookkeeping, no outstanding-count subtlety.
- **Unroutable pool**: placement finds no healthy worker — the release **parks** in the batcher, which re-tries placement on every wake: each arriving accumulator, each resolution's refill, and a park-retry deadline armed only while something is parked (the backstop when both go quiet). Waiting for a routable pool is transport state, so both the parking and its pacing live in the transport — the domain never arms a timer for it, and nothing is handed back. Unlike the stash, parked carries no ordering: at most one release per key (a parked release is still that key's one-out), cross-key order free. The partition frontiers stall; the watchdog below bounds it.
- **Stall watchdog**: per-partition — a frontier stuck for the timeout while work is pending fails the process, replaying that exposure (≤ B). Today's `deferred_flush_timeout` semantics, at the granularity where a wedge actually lives; the sweep runs on the partition manager's own cadence, the domain's only clock. A wedged key stalls *its partition's* frontier while healthy partitions keep committing — today it stalls every partition on the pod.
- **Rebalance**: revoke tears down the partition driver via the partition manager; in-flight requests containing its groups resolve and their results are discarded there by epoch; the assignment-epoch stamp (from #85238) keeps worker-side sentinels re-baselined. No batch-scoped state cuts across the revocation.

### 4.6 CPU concurrency

The event loop is pure domain bookkeeping by construction: placement and packing run on the worker batcher task, encode/compress on the stream runners, and the pipeline overlaps — while the batcher places one cascade's releases, the loop demuxes the next. If a task ever becomes the ceiling, each side shards on its own invariant's axis. **Domain:** by partition — one partition manager (with its own accumulator channel) per shard, all feeding the one batcher, so per-worker bins stay global and cross-partition coalescing is preserved. **Transport:** by worker — bins, busy state, and streams are per-worker with no cross-worker state. Ship unsharded with the boundary designed in (no shared mutable state between partition drivers), instrument both tasks' occupancy the way `assign_duration_seconds` is watched today, and shard only the side the metric names. Fleet-level parallelism remains partition assignment across pods.

### 4.7 The drivers in pseudocode

Rust-ish pseudocode in §8's vocabulary. The concurrency inventory is deliberately small: **one event-loop task** owning every driver by value, **one worker-batcher task** owning everything transport-shaped, **one long-lived stream runner task per worker**, and two read-only background tasks (the commit monitor, the health probes). Four channel families cross task boundaries — plus one shared snapshot — and everything on them moves **by value**:

```text
accumulators  mpsc                      loop → batcher      one send per cascade — the hand-off's only
                                                            coordination; content is bounded by B
resolutions   mpsc, bound ≥ pool size   runners → batcher   send never blocks (≤1 unreported per runner)
requests[w]   mpsc, capacity 1          batcher → runner w  depth 1 *is* the capacity; try_send never fails
results       mpsc, bound ≥ pool size   batcher → loop      ≤1 unresolved request per worker (depth-1 streams)
health        snapshot (ArcSwap-style)  probes → router     the only cross-task shared read
```

The `accumulators` channel is unbounded in count but self-limiting in content: every queued release is uncommitted work under the `B` gate, and a lagging batcher starves the domain of ACKs, which closes polling. The domain's outbound face is not an interface at all — it is the accumulator, plain data filled under `&mut`; the loop's inbound face is `next() -> RequestResult`. The values crossing the seam are:

```rust
struct Accumulator(Vec<Release>);            // one cascade's releases, in cascade order —
                                             //   filled under &mut during the cascade (no
                                             //   locking), then released to the batcher
                                             //   whole, by value: one send per cascade

struct Release {                             // one group, ready to send
    group: Group,                            // carries partition (affinity), epoch, offsets
    sticky: Option<WorkerId>,                // the key's last worker: a placement preference,
}                                            //   honored unless draining/dead/overloaded (§4.3)

struct RequestResult {                       // one resolved request, whole
    worker: WorkerId,
    outcome: Ack | Failure,                  // transport-classified (§2.9); backpressure,
    groups: Vec<Group>,                      //   retries, and 413 splits are absorbed below
}
```

There is no `Mutex`, no `Arc`'d mutable state, and no atomic in the model: every struct below is owned by exactly one task and mutated under plain `&mut`, so lock ordering stops being a concept. The loop and the batcher each have exactly one await point (their `select!`s); the runners block only on their own channel and their own socket. The accumulator is exclusively borrowed for the length of a cascade — the drivers below the manager stay pure, handing releases up as return values — and the only coordination between the two sides is the release itself: one channel send, after which the loop never touches that buffer again.

**Consumer loop — the event pump.** Backpressure is the *absence of the poll branch*, not a check inside it. Deliberately not a driver: it owns no unit's state — it checks results, fetches messages, watches assignments, and hands each to the partition manager.

```rust
// The event pump. Owns the domain side and the result stream's receive half;
// mutation is plain &mut, no locks.
struct ConsumerLoop {
    partitions: PartitionManager,            // the domain side; releases the accumulator
    results: ResultStream,                   // the transport's outlet: resolved requests
    budget: Budget,                          // uncommitted events+bytes — the B gate (§4.4)
    commits: CommitManager,                  // frontiers → one batched commit; owns its cadence
    kafka: KafkaConsumer,                    // rdkafka client: poll, commits, rebalance events
}

loop {
    select! {                                // the loop's ONLY await point; arms run to
        biased;                              //   completion — drain before taking new work

        result = results.next() => {         // one resolved request, whole — a value, not a
            partitions.apply(result)         //   callback into the drivers; the successors
        }                                    //   accumulate and release inside

        _ = sleep_until(min(partitions.next_deadline(),  // components own their deadlines;
                            commits.next_deadline())) => {   //   the loop knows only when
            partitions.wake(now);            //   the earliest is due — a wake with nothing
            commits.wake(now);               //   due is a no-op
        }

        msgs = kafka.recv(), if budget.used < B => {
            // the gate is rdkafka pause/resume, not an unpolled consumer: polling must
            // continue for rebalance callbacks and max.poll.interval liveness at B
            budget.charge(msgs);
            partitions.accept(msgs)          // the Kafka batch dissolves here; the cascade
        }                                    //   ends by releasing the accumulator

        ev = kafka.rebalance() => {          // surfaces via the same client, serialized
            match ev {                       //   with every other arm: no teardown race
                Assigned(p) => partitions.assign(p, epoch),
                Revoked(p)  => budget.refund(partitions.revoke(p)),  // late results for p
            }                                //   discard by epoch in apply()
        }
    }
}
```

**Partition manager — assignments, work distribution, and the accumulator.** The domain side's root: the only component that maps a group back to the state that must act on it, and the owner of the accumulator. The buffer stops here — the drivers below it hand releases up as return values.

```rust
// Loop-owned. Owns every partition driver, the accumulator, and the domain's one
// clock (the stall sweep); passes values down, collects releases into the
// accumulator under &mut, and ends every producing cascade by releasing it.
struct PartitionManager {
    partitions: Map<Partition, PartitionDriver>,
    acc: Accumulator,                        // this cascade's releases; a test reads it
    batcher: Tx<Accumulator>,                // the release point — one send per cascade
    sweep_at: Deadline,
}

fn assign(p, epoch) { partitions.insert(p, PartitionDriver::new(epoch)) }

fn revoke(p) -> Refund {                     // wholesale: key drivers and pending state go
    partitions.remove(p).teardown()          //   with it; returns the budget to refund
}

fn accept(msgs) {                            // one poll, demuxed to its partitions
    for (p, part) in msgs.by_partition() {
        partitions[p].accept(part, &mut acc)
    }
    release()
}

fn apply(result) {                           // one request result, distributed
    for group in result.groups {
        if group.epoch.dead() { continue }   // results for revoked partitions die here
        partitions[group.partition].apply(group, result, &mut acc)
    }
    release()
}

fn release() {                               // the one coordination point with the
    if !acc.is_empty() {                     //   transport: the full buffer moves by
        batcher.send(acc.take())             //   value; a fresh one replaces it
    }
}

fn next_deadline() -> Deadline { sweep_at }

fn wake(now) {                               // the stall sweep — the domain's only clock;
    if now < sweep_at { return }             //   it releases nothing, so no release()
    for p in partitions { p.check_stall() }
    sweep_at = now + SWEEP_INTERVAL;
}
```

**Partition driver — demux, the offset ledger, and acting on results.** A plain struct owned by its partition manager, mutated under `&mut`.

```rust
// Loop-owned (via the partition manager); methods are synchronous and never block.
struct PartitionDriver {
    keys: Map<RoutingKey, KeyDriver>,
    ledger: OffsetLedger,                    // pending offsets (+sizes) · completed · frontier
    stall_deadline: Deadline,
}

fn accept(msgs, acc) {                       // one poll's messages for this partition
    ledger.add_pending(msgs);
    for (key, group) in msgs.by_routing_key() {    // offset order preserved; groups
        if let Some(r) = keys.entry(key).or_create().enqueue(group) {
            acc.push(r)                            //   stamped: affinity = partition, epoch
        }
    }
}

fn apply(group, result, acc) {               // one group of one resolved request
    let released = match result.outcome {
        Ack => {
            ledger.complete(group.offsets);
            if ledger.advance_frontier() {   // highest contiguous completed offset
                stall_deadline = now + STALL_TIMEOUT;
            }
            keys[group.key].acked(result.worker)   // learn the pin, release the next group
        }
        Failure => keys[group.key].failed(group)   // back to queue head, re-released in
    };                                             //   this same cascade (§4.5)
    if let Some(r) = released { acc.push(r) }
}

fn check_stall() {
    if ledger.has_pending() && now > stall_deadline {
        fail_process()                       // replay ≤ B; this partition's wedge only (§4.5)
    }
}
```

**Commit manager — frontiers to one batched commit.** The §2.3 verification rides here unchanged.

```rust
// The consumer loop's `commits` field; owns its own cadence deadline — wake(now)
// runs tick() when due. tick() is synchronous and never blocks the loop.
fn next_deadline() -> Deadline { next_tick }
fn wake(now) { if now >= next_tick { tick(); next_tick = now + COMMIT_INTERVAL } }

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

**Key driver — a passive state machine.** The deferral cascade and the pin are this struct — a plain entry in its partition driver's map: no task, no lock, no ref-count, no timer. It hands releases up as return values; it calls nothing.

```rust
// A plain entry in its partition driver's map. No task, no lock, no ref-count — and
// no clock: retry pacing lives in the transport (§2.9, §4.5).
struct KeyDriver {
    queue: FifoQueue<Group>,
    in_flight: bool,                         // at most one release out at a time
    worker: Option<WorkerId>,                // the sticky pin — learned from ACK results
}

fn enqueue(group) -> Option<Release> {
    queue.push_back(group);
    try_release()
}

fn try_release() -> Option<Release> {        // on enqueue, after ACK, after a failure
    if in_flight || queue.is_empty() { return None }
    in_flight = true;
    Some(Release { group: queue.pop_front(), sticky: worker })
}                                            // placement is the batcher's — the pin is a
                                             //   preference; safe: nothing of ours in flight

fn acked(worker) -> Option<Release> {
    self.worker = worker;                    // stickiness for the next release
    in_flight = false;
    try_release()                            // then maybe_evict when idle and empty —
}                                            //   the pin dies with the driver

fn failed(group) -> Option<Release> {
    queue.push_front(group);                 // back to head — the key's queue *is* the order
    in_flight = false;
    worker = None;                           // let placement re-pick against current health
    try_release()                            // re-place now: transient faults were already
}                                            //   backed off below the model (§2.9), and an
                                             //   unroutable pool parks in the batcher (§4.5)
```

**Worker batcher — the transport side, whole, one task.** Placement, bins, parked, packing, and the stream runners, behind two channels: accumulators in, request results out. It never calls a driver; nothing inside it is reachable from outside.

```rust
// One long-lived task. Sole owner of everything transport-shaped; mutation is plain
// &mut, and its select! is its only await point.
struct WorkerBatcher {
    bins: Map<WorkerId, Bin>,                // bin: ordered groups, events/bytes, affinities
    busy: Map<WorkerId, bool>,               // stream state — set on fire, cleared on the
    touched: Set<WorkerId>,                  //   resolution; streams this wake binned into
    parked: Vec<Release>,                    // pool-wide unroutable (§4.5); re-placed on
    retry_at: Option<Deadline>,              //   every wake — this deadline is the backstop
    router: Router,                          // aperture + P2C over the health snapshot (§4.3)
    accumulators: Rx<Accumulator>,           // from the partition manager: one per cascade
    resolutions: Rx<Resolution>,             // from the runners
    results: Tx<RequestResult>,              // to the loop's result stream
    requests: Map<WorkerId, Tx<Request>>,    // send side per runner, capacity 1
    resolutions_tx: Tx<Resolution>,          // cloned into each runner at spawn
}

task worker_batcher {
    loop {
        select! {
            acc = accumulators.recv() => {   // one cascade's releases, whole
                revive_parked();             // health may have changed since they parked
                for release in acc { place(release) }
                fire_touched()
            }

            (w, outcome, groups) = resolutions.recv() => {
                busy[w] = false;             // the depth-1 slot is free again
                results.send(RequestResult { worker: w, outcome, groups });
                try_fire(w)                  // refill from the bin at once — this result's
            }                                //   successors ride a later accumulator

            _ = sleep_until(retry_at) => {   // armed only while something is parked:
                revive_parked();             //   the transport's one clock (§4.5)
                fire_touched()
            }
        }
    }
}

fn place(release) {
    match router.place(release.sticky, &bins) {      // §4.3: sticky honored unless
        None    => park(release),                    //   draining/dead/overloaded
        Some(w) => {
            bins[w].push(release.group);     // ≤1 group per key per bin: key drivers
            touched.insert(w);               //   release one at a time
            if bins[w].size >= T { try_fire(w) }     // target cap: fire mid-batch
        }
    }
}

fn park(release) { parked.push(release); retry_at.arm_if_unarmed(PARK_RETRY) }

fn revive_parked() {                         // re-place against current health; the
    retry_at = None;                         //   still-unplaceable simply park again
    for release in parked.take() { place(release) }
}

fn fire_touched() {
    for w in touched.drain() { try_fire(w) } // one request per worker per wake,
}                                            //   zero added latency

fn on_worker_discovered(w) {                 // from registry discovery; a reaped worker's
    let (tx, rx) = channel(capacity: 1);     //   runner and channel are torn down with it
    requests.insert(w, tx);
    spawn(stream_runner(w, rx, resolutions_tx.clone()));
}

fn try_fire(w) {                             // the single send-origination site
    if busy[w] || bins[w].is_empty() { return }
    let request = pack(bins[w]);             // §4.3: take ≤ T, minimize distinct affinities,
                                             //   oldest-head-first; remainder stays binned
    requests[w].try_send(request).unwrap();  // non-blocking; capacity 1, provably never full:
    busy[w] = true;                          //   sends happen only while !busy, and busy
}                                            //   clears only on this request's resolution
```

**Result stream — the transport's outlet.** The batcher forwards each resolution the moment it arrives; the loop hands it to the partition manager.

```rust
// Loop-owned receive half. Everything a resolved request carried, with its outcome —
// nothing else escapes the transport side.
struct ResultStream {
    results: Rx<RequestResult>,              // forwarded by the batcher, one per resolution
}

async fn next() -> RequestResult { results.recv().await }
```

**Router placement** (§4.3) — inside the batcher; `sticky` is the release's preference, not a constraint:

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
    // none healthy → None: the release parks; the batcher's next wake re-tries (§4.5)
}
```

**Worker stream runner — one task per worker, depth 1.** The machinery below the batcher, which hands it both channel ends at spawn.

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
            resolutions.send(w, classify(outcome), request.take_groups());  // never blocks
        }
        // stream break: the in-hand request (if any) reports Failure the same way — one
        // request's groups, handed back whole; no successor ledger, no fence
    }
}

fn classify(outcome) {                       // the transport classifier, §2.9 unchanged
    match outcome {
        Ack          => Ack,
        Busy | 503   => Backpressure,        // long jittered backoff; excluded from
                                             //   passive health
        Fault        => Failure,             // counts against passive health, after the
                                             //   below-model retries; groups come home whole
        Oversize413  => split_halve_resend() // §2.10 defense below the model — rare
    }                                        //   once T is under the worker body limit
}
```

What is *not* here is the point: no stash, no batch-sequence bookkeeping, no fences or `FenceGuard`, no eager reconciliation, no completion serialization, no per-key timers (the clocks: the stall sweep, the commit cadence, and the batcher's park-retry while anything is parked) — and no locks: today's `PinTable` mutex and its lock-ordering discipline have no successor, because nothing is shared to lock. The order argument is visible as four structural facts — one origination site (`try_fire`), at most one released group per key anywhere in the system, capacity-1 request channels, and two tasks that each finish one cascade before taking the next event. And the coupling argument is a fifth: the sides exchange only accumulators down and request results up, plain values on FIFO channels — so neither side can observe, or corrupt, the other mid-transition, and the transport has no path to a driver even to misuse.

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
| Completion-time flush (2.6) | Retired; commit gate → ledger, retry pacing → transport backoff + parked releases, watchdog → per-partition stall sweep |
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

1. **Target-sized worker batches** — the batcher's `T` and packing rules (§4.3) *are* stage 1 of the plan, with the fan-out clamp formula replaced by emergence and the pins-as-preferences packing expressed structurally.
2. **Demand-proportional concurrency** — the plan's controller (fill-EWMA → slots, duration budget, shed policy) is subsumed by `B` + self-clocking (§4.4). The behaviors the controller had to *steer toward* — MIN concurrency when drained, MAX under backlog, held pressure during worker saturation, bounded replay window, walk-down during a wedge (per-partition stalls now localize it) — are the only behaviors the structure permits. No EWMA, no tick, no shed policy, nothing to mis-tune.
3. **One-signal worker HPA** (the elastic plan's "processor HPA") — unchanged from the plan (`ingestion_api_event_seconds_in_flight_total`, time-weighted in-flight events per pod), and *strengthened*: every request is target-normalized, so in-flight work per worker is an honest, comparable unit.

The two scaling regimes the plan demands fall out of the poll gate:

- **Workers fast, backlog draining**: the gate stays open, the consumer is CPU-bound (demux, packing, encode), its CPU-only HPA is truthful — pods scale when the consumer is the bottleneck, and only then.
- **Workers slow / pool undersized**: uncommitted work fills `B`, polling pauses at low CPU (the consumer fleet correctly *doesn't* scale), and B/T requests held in flight drive the worker pool out. The transport's jittered backoff bounds futile traffic; a 503'd request never counts as worker occupancy, so the scale-out signal can't be starved — same reasoning as the plan's "no congestion input" argument, unchanged.

## 7. Open questions

1. **Build order.** The elastic plan's stages 1–2 can land on the current architecture (they're specced that way); the driver model delivers the same behavior by structure. Options: (a) elastic stages on the current code first, redesign later — two migrations, faster relief; (b) build the driver model and ship the elastic behavior with it — one migration, longer lead. The controller-free shape argues for (b) if the incident pressure allows; the stage 1 packing changes are the piece most worth doing early either way, since the packer carries over almost verbatim.
2. **Stream pipelining depth** — start at 1; revisit only if ACK round-trip caps a stream's throughput below what one worker can absorb.
3. **Partition fairness at the poll gate** — one global `B` lets a deep partition monopolize the budget. Levers, in escalation order: none (watch it), rdkafka per-partition pause/resume, isolating hot partitions on dedicated pods at the assignment level. Don't build until observed.
4. **Shard count** — single-shard until loop occupancy says otherwise (§4.6).
5. **`B` and `T` defaults** — `T` from the per-request-cost knee (the elastic plan's stage 1 calibration, unchanged); `B` from the acceptable replay window and the memory contract, with the plan's ~"MAX × batch" residual exposure as the anchor.

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
| `affinity` | the batcher's composition hint (today: the partition id) | cohort |
| `bin` | the batcher's per-stream buffer of placed groups | the accumulator |
| `resolve` | a send finished, success or failure | settle |
| `eager-flush task` | the ACK-speed drain task (`run_eager_flush_loop`) | sidecar |
| `window` | always qualified: in-flight, passive, stall, replay window | bare "the window" |
| `driver` | the single owner of one unit's state, advanced only by events | — |
| `consumer loop` | the event pump at the top: results, polls, deadlines, rebalance | consumer *driver* — it owns no unit's state |
| `partition manager` | the domain side's root: assignment lifecycle + work distribution + the accumulator | — |
| `release` | one group handed to the batcher, with its placement preference | the ship-a-version sense |
| `request result` | one resolved request, whole: groups + outcome + worker | resolution, outside the transport side |
| `worker batcher` | the transport-side task: placement, bins, parked, streams | — |
| `accumulator` | one cascade's releases, filled under `&mut`, released to the batcher | — |
| `result stream` | the transport's outlet: resolved requests, drained by the loop | — |
| `parked` | a release held in the batcher while no worker can take it (§4.5) | — |

### 8.2 Why these words are reserved

- **`lane`** is claimed three times over: capture's `Lane { Main, Overflow, Historical }` routing enum (plus the AI lane's topics), the Node deployment lanes (`INGESTION_LANE`, one namespace per lane, the `ingestion_lane` Prometheus label), and this binary stamps that label on every metric it emits. Drafts of #85238 called the gRPC construct a lane; the merged code says `WorkerStream`, and this doc follows the code.
- **`worker`, not `processor`**: every artifact of the downstream fleet says worker — the proto package `ingestion.worker.v1`, `INGESTION_WORKER_CONCURRENT_BATCHES`, `rust/ingestion-worker-proto`, the `worker` metric label. "Processor" is the elastic-dispatch plan's word for the same fleet (kept there, mapped in §6); in code, `*Processor` already means an in-process pipeline stage in both Rust and Node. One fleet, one name.
- **`group`, not `chunk`**, for the per-key unit: this crate's `MessageGroup`/`DeferredGroup` and the Node framework's `concurrentlyPerGroup(getTokenAndDistinctId, …)` are the same concept with the same key on both ends of the wire. `chunk` is doubly taken: the transport's 413 split (kept by §5), and the Node framework's per-stage unit (`ChunkPipeline`, whose docs explicitly contrast chunks with batches). The price is that the Kafka sense must always be written "consumer group".
- **`cohort` → `affinity`**: cohort is a core product noun (user cohorts, the cohorts API, five `rust/cohort-*` crates). The hint is the partition id used as a packing preference; affinity says exactly that.
- **`fence`** stays only because the merged worker-stream code uses it in the same sense personhog does — a barrier that stops the old flow before new work may start. Partition→pod placement (§7.3) is *isolation*, not fencing.
- **`frontier` vs `watermark`**: the code already uses watermark for the per-key ACK point (order sentinel); the per-partition commit point gets its own word instead of overloading it. Earlier drafts used the two interchangeably.
- **`worker batcher` and `accumulator`**: earlier drafts split the transport into a loop-owned "sender" behind a sink trait; the accumulator hand-off (§4.1) retired both names — the batcher is whole again, and the domain's outbound face is data, not an interface. A channel's ends are `Tx`/`Rx` ("send side"/"receive side") in code and prose, so "sender" stays free of meaning. The `bin` (the batcher's per-stream buffer) and the `accumulator` (the domain's per-cascade buffer) are deliberately distinct words for distinct waiting rooms.

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
