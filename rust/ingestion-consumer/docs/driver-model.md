# Driver-model redesign

Status: **draft, for discussion** — nothing here is implemented.

This doc proposes a restructuring of the ingestion consumer around components shaped like its invariants (partitions and routing keys) instead of around the Kafka batch. It is written against the code as of the gRPC-lanes work (#85238); the mechanisms it discusses are those in `consumer.rs`, `dispatcher.rs`, `stash.rs`, `transport.rs`, and `grpc_transport.rs`. It is a companion to the elastic-dispatch plan (target-sized worker batches, demand-proportional concurrency, one-signal processor autoscaling): the redesign is the shape in which those goals stop needing a controller at all.

The argument, in one paragraph: the consumer enforces two invariants — per-key send order and per-partition contiguous commits — but its unit of everything (ownership, completion, commit, flush pacing, concurrency) is the Kafka batch, which appears in neither invariant. Bridging that mismatch is what the stash, the deferral rules, the eager-flush ledgers, the lane fences, and the oldest-first completion serialization are for. Re-founding the consumer on partition- and key-shaped components makes most of that machinery either disappear or shrink to a local rule, and yields the elastic-dispatch scaling behavior as a side effect of the structure rather than as a feedback loop bolted on top.

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
| 2.8 | gRPC lanes, ledger, fences | feed order on the wire; failure atomicity |
| 2.9 | Transport retry / 503 handling | transient faults vs deliberate backpressure |
| 2.10 | Body splitting + 413 handling | worker body limits without reordering |
| 2.11 | Worker registry | health, drains, dead workers, discovery |
| 2.12 | Routing strategies + aperture | worker spread, herd resistance, consolidation |
| 2.13 | Key-order sentinel | verifying what the design can't make impossible |

### 2.1 Batch collection and the in-flight window

The loop collects up to `CONSUMER_BATCH_SIZE` messages (or `CONSUMER_BATCH_SIZE_KB`, or `CONSUMER_BATCH_TIMEOUT_MS`) into a batch, and runs at most `CONSUMER_MAX_BACKGROUND_TASKS` batches concurrently. The window bounds uncommitted work — the crash-replay exposure — and is the *only* source of dispatch concurrency.

**Cost:** concurrency is a fixed constant. Per-pod throughput is capped at `slots × batch / round-trip` regardless of backlog depth, and the consumer spends its wall time awaiting ACKs at low CPU — which blinds a CPU-based HPA and starves the processor pool's in-flight-based HPA at the same time : a deep backlog can sit for hours with both autoscalers reading "idle", until an operator raises `minPods` by hand. The batch is also the unit of *ownership*: every downstream mechanism (stash entries, flush loops, eager ledgers) is keyed by which batch a message arrived in, a fact neither invariant cares about.

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

When a key can't be sent — pinned to a draining/dead worker, or the whole pool unroutable — its group is *stashed* rather than re-routed, because its earlier messages are still in flight and re-routing would reorder the key. Critically, once a key defers once, **every newer group for it must also defer** (the cascade rule), or it would race ahead of the stashed ones. The stash orders a key's entries by batch *sequence* (registered on the consumer loop, because deferrals can arrive out of batch order), keeps per-batch live counts (so batches can complete), and per-key outstanding counts (which stay elevated from `defer` until the flushed group actually *lands*, closing the window where a flushed-but-unACKed group could be raced).

**Cost:** the stash is a second queue system living beside the primary send path, with its own ordering key (batch sequence), its own occupancy accounting, and subtle state ("outstanding" ≠ "physically stashed"). All of it is per-key queueing — expressed batch-scoped.

### 2.6 Completion-time flush

`flush_deferred` runs inline in `complete_oldest_batch`: re-route and send the completing batch's stashed groups, serialized oldest-batch-first (which is what preserves a key's cross-batch order), pacing retries at 200 ms when nothing is routable, and failing the process — replay from uncommitted offsets — when no progress happens for `CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS`. It is simultaneously the stash's drain path, the batch's commit gate, and the stall watchdog.

**Cost:** the drain is paced by batch completion and runs *on the consumer loop*. A continuously-sending hot key drains one group per completion while every collection adds one — it never exits deferral — and every batch's completion carries the flush round-trips inline, taxing all traffic.

