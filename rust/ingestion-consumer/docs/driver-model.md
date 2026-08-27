# Driver-model redesign

Status: **draft, for discussion** — nothing here is implemented.

This doc proposes a restructuring of the ingestion consumer around components shaped like its invariants (partitions and routing keys) instead of around the Kafka batch. It is written against the code as of the gRPC worker-stream work (#85238, since merged); the mechanisms it discusses are those in `consumer.rs`, `dispatcher.rs`, `stash.rs`, `transport.rs`, and `grpc_transport.rs`. Terms are used as defined in §8 (Nomenclature); the diagnosis (§1.2) and Appendix A keep the names the code has today. It is a companion to the elastic-dispatch plan (target-sized worker batches, demand-proportional concurrency, one-signal worker autoscaling): the redesign is the shape in which those goals stop needing a controller at all.

The argument, in one paragraph: the consumer enforces two invariants — per-key send order and per-partition contiguous commits — but its unit of everything (ownership, completion, commit, flush pacing, concurrency) is the Kafka batch, which appears in neither invariant. Bridging that mismatch is what the stash, the deferral rules, the eager-flush accounting, the worker-stream fences, and the oldest-first completion serialization are for. Re-founding the consumer on partition- and key-shaped components makes most of that machinery either disappear or shrink to a local rule, and yields the elastic-dispatch scaling behavior as a side effect of the structure rather than as a feedback loop bolted on top.

Two proposals in here go beyond restructuring — they change behavior or contract relative to today, and deserve their own review attention. **(1) The ordering contract becomes Kafka's own** (§1.1): the routing key is the message's partition key, opaque to this consumer, and a null key owes no order — capture, not the consumer, decides what is sequenced. **(2) Sticky pins are deleted** (§3.12): placement becomes memoryless, because both of the pin's jobs — per-key order and steady-state consolidation — are carried structurally here, leaving only an unmeasured worker-cache-locality conjecture (§7.6). §2.4 collects these and the other behavior-affecting changes.

The doc reads top-down: the problem (§1), the solution in outline (§2), the design in pseudocode, component by component down the ownership tree (§3), and the argument that the invariants survive (§4). Stop when you hit your depth; each section only sharpens the one before it. The disposition of today's machinery (§5), the autoscaling story (§6), open questions (§7), vocabulary (§8), and the construct-by-construct inventory of today's implementation (Appendix A) close the doc.

## 1. The problem

### 1.1 The two invariants

Everything the consumer does serves two guarantees, plus one delivery contract:

1. **Per-key send order.** For every routing key — the message's Kafka partition key, opaque bytes to this consumer — messages reach workers, and are ACKed, in Kafka offset order: a key's newer messages must never overtake its older ones, across any failure, re-route, or retry. A **null key owes no order at all** — that is Kafka's own contract, and the producer's declaration that the message is free. Sequencing is decided where the key is written: capture chooses partition keys (today `token:distinct_id`; its global rate limiter strips keys to spread hot senders), and this consumer honors the contract without ever parsing identity out of the key — which is what keeps it generic.
2. **Per-partition commit contiguity.** Offsets are committed contiguously and monotonically per partition: an offset is committed only when every offset below it has been accepted by a worker.
3. **At-least-once.** Nothing is committed until accepted; on a crash, uncommitted offsets replay. Duplication is legal, loss is not.

Every construct in today's implementation (inventoried in Appendix A) exists to uphold these three under some adverse condition (worker death, drains, 503s, oversized payloads, hot keys, rebalances). The question the redesign asks about each one is: *is this mechanism essential to the invariant, or is it the cost of enforcing a partition/key-shaped invariant through batch-shaped machinery?*

### 1.2 Diagnosis

Today's shape, in brief: the loop collects Kafka batches and runs at most a fixed number of them concurrently; batches complete strictly oldest-first, which is how commit contiguity is enforced; per-key order is kept by sticky pins plus a stash of deferred groups drained by two reconciled flush paths; and one ordered gRPC stream per worker carries sub-batches, fenced whole on failure. Appendix A walks each construct — the problem it solves, the mechanism, and the coupling cost. Four structural findings fall out of that inventory:

1. **The batch is the unit of everything, and no invariant is batch-shaped.** Ownership, completion, commit, stash scoping, flush pacing, and concurrency are all batch-scoped; the invariants are key- and partition-scoped. Every construct in §A.4–A.8 is bridge machinery between those two shapes.
2. **Two drain paths over one stash, plus reconciliation glue.** The eager path (A.7) is the right model; the completion path (A.6) is the incumbent it must coexist with. The cross-path accounting, credits, and suppression rules exist only because there are two.
3. **Ordering by discipline, not by structure.** Per-key order holds because `begin_send` is called in the right places in the right order across four call sites on three tasks. The worker-stream fences (A.8) are the cost of distributed origination; the sentinels (A.3, A.13) are the audit of it.
4. **Concurrency and request size are constants and accidents.** The slot count can't respond to backlog (the autoscaling blindness), and request size is whatever division produces (the fan-out inversion).

## 2. The solution

### 2.1 Components

```text
consumer loop                     (1 per pod; the event pump)
  ├── partition manager           (1 per pod; assignments + the offset ledgers)
  │     └── partition driver      (1 per assigned partition; ledger + stall deadline)
  ├── accumulator factory         (per poll: obtain a buffer, lend it down, release it)
  ├── worker batcher              (1 background task; the transport side, whole)
  │     ├── key table             (every key's send state + its scheduling, sharded)
  │     ├── router/aperture       (placement — §3.12)
  │     ├── packer + size defense (the pacing gate + the pack pass; §A.10 kept below it)
  │     ├── dispatch governor     (permits: the ±1 law over request RTT — §3.11)
  │     └── stream runners        (1 task per worker; depth-bounded ordered send)
  ├── completion stream           (batcher → loop; ACKed groups, for the ledgers)
  ├── commit manager              (1 per pod; frontiers → one batched commit)
  └── budget                      (the B poll gate; charged at poll, refunded at commit)

shared services: worker registry + discovery · transport classifier ·
                 sentinels (asserts) · debug recorder
```

The hierarchy follows the invariants: the domain side is *partition-shaped* — offset ledgers and commit frontiers, the state that rebalances and commits — and the transport side is *key- and worker-shaped* — per-key send queues and per-worker streams, the state that orders and sends. A key's sequence still moves in **groups** (one poll's messages for one key — the code's `MessageGroup`). The Kafka batch is demoted to an input format: it exists during collection and **dissolves at demux**. Nothing downstream tracks it. A *driver* here means exactly one thing: the single owner of one unit's state, advanced only by events.

Below the consumer loop the tree has exactly two sides — the **domain side** (the partition manager and its ledgers) and the **transport side** (the worker batcher and everything under it, with the completion stream as its outlet) — and the seam between them is two channels of plain values: **accumulators** of demuxed groups go down, **completions** (ACKed groups) come back up (§3). The loop carries the buffer across the seam: at each poll it obtains an accumulator from its factory, lends it down the demux (`&mut` — no locking anywhere), and releases it to the batcher when the cascade returns; the release is the hand-off's only coordination. The domain holds no send state — no key queue, no worker id, not even the buffer — and the transport holds no offset ledger; and because the transport runs as its own task, admission and dispatch overlap the loop's next demux.

- **Consumer loop** — polls rdkafka, applies backpressure (§2.3), drains the completion stream, watches assignment events, and hands each of them to the partition manager; a poll tick is three steps — obtain an accumulator, demux into it, release what accumulated. Deliberately not a *driver* — it owns no unit's state (§8). With all send state behind the accumulator hand-off and every firing trigger — the events and the transport's own clocks alike — inside the batcher (§3.8), it is a pure event pump: it owns nothing partition- or worker-shaped, and its one clock is an anonymous housekeeping tick for the two jobs that must run when no events arrive (commits, stall checks).
- **Partition manager** — the domain side's root. Owns the partition drivers and their lifecycle: partition assigned ⇒ create a driver; revoked ⇒ begin the **drain** (§4.5) — the driver stays to absorb the completions still in flight, and is torn down only when the batcher's `Drained` marker arrives, after a final commit. Owns nothing transport-shaped, no per-key state, and no clock of its own — the loop's housekeeping tick drives its stall checks. Distributes work: demuxes each poll to its partition drivers (which push the demuxed groups straight into the lent accumulator), routes each completion's groups back to the ledger that owns them, and discards completions whose assignment epoch is dead. Everything it passes down is a value.
- **Partition driver** — splits its messages by routing key into groups, stamps them (affinity = partition, epoch), and pushes them into the lent accumulator — no gating, no per-key state; owns the **offset ledger**: the set of pending offsets and the highest contiguous completed offset (the **frontier**), which is what gets committed, on a cadence. Contiguity becomes *constructive* — the ledger computes exactly the committable frontier — instead of a property to verify after the fact.
- **Accumulator factory** — the loop's supply of per-poll buffers, and the holder of the batcher's send side. `obtain()` hands the loop a buffer at the start of a poll tick; `release(acc)` sends a non-empty one to the batcher whole, by value — the hand-off's only coordination — and recycles an empty one; `revoked(p)` sends the in-band revoke marker down the same channel, behind every batch that preceded it (§4.5). The domain never sees the factory: it is lent the buffer, never the machinery.
- **Worker batcher** — the transport side, whole, as one background task, and the home of all send ordering. Its **key table** holds one entry per active routing key — a FIFO queue (the key's send order — §A.5's cascade rule, as a structure) and an `outstanding` bit (**exactly one request may carry a key's work at a time** — asserted when the request settles, never assumed) — behind one method per scenario (admit, pop-ready, take, park, settle, begin-drain); nothing outside the table touches a key or its scheduling. There are no sticky pins in this design (§2.4): placement is memoryless. Each received accumulator is *admitted* — every group joins its key's queue; keys with nothing outstanding become ready — and *dispatch* then asks the **packer** (§3.10): `try_pack` on event wakes — the pacing gate — or `force_pack` when a deadline is due. An emitting pass pops ready items, places each via the router, and composes up to one request per free permit (≤ `T`, in whole key-runs — a hot key may fill a whole request from its backlog); everything the pass composes fires at once, so placed-but-unfired work is not a state this design has. Each runner resolution *settles*: every carried key is asserted outstanding, then ACK ⇒ forward the groups up the completion stream and re-ready its remaining queue; failure ⇒ groups back to their queue heads, re-dispatch — the domain never hears of it. A ready key the pool cannot take stays **parked** in its own queue, re-tried on every pass (§4.4) — nothing is ever handed back. Null-key work rides each shard's **keyless lane** (§1.1): order-free filler, no one-outstanding, split at will to top open requests toward target. A **dispatch governor** meters how many requests ride at once — the surviving piece of the elastic-dispatch controller (§3.11): grow while healthy and permit-starved, shed while the request-RTT EWMA sits over its budget, so exposure walks down in a wedge instead of sitting at `B`. On a revoke marker it begins the partition's drain: queued work drops at once, in-flight keys count down at settlement (their failures drop too), and `Drained` goes up the completion stream behind the partition's final completion (§4.5) — the drain lives entirely in that partition's shard of the key table, so a `Drained` marker cannot exist without a `begin_drain`. The packer and the §A.10 size defense sit below it, as do the stream runners: one task per worker — connect, greet with the assignment epoch, transmit, await ACKs, depth-bounded (default 1) — and the transport classifier, §A.9 unchanged (backpressure vs fault vs non-retriable, backpressure excluded from passive health).
- **Completion stream** — the transport's outlet, and nothing more than a channel: the ACKed groups of each resolved request, forwarded the moment the ACK arrives — offsets for the ledgers. Failures never cross it: they are the batcher's to retry. Its only other traffic is the in-band `Drained` marker that ends a partition's drain (§4.5).
- **Commit manager** — the whole commit policy behind four calls: `progress` (every frontier advance, straight from each completion), `tick` (its clock, from the loop's housekeeping tick), and `begin_revoke` / `finish_revoke` for a drain — the final offset issues immediately, since the rebalance is waiting. When and how to issue — delay, batching, thresholds — is this component's algorithm and appears nowhere else; budget refunds return from whichever call issues, keeping B = polled minus committed exact. The §A.3 verification rides inside unchanged: the commit sentinel as a cheap assert, the commit monitor because librdkafka still drops async commit results.
- **Budget** — the `B` accounting (charged at poll, refunded at commit and at revoke teardown). The design has exactly three clocks: the loop's single housekeeping tick — the commit manager's clock and the stall checks, the two jobs that must run even when no events arrive — and the batcher's two, the pacing deadline, armed only while ready work waits on the pacing gate (§3.10), and the park-retry, armed only while an unroutable pool leaves ready keys parked (§4.4). Key states own no deadlines at all: retry pacing and packing pacing are transport-level, so unbounded key cardinality meets no per-key timer anywhere.

### 2.2 Two tasks, synchronous cascades

State transitions split across two single-threaded tasks — the domain's on the consumer loop, the transport's on the worker batcher (sharding noted in §3.14) — each driven by three event sources, each finishing one cascade before taking the next event. The loop's:

1. **Poll delivered** — the loop obtains an accumulator and lends it down with the poll: the partition drivers add the offsets to their ledgers and push the demuxed groups into the buffer. The cascade returns; the loop releases the accumulator to the batcher.
2. **Completion received** — the loop drains one completion (an ACKed request's groups) and hands it to the partition manager: ledgers complete, frontiers advance, and every advance goes straight to the commit manager (`progress`), which issues on its own algorithm. No accumulator here — completions produce no new work for the transport. A `Drained` marker on the same channel ends a partition's drain instead: `finish_revoke`, then unassign (§4.5).
3. **Housekeeping tick** — the loop's one clock: give the commit manager its clock (`tick` — it issues if its own delay is up, refunding the charge of the work it covers) and check the partition drivers' stall deadlines. These jobs exist because they must run when *no* events arrive — commits must land at low traffic to keep the replay window small, and a stall watchdog by definition fires on the absence of progress.

And the batcher's:

1. **Accumulator received** — admit every group to its key state (queue behind outstanding work, or become ready) and report its charge to the packer, then dispatch: `try_pack` — the pacing gate decides whether a pass emits or the accumulation keeps growing (§3.10). A revoke marker on the same channel begins a partition's drain instead (§4.5).
2. **Resolution received** — settle every key the request carried (asserted outstanding; ACK ⇒ forward the completion and re-ready the rest of the queue; failure ⇒ re-queue at head), then dispatch — the freed permit re-runs `try_pack`: a hot key refills at up to a full request from its own backlog.
3. **Deadline due** — the pacing deadline (§3.10) or the park-retry (§4.4): dispatch with `force_pack` — the traded latency is spent, so a pass emits whatever is ready.

The loop's `biased` select is ordered as its own starvation proof: an arm can only starve the arms below it, so the tick (ready at most once per interval) and the rare rebalance events sit on top where nothing can starve them — the stall watchdog has no other trigger — while completions sit above the poll deliberately: drain before taking new work, and self-limiting, since depth-bounded streams cap completions at a stream's depth per worker in flight. The spawned tasks are the batcher and, below it, one worker stream runner per worker — encode, transmit, await the ACK, post the resolution back. Because every structure is owned by exactly one task and each task finishes a cascade before its next event, **ordering is a property of the structure** — §4.1 makes that argument. Send origination has one call site instead of four. And the two sides overlap in time: while the batcher dispatches one poll's groups, the loop is already demuxing the next.

### 2.3 Two constants instead of a controller

- **`T`** — target request size (`TARGET_REQUEST_EVENTS` / `_KB`, whichever binds), at the worker batcher. Chosen from the knee where per-request fixed cost stops mattering; sized under the worker body limit so §A.10's splitting becomes a rarely-hit defense instead of a routine repair.
- **`B`** — the uncommitted-work budget (`CONSUMER_UNCOMMITTED_BUDGET_EVENTS` / `_BYTES`), at the consumer loop: **poll only while total uncommitted work < B.**

Concurrency then self-clocks. Fast workers: ACKs return quickly, frontiers advance, uncommitted stays low, the poll gate never closes — throughput is CPU-limited and consumer CPU is a truthful autoscaling signal. Slow workers or backlog: uncommitted fills to B, polling pauses, up to ~B/T target-sized requests sit in flight at the workers — which is the worker pool's HPA signal, now denominated in a meaningful unit because every request is target-normalized. The elastic-dispatch controller (EWMA smoothing, ±1/tick slot stepping, the batch-duration budget) existed to steer batch slots toward exactly this behavior; with B and T it is the only behavior the structure can produce — except the retreat. Walking exposure down when the pool sickens needs a latency measurement, and that one piece of the controller survives, as the batcher's dispatch governor (§3.11).

### 2.4 What changes in behavior

Most of this doc is restructuring — the same behavior with different owners. Four changes are not, and reviewers should treat each as a proposal in its own right:

1. **The ordering contract becomes Kafka's own** (§1.1). The routing key is the message's Kafka partition key, opaque bytes; a null key owes no order. Today the per-key unit is derived from the event's token and distinct id; under the contract the consumer never parses identity out of the key — sequencing is decided where the key is written, by capture (including its global rate limiter's key-stripping). This is what makes the consumer generic over partition keys.
2. **Sticky pins are deleted** (§3.12). Placement becomes memoryless: both of the pin's jobs are carried structurally — order by one-outstanding-per-key on ordered streams, consolidation by target packing — leaving only an unmeasured worker-cache-locality conjecture, reintroducible entirely inside the router if it ever measures real (§7.6).
3. **The worker-facing unit becomes the target-sized request** (§2.3). Sub-batches — whatever size `batch ÷ fan-out` happened to produce — are replaced by requests packed toward `T`, and fan-out becomes emergent (demand ÷ target) instead of topology-shaped. Worker-side, in-flight work becomes a normalized, comparable unit, which strengthens the autoscaling signal (§6).
4. **Bounded latency is traded for packing** (§3.10). The pacing gate accumulates admitted work until it can fill the free concurrency with target-sized requests, or until `PACK_LATENCY_BUDGET` expires. Today's shape sends on arrival; `PACK_LATENCY_BUDGET = 0` recovers that exactly, which makes the trade an explicit operator knob rather than a behavior change by stealth.

## 3. The design, top-down

Rust-ish pseudocode in §8's vocabulary, ordered down the ownership tree: the loop, the domain side, then the transport side. The concurrency inventory is deliberately small: **one event-loop task** owning every driver by value, **one worker-batcher task** owning everything transport-shaped, **one long-lived stream runner task per worker**, and two read-only background tasks (the commit monitor, the health probes). Four channel families cross task boundaries — plus one shared snapshot — and everything on them moves **by value**:

```text
accumulators  mpsc                      loop → batcher      one send per poll, plus in-band revoke markers —
                                                            the hand-off's only coordination; content ≤ B
resolutions   mpsc, bound ≥ pool size   runners → batcher   send never blocks (≤1 unreported per runner)
requests[w]   mpsc, capacity DEPTH_MAX  batcher → runner w  the depth bound *is* the capacity; try_send
                                                            never fails
completions   mpsc, bound ≥ pool size   batcher → loop      one per ACK, plus in-band Drained markers
                                                            (§4.5); ≤ depth unresolved per worker
health        snapshot (ArcSwap-style)  probes → router     the only cross-task shared read
```

The `accumulators` channel is unbounded in count but self-limiting in content: every group on it is uncommitted work under the `B` gate, and a lagging batcher starves the domain of completions, which closes polling. The domain's outbound face is not an interface at all — it is the accumulator, plain data the loop's factory obtains each poll and the demux fills under `&mut`; the loop's inbound face is the completion stream's receive side, a bare channel end. The values crossing the seam are:

```rust
struct Accumulator(Vec<Group>);              // one poll's demuxed groups, in offset order
                                             //   per key — obtained from the factory, lent
                                             //   down the demux under &mut (no locking),
                                             //   released by the loop whole, by value; a
                                             //   group carries partition (affinity), epoch,
                                             //   offsets — no worker appears anywhere here

struct Completed(Vec<Group>);                // one ACKed request's groups — offsets for
                                             //   the ledgers; failures never cross the
                                             //   seam, they are the batcher's to retry.
                                             //   The same channel carries Drained(p),
                                             //   the drain's in-band end marker (§4.5)
```

There is no `Mutex`, no `Arc`'d mutable state, and no atomic in the model: every struct below is owned by exactly one task and mutated under plain `&mut`, so lock ordering stops being a concept. The loop and the batcher each have exactly one await point (their `select!`s); the runners block only on their own channel and their own socket. The accumulator is exclusively borrowed for the length of the demux and filled by the partition drivers, and the only coordination between the two sides is the release itself: one channel send, after which the loop never touches that buffer again.

### 3.1 Consumer loop — the event pump

Backpressure is the *absence of the poll branch*, not a check inside it. Deliberately not a driver: it owns no unit's state — it checks results, fetches messages, watches assignments, and hands each to the partition manager.

```rust
// The event pump. Owns the domain side, the accumulator factory, and the result
// stream's receive half; mutation is plain &mut, no locks.
struct ConsumerLoop {
    partitions: PartitionManager,            // the domain side: assignments + ledgers
    accumulators: AccumulatorFactory,        // per-poll buffers + the batcher's send side
    completions: Rx<Completed>,              // the completion stream: ACKed groups
    tick: Interval,                          // housekeeping cadence: commits' clock + stalls
    budget: Budget,                          // uncommitted events+bytes — the B gate (§2.3)
    commits: CommitManager,                  // the commit policy, whole: progress / tick /
                                             //   begin_revoke / finish_revoke (§A.3 inside)
    kafka: KafkaConsumer,                    // rdkafka client: poll, commits, rebalance events
}

loop {
    select! {                                // the loop's ONLY await point; arms run to
        biased;                              //   completion. The order IS the starvation
                                             //   proof: a biased arm can only starve arms
                                             //   below it, so the clock and control arms —
                                             //   ready at bounded frequency — sit on top,
                                             //   where nothing can starve them

        _ = tick.next() => {                 // ready once per interval, so harmless first;
            budget.refund(commits.tick(kafka));      //   and the stall watchdog has no
            partitions.check_stalls();       //   other trigger, so it must not sit below
        }                                    //   a hot arm (commits alone would survive —
                                             //   progress also issues)

        ev = kafka.rebalance() => {          // rare, must be prompt; serialized with
            match ev {                       //   every other arm: no teardown race
                Assigned(p) => {
                    partitions.assign(p, epoch)
                }
                Revoked(p) => {              // begin the drain (§4.5): the driver stays —
                    partitions.revoking(p);  //   its ledger must absorb the completions
                    commits.begin_revoke(p); //   still in flight; the in-band marker
                    accumulators.revoked(p)  //   drops the batcher's queued work for p
                }
            }
        }

        up = completions.recv() => match up {        // hot, deliberately above the poll —
            Completed(groups) => {           //   drain before taking new work — and self-
                budget.refund(               //   limiting: ≤1 in flight per worker
                    commits.progress(kafka, partitions.complete(groups)))
            }                                // whether to issue now is commits' call alone
            Drained(p) => {                  // the drain's end (§4.5), riding behind p's
                budget.refund(               //   last completion: one final harvest,
                    commits.finish_revoke(kafka, partitions.drained(p)));
                kafka.unassign(p)            //   issued immediately — and only now is the
            }                                //   partition handed back
        }

        msgs = kafka.recv(), if budget.under_cap() => {
            // the gate is rdkafka pause/resume, not an unpolled consumer: polling must
            // continue for rebalance callbacks and max.poll.interval liveness at B
            let mut acc = accumulators.obtain();
            budget.charge(partitions.accept(msgs, &mut acc));    // the Kafka batch
            accumulators.release(acc);       //   dissolves here; the charge comes back
        }                                    //   from the same ledger that will refund it
    }
}
```

### 3.2 Accumulator factory — obtain, lend, release

The loop-owned pairing of the buffer supply with the batcher's send side; the whole hand-off protocol in two functions.

```rust
// Loop-owned. The domain is lent the buffer, never the factory.
struct AccumulatorFactory {
    batcher: Tx<Feed>,                       // Batch(accumulator) | Revoked(partition)
    spare: Option<Accumulator>,              // an empty buffer kept back for reuse
}

fn obtain() -> Accumulator {
    spare.take().unwrap_or_default()
}

fn release(acc) {                            // the one coordination point with the
    if !acc.is_empty() {                     //   transport: the full buffer moves by
        batcher.send(Batch(acc))             //   value
    } else {
        spare = Some(acc)                    // nothing accumulated: keep the allocation
    }
}

fn revoked(p) {                              // the revoke marker rides the same channel —
    batcher.send(Revoked(p))                 //   in-band: behind every batch that
}                                            //   preceded it (§4.5)
```

### 3.3 Partition manager — assignments and the ledgers

The domain side's root: the only component that maps a group back to the ledger that must record it. The domain is offsets: pending in at demux, completed out at ACK, frontiers harvested at the tick.

```rust
// Loop-owned. Owns every partition driver; nothing transport-shaped, no per-key
// state, and no clock of its own.
struct PartitionManager {
    partitions: Map<Partition, PartitionDriver>,
}

fn assign(p, epoch) {
    partitions.insert(p, PartitionDriver::new(epoch))
}

fn revoking(p) {                             // drain begun (§4.5): the ledger stays to
    partitions[p].revoking = true            //   absorb in-flight completions
}

fn drained(p) -> DrainHarvest {              // the drain's end (§4.5): remove the driver,
    let (frontier, dropped) = partitions.remove(p).drained();    //   take its last word
    DrainHarvest { p, frontier, dropped }
}

fn accept(msgs, acc) -> Charge {             // one poll, demuxed to its partitions;
    msgs.by_partition()                      //   returns the poll's debit for B
        .map(|(p, part)| partitions[p].accept(part, acc))
        .sum()
}

fn complete(completed) -> Vec<Advance> {     // one ACKed request's groups, distributed;
    completed.groups                         //   Advance = (partition, frontier, charge)
        .filter(|g| !g.epoch.dead())         // stragglers after a drain's teardown (§4.5)
        .filter_map(|g| partitions[g.partition].complete(g))     //   die here; mid-drain
}                                                                //   completions land

fn check_stalls() {                          // driven by the loop's housekeeping tick;
    for p in partitions {                    //   produces no releases, so no accumulator
        p.check_stall()
    }
}
```

### 3.4 Partition driver — demux and the offset ledger

A plain struct owned by its partition manager, mutated under `&mut`.

```rust
// Loop-owned (via the partition manager); methods are synchronous and never block.
struct PartitionDriver {
    ledger: OffsetLedger,                    // pending offsets (+sizes) · completed · frontier
    stall_deadline: Deadline,
    revoking: bool,                          // drain in progress (§4.5): completions still
}                                            //   land; the stall check stands down

fn accept(msgs, acc) -> Charge {             // one poll's messages for this partition
    let charge = ledger.add_pending(msgs);
    for group in msgs.by_routing_key() {     // offset order preserved; groups stamped:
        acc.push(group)                      //   affinity = partition, epoch. A null-key
    }                                        //   message is its own free group (§1.1). No
    charge                                   //   gating — order is the batcher's (§3.8)
}

fn complete(group) -> Option<Advance> {      // one ACKed group — the record of what landed
    ledger.complete(group.offsets).map(|(frontier, charge)| {
        stall_deadline = now + STALL_TIMEOUT;
        Advance { partition: group.partition, frontier, charge }
    })
}

fn drained(self) -> (Offset, Charge) {       // consumed at the drain's end (§4.5): the
    (ledger.frontier(), ledger.pending_charge())     //   final frontier to commit, and the
}                                            //   charge the frontier never walked over

fn check_stall() {
    if !revoking && ledger.has_pending() && now > stall_deadline {
        fail_process()                       // replay ≤ B; this partition's wedge only (§4.4)
    }
}
```

### 3.5 Offset ledger — contiguity as a structure

Today the committable point is emergent — oldest-first completion plus the all-accepted check, verified after the fact by the commit sentinel (§A.2–§A.3). Here it is constructed: polls deliver a partition's offsets in order, so the ledger is a dense ring over one contiguous offset range, and every operation is O(1) amortized per message. Completion, by contrast, arrives in **any order** — keys interleave in the partition and resolve independently, so a later request's offsets (say 4, 5, 6) may settle before an earlier one's (1, 2, 3): the late slots go done above the gap and nothing advances; when the earlier work lands, one advance walks over all of it. Only the frontier is ordered; completion never is. The ring's length is the partition's share of uncommitted work, bounded by the `B` gate.

```rust
// Owned by its partition driver; knows offsets and charges, nothing else.
struct OffsetLedger {
    base: Offset,                            // the offset of slots[0] — one past the frontier
    slots: Ring<Slot>,                       // one per delivered offset, in offset order
}

struct Slot {
    done: bool,
    charge: Charge,                          // this message's events+bytes — the budget's
}                                            //   unit: in at poll, back at commit or drain

fn add_pending(msgs) -> Charge {             // in offset order, so appending keeps the
    for m in msgs {                          //   ring dense — no map, no search
        while base + slots.len() < m.offset {        // an offset gap (transaction control
            slots.push_back(Slot { done: true, charge: 0 })      //   records) gets pre-done
        }                                    //   zero-charge filler: the frontier walks
        slots.push_back(Slot { done: false, charge: m.charge })  //   over it like anything
    }                                        //   else, and the index math stays honest
    msgs.charge()                            // the debit for B — measured by the same
}                                            //   slots that later refund it (§8.2)

fn complete(offsets) -> Option<(Offset, Charge)> {
    for o in offsets {                       // a group's offsets are any subset of the
        slots[o - base].done = true          //   ring, completing in ANY order across
    }                                        //   requests: index arithmetic, O(1) each
    let mut charge = Charge::ZERO;           // then pop the done prefix in the same call —
    while slots.front().is_done() {          //   marking and advancing are never separate
        charge += slots.pop_front().charge;  //   steps; what the frontier walked over is
        base += 1;                           //   exactly the newly committable span
    }
    (!charge.is_zero()).then(|| (base - 1, charge))  // None: the front is in flight — this
}                                            //   completion sits done above the gap until
                                             //   the earlier work lands

fn frontier() -> Offset {                    // highest contiguous completed offset (§8)
    base - 1
}

fn has_pending() -> bool {                   // the stall watchdog's predicate
    !slots.is_empty()
}

fn pending_charge() -> Charge {              // the drain's dropped (§4.5): everything the
    slots.map(|s| s.charge).sum()            //   frontier never walked over — including
}                                            //   done work stranded above a gap, which was
                                             //   never refunded and replays like the rest
```

### 3.6 Charge and budget — the accounting as arithmetic

A charge is one value with two axes, because `B` caps both (§2.3, whichever binds). It forms a plain monoid — zero, add, sum, component-wise — and the budget only ever adds charges in and subtracts them back out; nothing but the poll gate ever looks inside.

```rust
struct Charge { events: u64, bytes: u64 }    // one value, two axes; +, +=, Σ are
                                             //   component-wise — a monoid, nothing more

struct Budget {
    used: Charge,                            // Σ charged − Σ refunded, exactly (§8.2)
    cap: Charge,                             // B: CONSUMER_UNCOMMITTED_BUDGET_EVENTS / _BYTES
}

fn charge(c: Charge) {                       // the whole interface: add in, subtract
    used += c                                //   out; only under_cap() reads the axes
}

fn refund(c: Charge) {
    used -= c
}
fn under_cap() -> bool {
    used.events < cap.events && used.bytes < cap.bytes
}
```

### 3.7 Commit manager — the commit policy, whole

Advances in on every progress event, commits out on its own algorithm; the drain's final offset through `begin_revoke`/`finish_revoke`. The §A.3 verification rides inside unchanged.

```rust
// The consumer loop's `commits` field — the whole commit policy behind four calls.
// It owns the pending frontiers, the delay algorithm, the §A.3 sentinel and issued
// record; the kafka client is handed in, and it holds none of the loop's other state.
struct CommitManager {
    pending: Map<Partition, Advance>,        // latest unissued frontier + charge tally
    last_issue: Instant,                     // the delay algorithm's state — today a plain
    revoking: Set<Partition>,                //   COMMIT_INTERVAL; thresholds, eager modes,
    commit_sentinel, issued,                 //   or per-partition policy change here only
}

fn progress(kafka, advances) -> Refund {     // called on every completion that moved a
    for a in advances {                      //   frontier; whether to issue now is this
        pending.merge(a)                     //   component's decision, nobody else's
    }
    maybe_issue(kafka)
}

fn tick(kafka) -> Refund {                   // the clock: issue if the delay is up
    maybe_issue(kafka)
}

fn begin_revoke(p) {                         // drain begun (§4.5): p's next issue is its
    revoking.insert(p)                       //   final one, via finish_revoke below
}

fn finish_revoke(kafka, harvest) -> Refund { // the drain's end: issue p's final frontier
    let held = pending.remove(harvest.p);    //   NOW — the rebalance is waiting. Every
    issue(kafka, [(harvest.p, harvest.frontier + 1)]);   //   completed span was already
    revoking.remove(harvest.p);              //   reported via progress, so the refund is
    held.charge + harvest.dropped            //   the held tally plus the never-completed
}                                            //   charge — nothing counts twice

fn maybe_issue(kafka) -> Refund {            // the algorithm — today: at most one batched
    if last_issue.elapsed() < COMMIT_INTERVAL {      //   issue per interval
        return 0
    }
    issue(kafka, pending.drain())
}

fn issue(kafka, batch) -> Refund {
    kafka.commit(batch);                     // manual, async, fire-and-forget: never blocks
    commit_sentinel.assert(batch);           //   the loop; commit exactly the frontier —
    issued.record(batch);                    //   B = polled minus committed
    last_issue = now;
    batch.charge()
}

// Separate long-lived task: read-only against the broker, owns nothing of the loop's.
task commit_monitor {
    loop {
        compare(broker.committed().await, issued);   // unchanged §A.3 — librdkafka drops
        sleep(MONITOR_INTERVAL).await;               //   async commit results
    }
}
```

### 3.8 Worker batcher — the transport side, whole, one task

Admission, placement, packing, settlement, and the stream runners, behind two channels: accumulators in, completions out. Its per-key state lives in the **key table**, its composition in the **packer**, and its concurrency in the **governor** — each its own component below — so the batcher itself is only the wiring between them and the streams. The split of duties in one line: the table decides *what may go*, the router decides *where*, the packer decides *when to pack and what rides together*, the governor decides *how much at once*.

```rust
// One long-lived task. Sole owner of everything transport-shaped; mutation is plain
// &mut, and its select! is its only await point.
struct WorkerBatcher {
    keys: KeyTable,                          // every key's send state + scheduling, one
                                             //   method per scenario — nothing else
                                             //   touches a key (§3.9)
    packer: Packer,                          // the pacing gate + the pack pass (§3.10)
    governor: Governor,                      // the permit valve + the ±1 law (§3.11)
    in_flight: Map<WorkerId, u32>,           // per-stream depth in use (≤ DEPTH_MAX)
    pace_at: Option<Deadline>,               // the pacing deadline (§3.10): armed while
                                             //   ready work waits on the gate
    retry_at: Option<Deadline>,              // armed only while an item is parked
    router: Router,                          // aperture + P2C over the health snapshot (§3.12)
    accumulators: Rx<Feed>,                  // Batch(accumulator) | Revoked(partition)
    resolutions: Rx<Resolution>,             // from the runners
    completions: Tx<Completed>,              // to the loop: ACKed groups only
    requests: Map<WorkerId, Tx<Request>>,    // send side per runner, capacity DEPTH_MAX
    resolutions_tx: Tx<Resolution>,          // cloned into each runner at spawn
}

task worker_batcher {
    loop {
        select! {
            feed = accumulators.recv() => match feed {
                Batch(acc) => {
                    for group in acc {
                        packer.fed(group.charge);        // the gate's input (§3.10)
                        keys.admit(group)
                    }
                    dispatch(Try)
                }
                Revoked(p) => {
                    if keys.begin_drain(p) {         // nothing of p in flight at all:
                        completions.send(Drained(p)) //   drained already (§4.5)
                    }
                }
            }

            (w, outcome, groups, rtt) = resolutions.recv() => {
                in_flight[w] -= 1;           // a depth slot frees; the governor observes
                governor.observe(rtt);       //   the RTT and runs its law (§3.11)
                settle(outcome, groups);
                dispatch(Try)                // the freed permit re-runs the gate
            }

            _ = sleep_until(min(pace_at, retry_at)) => {     // the transport's two clocks:
                pace_at = None;              //   pacing (§3.10) and park-retry (§4.4). A
                retry_at = None;             //   due deadline disarms as it fires;
                dispatch(Forced)             //   dispatch re-arms whichever is still owed
            }
        }
    }
}

fn settle(outcome, groups) {                 // every transition — per key and per drain —
    let drained = keys.settle(outcome, &groups);         //   is the table's; the batcher
    if outcome == Ack {                      //   only orders the sends: the ledgers' feed
        completions.send(Completed(groups))  //   first (failures stay here) —
    }
    for p in drained {                       //   then any Drained, riding *behind* the
        completions.send(Drained(p))         //   final completion it waited for (§4.5)
    }
}

fn dispatch(mode) {                          // every wake ends here: event wakes try,
    let n = governor.free();                 //   due deadlines force (§3.10)
    let packed = match mode {
        Try => {
            packer.try_pack(n, &mut keys, &router)
        }
        Forced => {
            packer.force_pack(n, &mut keys, &router)
        }
    };
    match packed {
        Wait => {                            // gate shut, or zero permits: keep
            if keys.any_ready() {            //   accumulating, and spend the traded
                pace_at.arm_if_unarmed(PACK_LATENCY_BUDGET)  //   latency instead
            }
        }
        Requests(reqs) => {
            pace_at = None;                  // the pass consumed the accumulation
            for (w, request) in reqs {
                fire(w, request)
            }
        }
    }
    if keys.any_ready() && governor.free() == 0 {
        governor.starve()                    // demand beyond the permits — the ±1
    }                                        //   law's grow signal (§3.11)
    if keys.any_parked() {
        retry_at.arm_if_unarmed(PARK_RETRY)
    } else {
        retry_at = None
    }
}

fn fire(w, request) {                        // the single send-origination site
    assert(governor.permit());               // the pass was sized by free(), so a permit
    requests[w].try_send(request).unwrap();  //   is always there. try_send non-blocking;
    in_flight[w] += 1;                       //   capacity DEPTH_MAX, provably never full:
}                                            //   the router refuses depth-full workers

fn on_worker_discovered(w) {                 // from registry discovery; a reaped worker's
    let (tx, rx) = channel(DEPTH_MAX);       //   runner and channel are torn down with it
    requests.insert(w, tx);
    spawn(stream_runner(w, rx, resolutions_tx.clone()));
}
```

### 3.9 Key table — per-key send state, partition-sharded

One method per scenario. A key lives in exactly one partition, so its state nests in that partition's **shard** — the transport-side mirror of the domain's partition driver, which also carries the shard's **keyless lane** (§1.1: null-key work owes no order — no state, just a queue of free filler, counted only for the drain). The shards, the lists, and every drain live behind the table; nothing outside touches any of them, the one-outstanding-per-key invariant is asserted in here, and a `Drained` can only be produced by a draining shard's final settlement — no `begin_drain`, no marker, by construction.

```rust
// Owned by the batcher. The two lists index across the shards — dispatch is
// O(runnable keys), FIFO for cross-key fairness — and the `queued` bit flips
// together with list membership, so a key can never be listed twice.
struct KeyTable {
    partitions: Map<Partition, PartitionKeys>,
    ready: Deque<Item>,                      // runnable now, in the order they became so
    parked: Deque<Item>,                     // unplaceable (§4.4); rejoin ready at each
                                             //   pass via retry_parked()
}

enum Item {                                  // the table's one scheduling unit — keyed or
    Keyed(RoutingKey),                       //   keyless is the table's business alone:
    Keyless(Partition),                      //   the router and packer never learn which
}

struct PartitionKeys {                       // one partition's shard — created at first
    keys: Map<RoutingKey, KeyState>,         //   group, removed when its drain completes
    keyless: FifoQueue<Group>,               // null-key groups (§1.1): no order owed, no
    keyless_out: usize,                      //   state — free filler, counted
    keyless_listed: bool,                    //   only for the drain; the listed bit works
    draining: Option<usize>,                 //   like `queued`. draining = Some(n) =
}                                            //   revoked, n keys + keyless runs still
                                             //   out: the ONLY source of a Drained

struct KeyState {
    queue: FifoQueue<Group>,                 // the key's send order — §A.5's cascade rule
    outstanding: bool,                       // exactly one request may carry a key's work
    queued: bool,                            // on ready or parked
}

fn admit(group) {                            // scenario: a demuxed group arrived
    let shard = shard(group.partition);
    match group.key {
        Some(key) => {
            shard.keys.entry(key).or_create().queue.push_back(group);
            make_ready(key)                  // no-op if listed or outstanding — the
        }                                    //   guard decides
        None => {
            shard.keyless.push_back(group);  // free work (§1.1): placed as filler, any
            list_keyless(group.partition)    //   worker, any split
        }
    }
}

fn retry_parked() {                          // scenario: a new pass — every parked item
    ready.append(take(parked))               //   rejoins the ready list for another
}                                            //   placement attempt: worker health is only
                                             //   observable at placement, and the pool
                                             //   may have healed since the item parked

fn pop_ready() -> Option<Item> {             // scenario: a pass wants the next runnable
    loop {                                   //   item; a drained shard's stale entries
        let item = ready.pop_front()?;       //   drop here
        match item {
            Keyed(key) => {
                if let Some(k) = lookup(key) {
                    k.queued = false;
                    return Some(item)
                }
            }
            Keyless(p) => {
                if let Some(shard) = partitions.get(p) {
                    shard.keyless_listed = false;
                    return Some(item)
                }
            }
        }
    }
}

fn take(item, up_to) -> Run {                // scenario: the pass placed the item — hand
    match item {                             //   over a run of its work
        Keyed(key) => {
            lookup(key).outstanding = true;  // a contiguous, in-order run of the key's
            lookup(key).queue.take(up_to)    //   queue — one request may carry it
        }
        Keyless(p) => {
            let shard = shard(p);
            shard.keyless_out += 1;          // counted for the drain only (§1.1)
            let run = shard.keyless.take(up_to);
            if !shard.keyless.is_empty() {   // remainder: back on the list for this or
                list_keyless(p)              //   the next pass
            }
            run
        }
    }
}

fn park(item) {                              // scenario: pool-wide unroutable (§4.4) —
    match item {                             //   the work stays where it is; only the
        Keyed(key) => {                      //   item waits on the parked list
            lookup(key).queued = true
        }
        Keyless(p) => {
            shard(p).keyless_listed = true
        }
    }
    parked.push(item)
}

fn any_parked() -> bool {
    !parked.is_empty()
}

fn any_ready() -> bool {                     // may count a drained shard's stale entries
    !ready.is_empty()                        //   briefly — they drop at the next
}                                            //   pop_ready, so a false positive costs
                                             //   one empty pass, never a lost wake

fn settle(outcome, groups) -> Vec<Partition> {       // scenario: a request resolved —
    let mut drained = vec![];                //   every per-key transition and every
    for (key, run) in groups.by_key() {      //   drain step happen in here
        let shard = shard(key.partition);
        let k = shard.keys[key];
        assert(k.outstanding);               // the invariant, checked — not assumed: a
        k.outstanding = false;               //   key's work settles before more is sent
        if shard.is_draining() {             // §4.5: a draining shard sends nothing new —
            shard.keys.evict(key);           //   even failures just drop; the partition's
            drain_step(key.partition, &mut drained);     //   next owner re-reads them
            continue
        }
        if outcome == Failure {
            k.queue.push_front(run)          // order intact — back to the head
        }
        if k.queue.is_empty() {
            shard.keys.evict(key)
        } else {
            make_ready(key)
        }
    }
    for (p, run) in groups.keyless_runs() {  // keyless settles by count alone (§1.1): no
        let shard = shard(p);                //   assert, no order
        shard.keyless_out -= 1;
        if shard.is_draining() {             // a draining shard's keyless failures drop
            drain_step(p, &mut drained)      //   too, like everything else of its
        } else if outcome == Failure {       //   partition
            shard.keyless.push_back(run);    // any position is fine — no order owed
            list_keyless(p)
        }
    }
    drained
}

fn begin_drain(p) -> bool {                  // scenario: the in-band revoke marker (§4.5)
    let shard = shard(p);
    shard.keys.retain(|k| k.outstanding);    // queued-only keys and queued keyless work
    shard.keyless.clear();                   //   drop — never sent, the next owner
    shard.draining = Some(shard.keys.len() + shard.keyless_out);     //   re-reads them;
    if shard.draining == Some(0) {           //   O(one shard). The rest counts down in
        partitions.remove(p);                //   settle(); nothing in flight at all
        return true                          //   means the shard is drained already
    }
    false
}

fn drain_step(p, drained) {                  // private — one settled unit of a draining
    let shard = shard(p);                    //   shard; the final step removes the shard
    let n = shard.draining.unwrap();         //   and births the Drained — its only source
    shard.draining = Some(n - 1);
    if n == 1 {
        partitions.remove(p);
        drained.push(p)
    }
}

fn make_ready(key) {                         // private — the only way onto a list: the
    let k = lookup(key);                     //   guard makes entries unique by construction
    if !k.queued && !k.outstanding && !k.queue.is_empty() {
        k.queued = true;
        ready.push(Item::Keyed(key))
    }
}

fn list_keyless(p) {                         // private — the keyless lane's make_ready
    let shard = shard(p);
    if !shard.keyless_listed && !shard.keyless.is_empty() {
        shard.keyless_listed = true;
        ready.push(Item::Keyless(p))
    }
}

fn lookup(key) -> Option<&mut KeyState> {    // private — every key access routes through
    partitions.get(key.partition)?.keys.get(key)     //   its partition's shard
}
```

### 3.10 Packer — pacing and composition, its own component

When to pack and what a request carries are decided here, and only here — the router decides where work goes, the table decides what may go at all. The packer holds no messages: the accumulation it prices stays in the key queues, which is what lets a key's next poll join its pending run.

**Trigger conditions** (two transport clocks: the pacing deadline and the park-retry, §4.4). Dispatch is two calls on the packer — `try_pack(n)` on event wakes, `force_pack(n)` on a due deadline, with `n` = the governor's free permits — and both return `Wait` or up to `n` composed requests, which all fire at once:

- *The pacing gate*: admitted work accumulates **unplaced, in the key queues**, until `try_pack` judges it enough to pack well — the charge admitted since the last emitting pass reaches `n × T` — and one pass then pops, places, and composes it. `Wait` arms the **pacing deadline** (`PACK_LATENCY_BUDGET`); its expiry calls `force_pack`, which emits whatever is ready, partial requests included. Accumulating in the queues is what makes the trade pay: a key's next poll *joins* its pending run instead of queueing behind an undersized request for a full round trip. `PACK_LATENCY_BUDGET = 0` recovers fire-on-arrival exactly.
- *Settlement*: each settlement frees a permit and re-runs `try_pack` — a hot key with a target's worth of backlog refills immediately, a full request per round trip: the eager chain, upgraded. Under saturation `n` is zero and everything keeps accumulating — deliberately: the pipe is full, so waiting costs nothing and buys packing; the first settlement whose gate opens (or the next forced pass behind it) emits.
- *Target cap `TARGET_REQUEST_EVENTS` / `_KB`*: each composed request seals at `T`, whole key-runs only, so an over-target backlog yields consecutive full requests across passes.

The pacing deadline is the linger timer, readmitted deliberately: it is not needed for liveness — settlements alone re-open the gate — but it is the explicit price of packing quality, and the operator's knob. The wait bounds it leaves are argued in §4.6.

**Composition** (which groups ride together): each group carries an opaque **affinity** hint — stamped by the partition driver with the partition id, but the batcher knows only the preference rule: *minimize distinct affinities per request, choosing affinities oldest-head-first*. A key's work rides a request as one contiguous, in-order run from its queue (up to the target — hot-key coalescing), and cross-key order is unconstrained, so composition is free to pack. Affinity-pure requests mean a failed request wounds one partition's frontier, not eight (blast radius), and a slow request delays few frontiers (frontier coupling). Oldest-first keeps the packing strictly latency-safe. The affinity hint also acts as a placement *tie-break* among otherwise-equivalent open requests — never overriding load or fill, so a hot partition cannot become a hot worker. Keyless groups (§1.1) are the packer's free filler: no queue-behind, no one-outstanding — they top any open request toward target, and split however the pass likes.

```rust
// Owned by the batcher. Packing is one pass — pop ready, place, compose, emit
// whole — so nothing placed ever outlives a call: there are no bins.
struct Packer {
    pending: Charge,                         // admitted since the last emitting pass —
}                                            //   the pacing gate's input (above): a
                                             //   reset-at-pass heuristic, deliberately
                                             //   not a maintained aggregate that could
                                             //   drift

enum Packed {
    Wait,                                    // not enough to pack `n` well — the batcher
                                             //   arms the pacing deadline (above)
    Requests(Vec<(WorkerId, Request)>),      // ≤ n composed requests; the batcher fires
}                                            //   them all, immediately

fn fed(charge) {                             // the batcher reports each admitted group
    pending += charge
}

fn try_pack(n, keys, router) -> Packed {     // the pacing gate: emit when the free
    if n > 0 && pending.reaches(n * T) {     //   concurrency can be packed with full
        pass(n, keys, router)                //   requests (either charge axis, §2.3) —
    } else {                                 //   else keep accumulating, and spend the
        Wait                                 //   traded latency instead
    }
}

fn force_pack(n, keys, router) -> Packed {   // a due deadline: the traded latency is
    if n == 0 {                              //   spent — emit whatever is ready, partial
        Wait                                 //   requests included. Only zero permits
    } else {                                 //   refuses now, and settlements re-try,
        pass(n, keys, router)                //   ≤ one ACK timeout apart (§4.6)
    }
}

fn pass(n, keys, router) -> Packed {         // private — the one placement pass
    pending = Charge::ZERO;                  // the gate's counter resets with the pass
    keys.retry_parked();                     // parked items rejoin ready first — the
    let mut open = Requests(vec![]);         //   pool may have healed
    while open.charge() < n * T {            // room for ≤ n requests, each sealed at T
        let Some(item) = keys.pop_ready() else { break };
        match router.place(&open) {          // pass-local fill and load (§3.12)
            Placed(w) => {
                open.add(w, keys.take(item, up_to: open.room(w)))    // whole key-runs;
            }                                //   composition is the rules above: affinity-
            Unroutable => {                  //   minimizing, oldest-head-first
                keys.park(item)              // pool-wide, no healthy worker (§4.4): the
            }                                //   item parks, leaving the pass
        }
    }
    open                                     // partials included — nothing is held back,
}                                            //   so no buffer exists to forget or drain
```

### 3.11 Dispatch governor — the concurrency valve, its own component

How many requests ride at once is the batcher's last decision, and the one place the elastic-dispatch controller survives, shrunk to a valve. The structure already produces the plan's headline behaviors: demand is not an estimated fill ratio but the key table itself — ready work is waiting or it isn't — the total exposure is capped by `B`, and a backlog puts up to a full pool of target-sized requests in flight with no controller in the loop. What the structure alone cannot do is *retreat*: nothing would otherwise shrink the work in flight below `B` when the pool sickens — and crash exposure matters most exactly then, since wedges are when OOMs, restarts, and deploys-during-incident happen. So the governor holds a **permit count** — requests allowed in flight — and runs the plan's ±1 law on it, re-evaluated at every settlement (whose spacing the ACK timeout bounds, so it needs no clock): grow `+1` toward demand while dispatch is permit-starved (a pass left ready work with zero free permits) and the request-RTT EWMA (time-aware α, τ ≈ 10 s) sits under `REQUEST_LATENCY_BUDGET`; shed `−1` while it sits over; floor `GOVERNOR_MIN`, cap `GOVERNOR_MAX`. The plan's no-congestion-input reasoning carries over whole: the budget sits ≳3× healthy request RTT, so shedding refuses only the pathological region — where timeouts already gut the worker HPA's occupancy signal — the floor keeps probing, and 503s never reach the governor at all (transport backoff, §A.9).

**Stream depth.** Depth stays 1 per worker by default (`GOVERNOR_MAX` ≤ pool size), but this model — unlike today's — makes depth *safe to raise*: two requests on one ordered stream necessarily carry disjoint keys (one outstanding request per key), so a stream break fails them all and hands each home whole — no successor ledger, no fence, exactly as at depth 1. If ACK round-trip proves to be a stream's ceiling, `DEPTH_MAX` lifts and the governor's spare permits become pipelining: the runner encodes request *n+1* while *n* awaits its ACK.

The batcher sizes each pass by `free()`, takes `permit()` at fire, reports `starve()` when ready work is left with no free permit, and reports `observe(rtt)` at settlement; nothing else crosses.

```rust
struct Governor {
    permits: u32,                            // requests allowed in flight, MIN..=MAX
    in_flight: u32,
    starved: bool,                           // a dispatch left ready work with zero
                                             //   free permits (§3.8)
    rtt: Ewma,                               // time-aware α (the plan's EWMA aside), τ ≈ 10 s
}

fn permit() -> bool {                        // taken at fire, returned at settlement —
    if in_flight == permits {                //   never actually refused: every pass is
        return false                         //   sized by free() before it composes
    }
    in_flight += 1;
    true
}

fn free() -> u32 {                           // permits not in flight — sizes each
    permits - in_flight                      //   pack pass (§3.10)
}

fn starve() {                                // the batcher's demand signal — the ±1
    starved = true                           //   law's grow input
}

fn observe(rtt_sample) {                     // at every settlement — the law:
    in_flight -= 1;
    rtt.update(rtt_sample);
    if rtt > REQUEST_LATENCY_BUDGET {        // pathological only (budget ≳3× healthy):
        permits = max(GOVERNOR_MIN, permits - 1)     //   walk exposure down while a crash
    } else if starved {                              //   is most likely (§4.7)
        permits = min(GOVERNOR_MAX, permits + 1)     // grow toward demand while healthy
    }
    starved = false
}
```

### 3.12 Router — memoryless placement

**Placement** (which worker an item's work goes to): there are **no sticky pins in this design** — a major, behavior-changing departure from today, flagged in the preamble and §2.4. Both of the pin's historical jobs (§A.4) dissolved — order is structural (at most one outstanding request per key, on ordered streams; the pin existed to keep a key's *concurrent* batches together, and per-key concurrency no longer exists), and steady-state consolidation belongs to the packer, which composes requests toward target regardless of which keys arrive. Placement is therefore **memoryless**: work fills the pass's open, in-slice, below-target requests first (load- and depth-checked), then rotating P2C opens further slice workers — and no placement state outlives the pass. Re-placement can never reorder: new groups for an outstanding key never reach the router at all — they queue behind, and `pop_ready` yields only keys with nothing outstanding — so between a request's send and its settlement, no routing decision for that key exists. What is given up is an unmeasured conjecture: worker-side per-key cache locality; §7 keeps it as the open question, reintroducible entirely inside the router if it ever proves real. A ready key *no* worker can take — pool-wide unroutability only — stays parked in its own queue and is re-tried at the next pass (§4.4); nothing is ever handed back. Fan-out is **emergent**: demand ÷ target, clamped below by the aperture coverage floor, with slice coverage achieved over seconds by rotation rather than within every batch. The elastic-dispatch fan-out formula stops being a formula.

No pins, no state beyond the aperture; the verdicts are named:

```rust
enum Placement {                             // the router's verdict, named:
    Placed(WorkerId),                        //   this item's next run rides w's stream
    Unroutable,                              //   pool-wide — no healthy worker (§4.4)
}

fn place(pass) -> Placement {                // reads the pass's open requests for fill;
    let health = registry.snapshot();        //   health is the probe task's snapshot, the
                                             //   model's only cross-task shared read
    let slice = aperture.slice(health);      // in-slice candidates
    let open = slice.healthy, with a below-target open request this pass, load- and depth-checked;
    if open is non-empty {
        Placed(pick by fill, affinity overlap as tie-break)  // never overriding load/fill
    } else if slice.any_healthy() {
        Placed(rotating_p2c(slice))          // opens further slice workers
    } else {
        Unroutable                           // the item parks; a later pass re-tries
    }                                        //   (§4.4)
}
```

### 3.13 Worker stream runner — one task per worker, depth-bounded

The machinery below the batcher, which hands it both channel ends at spawn.

```rust
// One long-lived task per worker. Owns its connection; shares only the two channels
// (received from on_worker_discovered), and both hand data over by value.
task stream_runner(w, requests: Rx<Request>, resolutions: Tx<Resolution>) {
    loop {
        connect_and_greet(epoch).await;      // BLOCKS (its own socket); on failure:
                                             //   backoff, then reconnect
        while connected {                    // pipelined to the stream's depth: encode and
            select! {                        //   transmit request n+1 while n awaits its ACK
                request = requests.recv() => {
                    encode_and_transmit(request).await   // per-request CPU (serialize,
                }                                        //   compress) runs here, off the
                outcome = next_ack() => {                //   batcher task — one task per
                    resolutions.send(w, classify(outcome), groups, rtt)  //   worker, so
                }                            //   encodes run concurrently across the pool
            }                                //   (§3.14); ACKs resolve in send order
        }                                    //   (ordered stream)
        // stream break: every un-ACKed request fails and comes home whole; their keys
        // are disjoint (one outstanding request per key), so no fence is needed
    }
}

fn classify(outcome) {                       // the transport classifier, §A.9 unchanged
    match outcome {
        Ack          => Ack,
        Busy | 503   => Backpressure,        // long jittered backoff; excluded from
                                             //   passive health
        Fault        => Failure,             // counts against passive health, after the
                                             //   below-model retries; groups come home whole
        Oversize413  => split_halve_resend() // §A.10 defense below the model — rare
    }                                        //   once T is under the worker body limit
}
```

### 3.14 CPU concurrency

The event loop is now nearly free — demux and ledgers — while admission, dispatch, packing, and settlement run on the worker batcher task and encode/compress on the stream runners, one concurrent encode per in-flight request across the pool (and within one stream at depth > 1); the pipeline overlaps — while the batcher dispatches one poll's groups, the loop demuxes the next. If the batcher ever becomes the ceiling, its natural shard axis is the partition: the key table is already partition-sharded (a routing key lives in exactly one partition), so key states split cleanly by partition-set — at the price of per-shard passes and streams (shard×worker), the coalescing cost the single-task design avoids. Ship unsharded, instrument both tasks' occupancy the way `assign_duration_seconds` is watched today, and shard only when the metric says so. Fleet-level parallelism remains partition assignment across pods.

## 4. The guarantees

What is *not* in §3 is the point: no stash, no batch-sequence bookkeeping, no fences or `FenceGuard`, no eager reconciliation, no completion serialization, no bins of placed-but-unfired work, no per-key timers — and no locks: today's `PinTable` mutex and its lock-ordering discipline have no successor, because nothing is shared to lock. This section takes each guarantee of §1.1 — and each adverse condition today's machinery defends against — and shows the structure that now carries it.

### 4.1 Per-key send order

The order argument is visible as four structural facts — one origination site (`fire`), at most one outstanding request per key (asserted at `settle`, never assumed), depth-bounded ordered streams whose in-flight requests therefore carry disjoint keys, and two tasks that each finish one cascade before taking the next event. And the coupling argument is a fifth: the sides exchange only accumulators down and completions up, plain values on FIFO channels — so neither side can observe, or corrupt, the other mid-transition. The split is total: the domain is offsets, and knows no worker and no send queue; the transport is send state, and knows no ledger.

A key's entire order lives in one queue in one task, and at most one request carries a key's work at any moment — *asserted* at settlement, not assumed — so nothing can slip a newer group past a failure being processed, exactly the race the worker-stream fences exist to close today (§A.8). Re-placement can never reorder: new groups for an outstanding key never reach the router at all — they queue behind, and `pop_ready` yields only keys with nothing outstanding — so between a request's send and its settlement, no routing decision for that key exists (§3.12). The key-order sentinel survives as a cheap assert (§5): it now verifies what the structure constructs.

### 4.2 Per-partition commit contiguity

Contiguity is constructed, not emergent. Today the committable point emerges from oldest-first completion plus the all-accepted check, and the sentinel verifies what nothing computes (§A.2–A.3); here the offset ledger *is* the property: `complete()` can only ever advance the dense ring's frontier — the highest contiguous completed offset — and the commit manager only ever issues frontiers, on every path including the drain's final commit. Out-of-order completion is absorbed structurally: late slots go done above a gap and nothing advances until the earlier work lands (§3.5). The commit sentinel survives as a cheap assert, and the commit monitor as-is — librdkafka still drops async commit results (§A.3).

### 4.3 At-least-once

Nothing is committed until accepted: a slot goes done only when its group's request is ACKed, and failures never cross the seam — the groups return to their queue heads and the offsets simply stay pending, so the frontier cannot walk over them. Every message's charge is measured once, by the ledger slot that will later return it, and refunded exactly once — at the commit that covers it, or as a drain's `dropped` when the work never completed — so `B` = polled minus committed stays exact, and a crash replays exactly the uncommitted span, bounded by `B` (§4.7). A completion that straggles in after a drain's teardown dies by epoch; the replay it represents is legal duplication, never loss.

### 4.4 Under failure

- **503 / stream busy**: unchanged — the transport's jittered backoff absorbs deliberate backpressure below the model, excluded from passive health.
- **Send failure (fault)**: settled entirely inside the batcher — each carried key is asserted outstanding, its groups go back to its queue head, and dispatch re-places it immediately against current health (§3.12). The domain never hears of it: its offsets simply stay pending. No backoff above the transport: transient faults were already retried with backoff below the model (§A.9), and passive health has already marked the failing worker, so waiting again would be double pacing. This replaces `defer_failed` + re-stash + both flush paths' retry pacing with one local rule. The order argument is trivial: the key's queue *is* the order, and nothing of that key was in flight behind the failure (one outstanding request per key — a stream's in-flight requests are key-disjoint).
- **Draining/dead worker**: the registry is unchanged; the *consequence* becomes local. Memoryless placement (§3.12) simply never picks a draining or dead worker again — and since nothing of a key is in flight when it is placed, avoiding a worker cannot reorder. The cascade rule is the queue: newer groups are behind older ones by construction. No stash, no batch-sequence bookkeeping, no outstanding-count subtlety.
- **Unroutable pool**: placement finds no healthy worker — the ready key stays **parked** in its own queue, and every pass re-tries it first (`retry_parked`) — whichever call emits one (§3.10) — with a park-retry deadline, armed only while parked keys exist, forcing a pass when the traffic goes quiet. Waiting for a routable pool is transport state, so both the waiting and its pacing live in the transport — the domain never arms a timer for it, and nothing is handed back. There is no separate buffer of groups: an unplaceable key's work stays in its own queue — only its id waits on the key table's parked list. The partition frontiers stall; the watchdog below bounds it.
- **Stall watchdog**: per-partition — a frontier stuck for the timeout while work is pending fails the process, replaying that exposure (≤ B). Today's `deferred_flush_timeout` semantics, at the granularity where a wedge actually lives; the check runs on the loop's housekeeping tick — a watchdog cannot be event-driven, since what it detects is the absence of events. A wedged key stalls *its partition's* frontier while healthy partitions keep committing — today it stalls every partition on the pod.

### 4.5 Under rebalance: the bounded drain

Revocation is a **bounded drain**, not a synchronous teardown. On revoke the loop keeps the partition driver — its ledger must still absorb the completions in flight — tells the commit manager (`begin_revoke`), and sends the batcher an in-band **revoke marker** down the accumulator channel, ordered behind every batch that preceded it. The batcher drops the partition's *queued* key states at once (never sent, so the next owner simply re-reads them), stops re-queueing its failures, and counts its outstanding keys down as their requests settle; when the last one lands it emits **`Drained`** up the completion stream — in-band again, behind the partition's final completion. Only then does the loop hand the final harvest to the commit manager (`finish_revoke` — issued immediately, refunding every charge the partition still held), drop the driver, and hand the partition back to rdkafka (`incremental_unassign`). The drain needs no clock of its own: depth-bounded streams plus the runner's ACK timeout bound every outstanding request's settlement, so `Drained` arrives within one request timeout — configure the rebalance timeout above it, and a completion that straggles past teardown still dies by epoch. The assignment-epoch stamp (from #85238) keeps worker-side sentinels re-baselined.

### 4.6 Liveness and bounded waits

The bounded-wait argument is two waiting rooms, each with its own bound. Work waits either in a key queue or on the wire — placed-but-unfired is not a state, so there is no buffer to forget and no per-stream fairness to arrange. On the wire, the ACK timeout bounds every settlement. In the queues: while a permit is free, ready work waits at most `PACK_LATENCY_BUDGET` for a forced pass; while none is, settlements arrive at most one ACK timeout apart and the budget-spaced force re-tries behind each — so ready work waits at most one ACK timeout plus one budget, and a parked item adds its park-retry deadline (§4.4). The three clocks this needs — the loop's housekeeping tick and the batcher's two deadlines (§2.1) — are the only timers in the model; nothing else waits on time.

### 4.7 Bounded exposure and memory

`B` is the **crash-replay window, enforced directly**. The elastic plan bounded replay through a duration budget because Little's law was the only handle batch slots offered; here the bound is the number itself. The memory provisioning contract becomes literal — `baseline + librdkafka caps + B_bytes + headroom`, verified at boot — with no ×2 estimation. And when the pool sickens, exposure does not sit at `B`: the governor walks the in-flight span down (§3.11), shrinking exactly the exposure a crash mid-wedge would replay.

## 5. Construct-by-construct disposition

| Today | In the driver model |
|-------|---------------------|
| Batch collection | Unchanged as input format; batch dissolves at demux |
| In-flight batch window (A.1) | Retired; replaced by budget `B` (poll gate) |
| Oldest-first completion (A.2) | Retired; per-partition offset ledger commits the contiguous frontier |
| Commit sentinel (A.3) | Kept as a cheap assert; contiguity is now constructed, not emergent |
| Commit monitor (A.3) | Kept as-is (librdkafka async-commit blindness is unchanged) |
| Sticky pins (A.4) | Retired: both jobs dissolved — order is structural (one outstanding request per key + ordered streams), consolidation is the packer's (target packing). Router affinity can return if measured (§7) |
| Stash + cascade rule (A.5) | The batcher's per-key queue; the cascade is the queue |
| Completion-time flush (A.6) | Retired; commit gate → ledger, retry pacing → transport backoff + parked releases, watchdog → per-partition stall deadline |
| Eager flush + its accounting (A.7) | Becomes the *only* drain mechanism — settle + dispatch, refilling up to a full request from one key's backlog; `eager_pending`/`eager_accepted`/`take_eager_accepted` deleted |
| Worker-stream ledger + fences (A.8) | Key-disjoint depth-bounded streams + single-origination dispatch; ordered stream kept, fences and consecutive-prefix resolution deleted |
| 503/backoff/backpressure classification (A.9) | Unchanged |
| Body split + 413 (A.10) | Kept as defense; `T` makes routine splitting stop happening |
| Worker registry (A.11) | Unchanged; drain consequences become key-driver-local |
| Aperture + P2C (A.12) | Kept for placement, now memoryless; fan-out formula retired (emergent from demand ÷ `T`); `STICKY_PIN_LOAD_SLACK` retires with the pins |
| Key-order sentinel (A.13) | Kept as a cheap assert; order is now structural (one origination site, one outstanding request per key — asserted at settle — key-disjoint ordered streams) |
| Debug recorder | Kept; event points move to the drivers (arguably richer: per-key and per-partition state is now first-class) |

The through-line: the mechanisms that survive are the ones facing the outside world (transport classification, registry, discovery, sentinels-as-audit). The mechanisms that dissolve are the ones that bridged batch-shaped machinery to key/partition-shaped invariants.

## 6. How this drives the autoscaling plan

The elastic-dispatch plan's three changes map onto the model as follows:

1. **Target-sized worker batches** — the batcher's `T` and packing rules (§3.10) *are* stage 1 of the plan, with the fan-out clamp formula replaced by emergence; the plan's pins-as-preferences packing dissolves with the pins themselves (§5, row A.4).
2. **Demand-proportional concurrency** — the plan's fill-EWMA → slots law is subsumed by `B` + self-clocking (§2.3): MIN when drained, MAX under backlog, held pressure during worker saturation, bounded replay window — the structure permits nothing else, with no fill estimator and no tick. The one behavior that is *not* structural — walking exposure down during a wedge — survives as the batcher's dispatch governor (§3.11): the plan's ±1 law and latency budget, applied to requests in flight, evaluated at settlement instead of on a clock.
3. **One-signal worker HPA** (the elastic plan's "processor HPA") — unchanged from the plan (`ingestion_api_event_seconds_in_flight_total`, time-weighted in-flight events per pod), and *strengthened*: every request is target-normalized, so in-flight work per worker is an honest, comparable unit.

The two scaling regimes the plan demands fall out of the poll gate:

- **Workers fast, backlog draining**: the gate stays open, the consumer is CPU-bound (demux, packing, encode), its CPU-only HPA is truthful — pods scale when the consumer is the bottleneck, and only then.
- **Workers slow / pool undersized**: uncommitted work fills `B`, polling pauses at low CPU (the consumer fleet correctly *doesn't* scale), and B/T requests held in flight drive the worker pool out. The transport's jittered backoff bounds futile traffic; a 503'd request never counts as worker occupancy, so the scale-out signal can't be starved — same reasoning as the plan's "no congestion input" argument, unchanged.

## 7. Open questions

1. **Build order.** The elastic plan's stages 1–2 can land on the current architecture (they're specced that way); the driver model delivers the same behavior by structure. Options: (a) elastic stages on the current code first, redesign later — two migrations, faster relief; (b) build the driver model and ship the elastic behavior with it — one migration, longer lead. The controller-free shape argues for (b) if the incident pressure allows; the stage 1 packing changes are the piece most worth doing early either way, since the packer carries over almost verbatim.
2. **Governor and pacing defaults** — `GOVERNOR_MIN`/`_MAX`, `REQUEST_LATENCY_BUDGET` (≳3× healthy request RTT — at or below it a lane pins to MIN), `DEPTH_MAX` (start 1; lift only if ACK round-trip caps a stream's throughput below what one worker can absorb), `PACK_LATENCY_BUDGET` (the pacing gate's traded latency, §3.10 — `0` recovers fire-on-arrival; calibrate against observed request fill). Tuned on team2 with the exported governor state, per the elastic plan's calibration.
3. **Partition fairness at the poll gate** — one global `B` lets a deep partition monopolize the budget. Levers, in escalation order: none (watch it), rdkafka per-partition pause/resume, isolating hot partitions on dedicated pods at the assignment level. Don't build until observed.
4. **Shard count** — single-shard until loop occupancy says otherwise (§3.14).
5. **`B` and `T` defaults** — `T` from the per-request-cost knee (the elastic plan's stage 1 calibration, unchanged); `B` from the acceptable replay window and the memory contract, with the plan's ~"MAX × batch" residual exposure as the anchor.
6. **Worker cache affinity** — sticky pins are deleted (§3.12): order and consolidation no longer need them, leaving only an unmeasured conjecture about worker-side per-key cache locality. If memoryless placement measurably hurts worker cache hit rates, reintroduce a key → worker preference entirely inside the router (a bounded LRU, recorded at the placement decision, abandoned by the health and load checks) — zero protocol impact. Measure first.

## 8. Nomenclature

The consumer's vocabulary has to survive three audiences at once: this crate, the Node.js worker across the wire, and the rest of PostHog — where `lane`, `group`, `chunk`, `cohort`, and `fence` already mean things. The rules of this doc: the diagnosis (§1.2) and Appendix A describe today's constructs under the names the code actually uses; the design sections use only the canonical terms below. A "never" entry reserves the word — new type, config, metric, and proto names must not reuse it for another concept.

### 8.1 Canonical terms

| Term | Means | Never |
|---|---|---|
| `lane` | the deployment axis (`INGESTION_LANE`; global `ingestion_lane` metric label) | anything consumer-internal |
| `worker` | one Node.js ingestion-api process (proto `WorkerIngest`) | processor |
| `worker stream` | the ordered gRPC connection to one worker (`WorkerStream`) | lane |
| `batch` | one Kafka collection unit; dissolves at demux | the worker-facing unit |
| `sub-batch` | today's worker-facing unit (proto `SubBatch`); retired by this design | — |
| `request` | this design's worker-facing unit: one target-sized send | batch, sub-batch |
| `group` | one key's messages from one poll (`MessageGroup`) — or one keyless message (§1.1) | chunk |
| `consumer group` | the Kafka sense, always spelled in full | bare "group" |
| `chunk` | a body-size split of one request (the transport's 413 path) | the per-key unit |
| `routing key` | the message's Kafka partition key, opaque here; the order unit — null ⇒ unordered (§1.1) | `token:distinct_id` — writing (and parsing) it is capture's business |
| `defer` | hold a key's newer work until its older work lands | stash, in new names |
| `frontier` | highest contiguous completed offset, per partition | watermark |
| `watermark` | highest ACKed offset, per key (the order sentinel's sense) | high-water mark |
| `ledger` | the partition driver's offset accounting | the eager-flush accounting |
| `fence` | the worker stream's failure barrier (`FenceGuard`) | partition→pod isolation |
| `affinity` | the batcher's composition hint (today: the partition id) | cohort |
| `pack pass` | one gate-opened sweep: pop ready → place → compose ≤ n requests, all fired — nothing placed survives it | — |
| `resolve` | a send finished, success or failure | settle |
| `eager-flush task` | the ACK-speed drain task (`run_eager_flush_loop`) | sidecar |
| `window` | always qualified: in-flight, passive, stall, replay window | bare "the window" |
| `driver` | the single owner of one unit's state, advanced only by events | — |
| `consumer loop` | the event pump at the top: results, polls, deadlines, rebalance | consumer *driver* — it owns no unit's state |
| `partition manager` | the domain side's root: assignment lifecycle + the offset ledgers | — |
| `release` | the loop's hand-off of a filled accumulator to the batcher | the ship-a-version sense |
| `worker batcher` | the transport-side task: the key table, the packer, the governor, placement, streams | — |
| `key table` | the batcher's component owning all key states + their scheduling, partition-sharded, one method per scenario | — |
| `partition keys` | one partition's shard of the key table: its key states + keyless lane + drain | the domain's partition *driver* |
| `keyless` | null-key work — no order owed (§1.1); a shard's free-filler lane | — |
| `item` | the table's one scheduling unit: a ready key, or a shard's keyless lane | — |
| `packer` | the batcher's pacing + composition component: the gate and the pack pass | — |
| `key state` | one key's entry in its shard: queue · outstanding · queued | key *driver* — retired with the domain-side version |
| `outstanding` | a key has exactly one request's worth of work out (§A.5's sense) | in-flight, for this |
| `admit` / `dispatch` / `settle` | the batcher's three phases: queue in, place + fire, resolve | — |
| `completion` | one ACKed request's groups, forwarded to the loop for the ledgers | request result — failures never cross the seam |
| `accumulator` | one poll's demuxed groups: obtained from the factory, lent down the demux | — |
| `accumulator factory` | the loop's buffer supply + the batcher's send side: obtain / release / revoked | — |
| `completion stream` | the transport's outlet: completions, drained by the loop | result stream |
| `parked` | a key the pool cannot take: groups stay in its queue, its id on the table's parked list (§4.4) | a separate group buffer |
| `drain` | revocation: drop queued work, settle in-flight, final-commit, unassign (§4.5) | the worker-drain sense — that stays "draining worker" |
| `governor` | the batcher's permit valve: requests in flight, ±1 by RTT vs budget (§3.11) | controller — the plan's word; this is its surviving piece |
| `pacing gate` | `try_pack`'s emit condition: enough charge to pack the free permits; a due pacing deadline (`PACK_LATENCY_BUDGET`) forces instead (§3.10) | linger — the producer-config word; this prices packing, not batch fill |
| `depth` | a stream's in-flight request bound (`DEPTH_MAX`); safe above 1 — keys stay disjoint | — |
| `advance` | one frontier movement: partition, new frontier, the span's charge | — |
| `charge` | a message's events+bytes, as debited from `B` at poll | cost, weight |
| `refund` | a charge returning to `B`: at commit issue, or at a drain's end | — |
| `dropped` | the charge a drain abandons (never completed); refunded at `finish_revoke` | — |

### 8.2 Why these words are reserved

- **`lane`** is claimed three times over: capture's `Lane { Main, Overflow, Historical }` routing enum (plus the AI lane's topics), the Node deployment lanes (`INGESTION_LANE`, one namespace per lane, the `ingestion_lane` Prometheus label), and this binary stamps that label on every metric it emits. Drafts of #85238 called the gRPC construct a lane; the merged code says `WorkerStream`, and this doc follows the code.
- **`worker`, not `processor`**: every artifact of the downstream fleet says worker — the proto package `ingestion.worker.v1`, `INGESTION_WORKER_CONCURRENT_BATCHES`, `rust/ingestion-worker-proto`, the `worker` metric label. "Processor" is the elastic-dispatch plan's word for the same fleet (kept there, mapped in §6); in code, `*Processor` already means an in-process pipeline stage in both Rust and Node. One fleet, one name.
- **`group`, not `chunk`**, for the per-key unit: this crate's `MessageGroup`/`DeferredGroup` and the Node framework's `concurrentlyPerGroup(getTokenAndDistinctId, …)` are the same concept with the same key on both ends of the wire. `chunk` is doubly taken: the transport's 413 split (kept by §5), and the Node framework's per-stage unit (`ChunkPipeline`, whose docs explicitly contrast chunks with batches). The price is that the Kafka sense must always be written "consumer group".
- **`cohort` → `affinity`**: cohort is a core product noun (user cohorts, the cohorts API, five `rust/cohort-*` crates). The hint is the partition id used as a packing preference; affinity says exactly that.
- **`fence`** stays only because the merged worker-stream code uses it in the same sense personhog does — a barrier that stops the old flow before new work may start. Partition→pod placement (§7.3) is *isolation*, not fencing.
- **`frontier` vs `watermark`**: watermark is claimed twice already — this crate uses it for the per-key ACK point (order sentinel), and Kafka itself uses low/high watermark for broker-side log bounds (log start, replicated-up-to), neither of which is consumer bookkeeping. The highest *contiguous completed* offset has no standard Kafka name at all, because the in-order consumer never needs it; the word comes from dataflow systems, where the frontier is precisely "everything below this is complete". Earlier drafts used frontier and watermark interchangeably.
- **`charge` and `refund`** — the budget's two verbs, one unit (events+bytes). Every message's charge is debited from `B` at poll, measured by the ledger slot that will later return it, and refunded exactly once: when the commit covering it issues, or as a drain's `dropped` when the work never completed. That is the whole `B` accounting, and why `B = polled minus committed` stays exact. Not "released" — that word is the accumulator hand-off's; earlier drafts said "retired" (the CPU-pipeline sense), but charge/refund reads plainly beside `budget`.
- **`worker batcher` and `accumulator`**: earlier drafts split the transport into a loop-owned "sender" behind a sink trait; the accumulator hand-off (§2.1) retired both names — the batcher is whole again, and the domain's outbound face is data, not an interface. A channel's ends are `Tx`/`Rx` ("send side"/"receive side") in code and prose, so "sender" stays free of meaning. Earlier drafts also had per-stream `bin`s — buffers of placed-but-unfired work; the pack pass retired them (nothing placed outlives a pass), leaving the `accumulator` (the domain's per-cascade buffer) and the key queues as the design's only waiting rooms.

### 8.3 Cleanups this implies in today's code

Independent of the redesign; each is a small standalone chore PR.

1. Metrics `ingestion_consumer_stashed_{batches,groups,messages}` → `deferred_*` — one queue is graphed under two prefixes today, while the config surface (`CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS`, `DISPATCHER_EAGER_DEFERRED_FLUSH`) only says deferred.
2. `Stash::completed` → `routed` — its own docstring says "mark … as routed"; every other `complete_*` in the crate means finished.
3. `Stash::is_deferring` → `has_unlanded_work` — deliberately true while the queue is empty (§A.5); the name should state the predicate callers branch on.
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

## Appendix A. Inventory: what exists today and why

An index, then a subsection per construct. Each subsection states the problem, the mechanism, and the coupling cost — the part that makes the whole hard to reason about.

| # | Construct | Problem it solves |
|---|-----------|-------------------|
| A.1 | Batch collection + in-flight window | throughput vs bounded uncommitted work |
| A.2 | Oldest-first completion + commit | commit contiguity |
| A.3 | Commit sentinel + commit monitor | verifying commits actually land |
| A.4 | Sticky pins (pin table) | per-key order across concurrent batches |
| A.5 | Stash / deferral | order across worker drain, death, unroutability |
| A.6 | Completion-time flush | draining the stash; commit gate; stall watchdog |
| A.7 | Eager deferred flush | breaking the hot-key deferral cascade |
| A.8 | gRPC worker streams, ledger, fences | feed order on the wire; failure atomicity |
| A.9 | Transport retry / 503 handling | transient faults vs deliberate backpressure |
| A.10 | Body splitting + 413 handling | worker body limits without reordering |
| A.11 | Worker registry | health, drains, dead workers, discovery |
| A.12 | Routing strategies + aperture | worker spread, herd resistance, consolidation |
| A.13 | Key-order sentinel | verifying what the design can't make impossible |

### A.1 Batch collection and the in-flight window

The loop collects up to `CONSUMER_BATCH_SIZE` messages (or `CONSUMER_BATCH_SIZE_KB`, or `CONSUMER_BATCH_TIMEOUT_MS`) into a batch, and runs at most `CONSUMER_MAX_BACKGROUND_TASKS` batches concurrently — the **in-flight window** (the field is `max_in_flight_batches`; one *slot* below means one in-flight batch). The in-flight window bounds uncommitted work — the crash-replay exposure — and is the *only* source of dispatch concurrency.

**Cost:** concurrency is a fixed constant. Per-pod throughput is capped at `slots × batch / round-trip` regardless of backlog depth, and the consumer spends its wall time awaiting ACKs at low CPU — which blinds a CPU-based HPA and starves the worker pool's in-flight-based HPA at the same time: a deep backlog can sit for hours with both autoscalers reading "idle", until an operator raises `minPods` by hand. The batch is also the unit of *ownership*: every downstream mechanism (stash entries, flush loops, eager accounting) is keyed by which batch a message arrived in, a fact neither invariant cares about.

### A.2 Oldest-first completion and commit

Batches complete strictly oldest-first (`complete_oldest_batch`): await the batch's sends, flush its deferred groups, verify every message accepted, then commit its offsets. Serializing completion is how commit contiguity is enforced — batch N+1's offsets never commit before batch N's.

**Cost:** head-of-line blocking across *everything*. One wedged key in one partition holds the commits of all partitions, all batches behind it, and — once the window fills — stops collection entirely. Contiguity is a per-partition property, but it is enforced with a global serialization.

### A.3 Commit sentinel and commit monitor

`CommitSentinel` checks each commit for gaps, out-of-order, and overlaps per partition; a background monitor polls the broker's committed offsets because librdkafka drops the result of manual async commits. Pure observers.

**Cost:** none — but note *why* the sentinel earns its keep: contiguity today is an emergent property of the completion serialization plus the all-accepted check, not something any component computes. The sentinel verifies what nothing constructs.

### A.4 Sticky pins

While a key has sends in flight, it is pinned to one worker with a ref-count (`PinTable`). Pins keep a key's concurrent batches on one worker (order), are evicted at ref-count zero when nothing is deferred, and are abandoned at flush time when the pinned worker is drastically overloaded (`STICKY_PIN_LOAD_FACTOR`/`SLACK`).

**Cost:** the pin table is correct only in concert with the stash: eviction must check `is_deferring`, resolution must skip stale pins after re-points, and the ref-count discipline spans `assign`, both flush paths, and the eager path. The rules are right, but they are distributed.

### A.5 The stash (deferral)

When a key can't be sent — pinned to a draining/dead worker, or the whole pool unroutable — its group is *stashed* rather than re-routed, because its earlier messages are still in flight and re-routing would reorder the key. Critically, once a key defers once, **every newer group for it must also defer** (the cascade rule), or it would race ahead of the stashed ones. The stash orders a key's entries by batch *sequence* (registered on the consumer loop, because deferrals can arrive out of batch order), keeps per-batch live counts (so batches can complete), and per-key outstanding counts (which stay elevated from `defer` until the flushed group actually *lands*, closing the race window where a flushed-but-unACKed group could be overtaken — this is why `is_deferring` answers *does this key have unlanded work*, not *is anything physically stashed*).

**Cost:** the stash is a second queue system living beside the primary send path, with its own ordering key (batch sequence), its own occupancy accounting, and subtle state ("outstanding" ≠ "physically stashed"). All of it is per-key queueing — expressed batch-scoped.

### A.6 Completion-time flush

`flush_deferred` runs inline in `complete_oldest_batch`: re-route and send the completing batch's stashed groups, serialized oldest-batch-first (which is what preserves a key's cross-batch order), pacing retries at 200 ms when nothing is routable, and failing the process — replay from uncommitted offsets — when no progress happens for `CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS`. It is simultaneously the stash's drain path, the batch's commit gate, and the stall watchdog.

**Cost:** the drain is paced by batch completion and runs *on the consumer loop*. A continuously-sending hot key drains one group per completion while every collection adds one — it never exits deferral — and every batch's completion carries the flush round-trips inline, taxing all traffic.

### A.7 Eager deferred flush

`DISPATCHER_EAGER_DEFERRED_FLUSH` (default off) attacks A.6's pacing problem: the moment the send blocking a key resolves (pin ref-count zero, stash non-empty, send succeeded), the dispatcher pops the key's *oldest* stashed group, re-routes it, and hands it to the eager-flush task to send. Each ACK releases the next group — the chain drains at ACK round-trip speed instead of completion speed, which is what lets a hot key actually catch up and exit deferral.

**Cost:** a second drain path over the same stash, reconciled with the first through dedicated glue: `eager_pending` (batches can't commit with eager sends in flight), `eager_accepted` / `take_eager_accepted` (acceptances credited across paths), stall-deadline resets on eager progress, and `send_failed` suppression so a flapping worker doesn't tight-loop between the paths. Every subtle interaction in the dispatcher today lives at this seam. The eager path is the *correct* drain model — the completion path is what forces it to be an add-on rather than the design.

### A.8 gRPC worker streams, the ledger, and fences (#85238)

One ordered stream per worker: enqueue order is send order is the worker's feed order — the per-key guarantee concurrent HTTP requests can't give, which is why `begin_send` must be called synchronously where send order is decided (the consumer loop, the serialized flush paths, the eager loop's receive-order). The stream's ledger resolves ACKs only as a consecutive prefix (a later send must not release its keys while an earlier one can still fail), and a failure **fences the whole worker stream**: every queued and un-ACKed item is resolved in order with its messages handed back, and each carries a `FenceGuard` — the stream refuses new work until every guard is dropped, closing the race where the consumer loop could enqueue a fenced key's next group before the failure finished re-stashing.

**Cost:** the fence machinery exists because send *origination is distributed*: scatter tasks, two flush paths, and the eager-flush task all enqueue concurrently, so the stream cannot know when a failure's cleanup is complete except by explicit guard hand-off. The ledger's resolve-in-send-order rule exists because many sends ride the stream concurrently on behalf of batch-scoped callers.

### A.9 Transport retry and 503 handling

The transport distinguishes deliberate backpressure from faults: HTTP 503 (`WorkerBusy`) and stream-busy get a longer, jittered backoff (250 ms·2ⁿ capped at 5 s + jitter, vs 100 ms·2ⁿ for errors) and are **excluded from passive health** (`is_backpressure`), so a worker at capacity is throttled but not marked sick. 4xx is non-retriable; retries mark `replay` so worker-side sentinels count repeats correctly; per-worker semaphores softly cap in-flight requests to match the worker's `concurrentBatches`.

**Cost:** essentially none — this layer is well-factored and survives the redesign intact.

### A.10 Body splitting and 413

Sub-batches have no construction-time size bound, so the transport compensates: estimated-oversize bodies split into sequential order-preserving chunks under one permit, a 413 halves and resends, a single un-splittable message fails cleanly, and failures reassemble the *entire* original message set for deferral (all-or-nothing contract).

**Cost:** request size is an emergent accident of `batch ÷ fan-out` — nobody chose it. The splitting is a downstream repair for an upstream non-decision.

### A.11 Worker registry

Passive send outcomes (rolling window) combined with active `/_ready` probes drive Healthy/Degraded/Unhealthy with anti-flap dwell times. Draining workers (left the pool, e.g. a deploy) take no new work, have probe failures ignored but send failures still escalate, and are reaped when their in-flight hits zero or a deadline passes. Discovery is static or EndpointSlice-driven.

**Cost:** none structurally — but note that the *consequence* of a drain (the key must wait for in-flight, then re-route in order) is implemented far away, in the stash and its two flush paths.

### A.12 Routing strategies and the aperture

Unpinned keys route by BinPack (exclusive pools), P2C (shared pools, herd resistant), or deterministic Aperture: each consumer routes fresh keys only within its slice of the worker ring, slices tiling the pool without coordination, floored at `ceil(pool/consumers)` for coverage.

**Cost:** the aperture floor makes fan-out *topology-shaped, not load-shaped*: a batch shatters across the slice width whether it holds 40 events or 5,000. Few consumers over a large pool ⇒ many tiny requests, maximum per-request fixed cost exactly when efficiency matters most (a 5,000-event batch spread over a 32-wide slice floor comes out as ~150-event requests).

### A.13 Key-order sentinel

`KeyOrderSentinel` verifies per-key send order at assignment time and ACK regressions, distinguishing legal at-least-once replays from violations, re-baselining on rebalances.

**Cost:** none — but like A.3, it verifies a property that emerges from discipline (synchronous `begin_send` placement, register-before-assign, credit-before-resolve orderings) rather than from structure. The codebase enforces its invariants by the *care with which calls are placed*; the sentinels are the tax on that.