### 2.7 Eager deferred flush

`DISPATCHER_EAGER_DEFERRED_FLUSH` (default off) attacks 2.6's pacing problem: the moment the send blocking a key resolves (pin ref-count zero, stash non-empty, send succeeded), the dispatcher pops the key's *oldest* stashed group, re-routes it, and hands it to a sidecar task to send. Each ACK releases the next group — the chain drains at ACK round-trip speed instead of completion speed, which is what lets a hot key actually catch up and exit deferral.

**Cost:** a second drain path over the same stash, reconciled with the first through dedicated glue: `eager_pending` (batches can't commit with eager sends in flight), `eager_accepted` / `take_eager_accepted` (acceptances credited across paths), stall-deadline resets on eager progress, and `send_failed` suppression so a flapping worker doesn't tight-loop between the paths. Every subtle interaction in the dispatcher today lives at this seam. The eager path is the *correct* drain model — the completion path is what forces it to be an add-on rather than the design.

### 2.8 gRPC lanes, the ledger, and fences (#85238)

One ordered stream per worker: enqueue order is send order is the worker's feed order — the per-key guarantee concurrent HTTP requests can't give, which is why `begin_send` must be called synchronously where send order is decided (the consumer loop, the serialized flush paths, the eager loop's receive-order). The lane's ledger resolves ACKs only as a consecutive prefix (a later send must not release its keys while an earlier one can still fail), and a failure **fences the whole lane**: every queued and un-ACKed item is resolved in order with its messages handed back, and each carries a `FenceGuard` — the lane refuses new work until every guard is dropped, closing the race where the consumer loop could enqueue a fenced key's next group before the failure finished re-stashing.

**Cost:** the fence machinery exists because send *origination is distributed*: scatter tasks, two flush paths, and the eager sidecar all enqueue concurrently, so the lane cannot know when a failure's cleanup is complete except by explicit guard hand-off. The ledger's resolve-in-send-order rule exists because many sends ride the stream concurrently on behalf of batch-scoped callers.

### 2.9 Transport retry and 503 handling

The transport distinguishes deliberate backpressure from faults: HTTP 503 (`WorkerBusy`) and lane-busy get a longer, jittered backoff (250 ms·2ⁿ capped at 5 s + jitter, vs 100 ms·2ⁿ for errors) and are **excluded from passive health** (`is_backpressure`), so a worker at capacity is throttled but not marked sick. 4xx is non-retriable; retries mark `replay` so worker-side sentinels count repeats correctly; per-worker semaphores softly cap in-flight requests to match the worker's `concurrentBatches`.

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
2. **Two drain paths over one stash, plus reconciliation glue.** The eager path (2.7) is the right model; the completion path (2.6) is the incumbent it must coexist with. The ledgers, credits, and suppression rules exist only because there are two.
3. **Ordering by discipline, not by structure.** Per-key order holds because `begin_send` is called in the right places in the right order across four call sites on three tasks. The lane fences (2.8) are the cost of distributed origination; the sentinels (2.3, 2.13) are the audit of it.
4. **Concurrency and request size are constants and accidents.** The slot count can't respond to backlog (the autoscaling blindness), and request size is whatever division produces (the fan-out inversion).

## 4. The driver model

### 4.1 Components

```text
consumer driver                 (1 per pod)
  ├── partition driver          (1 per assigned partition)
  │     └── key driver          (1 per active routing key, passive)
  └── worker batcher            (1 per pod; bins per worker lane)

shared services: worker registry · router/aperture · transport lanes
```

The hierarchy follows containment in the *data*: a partition contains key streams; a key stream is consumed in **chunks** (one poll's messages for one key — today's "group"). The Kafka batch is demoted to an input format: it exists during collection and **dissolves at demux**. Nothing downstream tracks it.

- **Consumer driver** — polls rdkafka, demultiplexes messages to partition drivers, applies backpressure (§4.4), owns rebalance lifecycle: partition assigned ⇒ create a partition driver; revoked ⇒ tear it down wholesale, with its key drivers and pending state. The rebalance unit and the component unit coincide.
- **Partition driver** — splits its messages by routing key into chunks and hands them to key drivers; owns the **offset ledger**: the set of pending offsets and the highest contiguous completed offset (the watermark), which is what gets committed, on a cadence. Contiguity becomes *constructive* — the ledger computes exactly the committable frontier — instead of a property to verify after the fact.
- **Key driver** — a passive state machine (a struct in a map, not a task; key cardinality is unbounded): a FIFO of chunks, **at most one chunk released at a time** (buffered in a lane or in flight), the rest queued behind it. On ACK: report offsets to the partition ledger, release the next chunk. On failure: take the chunk back, arm a backoff timer, re-route on expiry per current worker health. Created on first chunk, evicted when idle and empty. Holds the sticky-pin identity (its current worker).
- **Worker batcher** — per-worker bins that coalesce released chunks into target-sized requests and fan resolutions back out to the contributing key drivers. Placement and composition rules in §4.3.

### 4.2 One event loop, synchronous cascades

All state transitions run on a single event loop (sharding noted in §4.6) driven by three event sources:

1. **Poll delivered** — demux to partition drivers → key drivers enqueue → released chunks land in lane bins → flush every *idle* lane touched this cycle.
2. **Send resolved** — settle the request's chunks: ACK ⇒ ledger updates, key drivers advance, next chunks land in bins; failure ⇒ chunks return to their key drivers, backoff timers arm. Then refill the lane if its bin is non-empty.
3. **Timer fired** — key-driver backoff expiry (re-route and re-release), gather-timer expiry (fire an undersized bin), commit cadence.

The only spawned tasks are the sends themselves: encode, transmit, await, post a `SendResolved` event back. Because every enqueue and every failure cleanup runs to completion on one thread, **ordering is a property of the structure**: nothing can slip a newer chunk past a failure being processed, which is exactly the race the lane fences exist to close today. Send origination has one call site instead of four.

### 4.3 The batcher: packing, placement, composition

**Trigger conditions** (no linger timer in the common path):

- *Idle lane, end of demux cycle*: fire the accumulated bin as one request. Coalescing comes from the synchronous demux of a whole poll — this reproduces today's one-sub-batch-per-worker-per-batch behavior with zero added latency.
- *Busy lane, on resolution*: chunks accumulate while a request is in flight; when it resolves, fire what accumulated. Adaptive batching: fast workers get small low-latency requests, slow workers automatically get fuller ones instead of deeper queues. This *is* the eager chain, generalized from one key to the lane.
- *Target cap `TARGET_WORKER_BATCH_EVENTS` / `_KB`*: a bin at target fires immediately; an over-target bin splits into consecutive requests.
- *Gather timer*: bounds latency for undersized bins at low traffic. Set well under end-to-end latency budgets; the one timer the trigger design needs.

**Placement** (which worker a chunk's key uses): pins are placement *constraints* — a pinned key's chunk must go to its worker, and its volume counts toward that bin's fill. Fresh keys fill open, in-slice, below-target bins first (load-checked), then rotating P2C opens further slice workers. Fan-out is **emergent**: demand ÷ target, clamped below by the aperture coverage floor, with slice coverage achieved over seconds by rotation rather than within every batch. The elastic-dispatch fan-out formula stops being a formula.

**Composition** (which chunks ride together): each chunk carries an opaque **cohort** hint — stamped by the consumer driver with the partition id, but the batcher knows only the preference rule: *minimize distinct cohorts per request, choosing cohorts oldest-head-first*. A lane's bin holds at most one chunk per key (key drivers release one at a time), and cross-key order is unconstrained, so composition is free to group. Cohort-pure requests mean a failed request wounds one partition's frontier, not eight (blast radius), and a slow request delays few watermarks (frontier coupling). Oldest-first keeps the grouping strictly latency-safe. Hint-affinity also acts as a placement *tie-break* among otherwise-equivalent bins — never overriding load or fill, so a hot partition cannot become a hot worker.

**Lane depth: 1.** One un-ACKed request per lane. The stream still provides ordered delivery; depth 1 means a failure's cleanup involves exactly one request's chunks, no ledger of un-ACKed successors, no fence. Pipelining depth becomes a tunable only if ACK round-trip proves to be the ceiling.

### 4.4 Two constants instead of a controller

- **`T`** — target request size (events and KB, whichever binds), at the batcher. Chosen from the knee where per-request fixed cost stops mattering; sized under the worker body limit so §2.10's splitting becomes a rarely-hit defense instead of a routine repair.
- **`B`** — the uncommitted-work budget (events and bytes), at the consumer driver: **poll only while total uncommitted work < B.**

Concurrency then self-clocks. Fast workers: ACKs return quickly, watermarks advance, uncommitted stays low, the poll gate never closes — throughput is CPU-limited and consumer CPU is a truthful autoscaling signal. Slow workers or backlog: uncommitted fills to B, polling pauses, up to ~B/T target-sized requests sit in flight at the workers — which is the processor HPA's signal, now denominated in a meaningful unit because every request is target-normalized. The elastic-dispatch controller (EWMA smoothing, ±1/tick slot stepping, the batch-duration budget) existed to steer batch slots toward exactly this behavior; with B and T it is the only behavior the structure can produce.

`B` is also the **crash-replay window, enforced directly**. The elastic plan bounded replay through a duration budget because Little's law was the only handle batch slots offered; here the bound is the number itself. The memory provisioning contract becomes literal — `baseline + librdkafka caps + B_bytes + headroom`, verified at boot — with no ×2 estimation.

### 4.5 Failure handling in the new shape

- **503 / lane busy**: unchanged — the transport's jittered backoff absorbs deliberate backpressure below the model, excluded from passive health.
- **Send failure (fault)**: the resolution event synchronously returns the request's chunks to their key drivers; each holds its chunk at queue head, arms backoff, re-routes on expiry against current health. This replaces `defer_failed` + re-stash + both flush paths' retry pacing with one local rule. The order argument is trivial: the key's queue *is* the order, and nothing for that key was in flight behind the failure (depth-1 lanes, one-release key drivers).
- **Draining/dead worker**: the registry is unchanged; the *consequence* becomes local. A key pinned to a drainer simply doesn't release until its in-flight resolves, then re-routes at its next release. The cascade rule is the queue: newer chunks are behind older ones by construction. No stash, no batch-sequence bookkeeping, no outstanding-count subtlety.
- **Unroutable pool**: key drivers hold, backoff timers re-check; the partition watermarks stall; the watchdog below bounds it.
- **Stall watchdog**: per-partition — a watermark stuck for the timeout while work is pending fails the process, replaying that exposure (≤ B). Today's `deferred_flush_timeout` semantics, at the granularity where a wedge actually lives. A wedged key stalls *its partition's* frontier while healthy partitions keep committing — today it stalls every partition on the pod.
- **Rebalance**: revoke tears down the partition driver; in-flight requests containing its chunks resolve and are discarded against the dead ledger; the assignment-epoch stamp (from #85238) keeps worker-side sentinels re-baselined. No batch-scoped state cuts across the revocation.

### 4.6 CPU concurrency

The event loop stays pure bookkeeping; CPU parallelism lives in two places. **Leaves:** encode/compress on the send tasks, which already ride the multi-threaded runtime. **Shards:** partition is the natural sharding unit — both invariants are per-partition — so the loop can be sharded by partition (lanes then per shard×worker; registry load read as snapshots) with no cross-shard ordering concerns. Ship single-shard with the boundary designed in (no shared mutable state between partition drivers), instrument loop occupancy the way `assign_duration_seconds` is watched today, and shard only when the metric says the loop is the ceiling. Fleet-level parallelism remains partition assignment across pods.

## 5. Construct-by-construct disposition

| Today | In the driver model |
|-------|---------------------|
| Batch collection | Unchanged as input format; batch dissolves at demux |
| In-flight batch window (2.1) | Retired; replaced by budget `B` (poll gate) |
| Oldest-first completion (2.2) | Retired; per-partition watermark ledger commits the contiguous frontier |
| Commit sentinel (2.3) | Kept as a cheap assert; contiguity is now constructed, not emergent |
| Commit monitor (2.3) | Kept as-is (librdkafka async-commit blindness is unchanged) |
| Sticky pins (2.4) | The key driver's current-worker field; eviction = driver eviction |
| Stash + cascade rule (2.5) | The key driver's FIFO; the cascade is the queue |
| Completion-time flush (2.6) | Retired; commit gate → ledger, retry pacing → per-key backoff timers, watchdog → per-partition stall deadline |
| Eager flush + ledgers (2.7) | Becomes the *only* drain mechanism (resolution cascade + lane refill); `eager_pending`/`eager_accepted`/`take_eager_accepted` deleted |
| Lane ledger + fences (2.8) | Depth-1 lanes + single-threaded origination; ordered stream kept, fences and consecutive-prefix resolution deleted |
| 503/backoff/backpressure classification (2.9) | Unchanged |
| Body split + 413 (2.10) | Kept as defense; `T` makes routine splitting stop happening |
| Worker registry (2.11) | Unchanged; drain consequences become key-driver-local |
| Aperture + P2C (2.12) | Kept for placement; fan-out formula retired (emergent from demand ÷ `T`); `STICKY_PIN_LOAD_SLACK` re-derived against `T` |
| Key-order sentinel (2.13) | Kept as a cheap assert; order is now structural (one origination site, one-release key drivers, depth-1 lanes) |
| Debug recorder | Kept; event points move to the drivers (arguably richer: per-key and per-partition state is now first-class) |

The through-line: the mechanisms that survive are the ones facing the outside world (transport classification, registry, discovery, sentinels-as-audit). The mechanisms that dissolve are the ones that bridged batch-shaped machinery to key/partition-shaped invariants.

## 6. How this drives the autoscaling plan

The elastic-dispatch plan's three changes map onto the model as follows:

1. **Target-sized worker batches** — the batcher's `T` and packing rules (§4.3) *are* stage 1 of the plan, with the fan-out clamp formula replaced by emergence and the pins-as-constraints packing expressed structurally.
2. **Demand-proportional concurrency** — the plan's controller (fill-EWMA → slots, duration budget, shed policy) is subsumed by `B` + self-clocking (§4.4). The behaviors the controller had to *steer toward* — MIN concurrency when drained, MAX under backlog, held pressure during worker saturation, bounded replay window, walk-down during a wedge (per-partition stalls now localize it) — are the only behaviors the structure permits. No EWMA, no tick, no shed policy, nothing to mis-tune.
3. **One-signal processor HPA** — unchanged from the plan (`ingestion_api_batch_seconds_in_flight_total`, time-weighted concurrent batches per pod), and *strengthened*: every request is target-normalized, so "concurrent batches" is an honest unit of held work.

The two scaling regimes the plan demands fall out of the poll gate:

- **Workers fast, backlog draining**: the gate stays open, the consumer is CPU-bound (demux, packing, encode), its CPU-only HPA is truthful — pods scale when the consumer is the bottleneck, and only then.
- **Workers slow / pool undersized**: uncommitted work fills `B`, polling pauses at low CPU (the consumer fleet correctly *doesn't* scale), and B/T requests held in flight drive the processor pool out. The transport's jittered backoff bounds futile traffic; a 503'd request never counts as worker occupancy, so the scale-out signal can't be starved — same reasoning as the plan's "no congestion input" argument, unchanged.

## 7. Open questions

1. **Build order.** The elastic plan's stages 1–2 can land on the current architecture (they're specced that way); the driver model delivers the same behavior by structure. Options: (a) elastic stages on the current code first, redesign later — two migrations, faster relief; (b) build the driver model and ship the elastic behavior with it — one migration, longer lead. The controller-free shape argues for (b) if the incident pressure allows; the stage 1 packing changes are the piece most worth doing early either way, since the packer carries over almost verbatim.
2. **Gather timer default** — small enough not to show in end-to-end latency; exact value from lane traffic percentiles.
3. **Lane pipelining depth** — start at 1; revisit only if ACK round-trip caps a lane's throughput below what one worker can absorb.
4. **Partition fairness at the poll gate** — one global `B` lets a deep partition monopolize the budget. Levers, in escalation order: none (watch it), rdkafka per-partition pause/resume, fencing hot partitions to dedicated pods at the assignment level. Don't build until observed.
5. **Shard count** — single-shard until loop occupancy says otherwise (§4.6).
6. **`B` and `T` defaults** — `T` from the per-request-cost knee (the elastic plan's stage 1 calibration, unchanged); `B` from the acceptable replay window and the memory contract, with the plan's ~"MAX × batch" residual exposure as the anchor.
