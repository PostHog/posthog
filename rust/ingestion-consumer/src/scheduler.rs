//! The scheduler seam: every ordering and placement decision in the batcher,
//! behind one interface.
//!
//! The scheduler decides which runs may go to a worker now, and where.
//! Nothing else in the batcher decides that. The seam is event-shaped: a
//! group arrives (`on_groups`), a request settles with success or failure
//! (`on_settled`), a retry deadline fires (`on_deadline`). Each call is one
//! event, runs to completion, does no I/O, takes no locks, and returns its
//! effects as data: the dispatches to send, the deferral counts, and the
//! evicted keys. The caller owns the lock, the worker-health snapshot
//! ([`WorkerSnapshot`]), the in-flight load accounting, the sentinels, and the
//! sends.
//!
//! [`PinStashScheduler`] is the current semantics moved out of the
//! dispatcher: sticky pins, the stash, deferral on drain, and the
//! oldest-first flush pacing. The key-table scheduler replaces it behind
//! this same interface.

use std::collections::HashMap;

use metrics::{counter, gauge};

use crate::order_sentinel::SendKind;
use crate::routing::{Router, WorkerLoad};
use crate::stash::{DeferredGroup, Stash};
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

/// A point-in-time snapshot of the worker world, captured by the caller
/// before a seam call so the scheduler decides over data instead of querying
/// the registry and the peer tracker itself.
pub struct WorkerSnapshot {
    /// Routable workers.
    pub healthy: Vec<WorkerId>,
    /// Candidates for fresh keys: the aperture ring slice when narrowing
    /// applies, otherwise the healthy pool.
    pub candidates: Vec<WorkerId>,
    /// Outstanding messages per worker (the caller's in-flight table).
    pub load: WorkerLoad,
    /// Health per known worker. A worker absent here is dead (removed from
    /// the registry) and not draining, matching the registry's answers.
    workers: HashMap<WorkerId, WorkerHealth>,
}

pub struct WorkerHealth {
    pub dead: bool,
    pub draining: bool,
}

impl WorkerSnapshot {
    pub fn new(
        healthy: Vec<WorkerId>,
        candidates: Vec<WorkerId>,
        load: WorkerLoad,
        workers: HashMap<WorkerId, WorkerHealth>,
    ) -> Self {
        Self {
            healthy,
            candidates,
            load,
            workers,
        }
    }

    pub fn is_dead(&self, worker: &WorkerId) -> bool {
        self.workers.get(worker).is_none_or(|health| health.dead)
    }

    pub fn is_draining(&self, worker: &WorkerId) -> bool {
        self.workers
            .get(worker)
            .is_some_and(|health| health.draining)
    }
}

/// One run of one key's messages arriving at the seam.
pub struct KeyRun {
    pub routing_key: String,
    pub messages: Vec<SerializedKafkaMessage>,
}

/// One run of one key, placed on the chosen worker.
pub struct Dispatch {
    pub worker: WorkerId,
    pub routing_key: String,
    pub messages: Vec<SerializedKafkaMessage>,
    /// Fresh assignment or a retry of deferred work; the key-order sentinel
    /// notes the send under this kind.
    pub kind: SendKind,
}

/// One resolved send arriving at the seam.
pub struct Settlement {
    pub worker: WorkerId,
    /// The resolved send's message count, for the caller's load accounting;
    /// the scheduler does not read it.
    pub message_count: usize,
    /// Unique routing keys the send carried.
    pub routing_keys: Vec<String>,
    /// True when the send came from a deferred flush: the settlement then
    /// clears one deferral per key.
    pub from_flush: bool,
    pub outcome: SettlementOutcome,
}

pub enum SettlementOutcome {
    Delivered,
    /// The send failed; its runs come back for replay, already named by the
    /// caller. Requeue happens before the keys are released, in this one
    /// call, so a newer send can never overtake the failed messages.
    Failed {
        batch_id: String,
        runs: Vec<KeyRun>,
    },
}

/// Groups deferred by one seam call, by reason. The caller emits the debug
/// events from these; the scheduler emits its own counters.
#[derive(Default)]
pub struct DeferredCounts {
    /// The key's worker is draining or dead.
    pub drain: u64,
    /// The key already has deferred work; newer messages queue behind it.
    pub queued_behind_deferral: u64,
    /// No worker was routable.
    pub unroutable: u64,
    /// A failed send's messages went back to the stash.
    pub send_failed: u64,
}

impl DeferredCounts {
    pub fn total(&self) -> u64 {
        self.drain + self.queued_behind_deferral + self.unroutable + self.send_failed
    }
}

/// One seam call's effects, as data.
#[derive(Default)]
pub struct SchedulerEffects {
    /// Runs to send now, in decision order. The caller establishes send
    /// order from this order.
    pub dispatches: Vec<Dispatch>,
    pub deferred: DeferredCounts,
    /// Keys whose pins were evicted: nothing is in flight or deferred for
    /// them, so their order-sentinel state can go.
    pub evicted_keys: Vec<String>,
}

impl SchedulerEffects {
    fn with_dispatch_capacity(capacity: usize) -> Self {
        Self {
            dispatches: Vec::with_capacity(capacity),
            ..Self::default()
        }
    }
}

/// The decision core: which runs may go to a worker now, and where.
pub trait Scheduler {
    /// One poll's key runs arrived, in batch order.
    fn on_groups(
        &mut self,
        snapshot: &WorkerSnapshot,
        batch_id: &str,
        groups: Vec<KeyRun>,
    ) -> SchedulerEffects;

    /// A send settled, with success or failure.
    fn on_settled(&mut self, snapshot: &WorkerSnapshot, settlement: Settlement)
        -> SchedulerEffects;

    /// The retry deadline for `batch_id`'s deferred work fired. The batch id
    /// carries the current oldest-first pacing; the key-table scheduler
    /// generalizes this to a parked-retry deadline.
    fn on_deadline(&mut self, snapshot: &WorkerSnapshot, batch_id: &str) -> SchedulerEffects;
}

/// Sticky pin for one routing key. Tracks which worker owns the key and how
/// many in-flight batches reference it. The pin is evicted when ref_count
/// reaches 0 and the key has no deferred groups outstanding (see [`Stash`]).
pub(crate) struct Pin {
    pub(crate) worker: WorkerId,
    pub(crate) ref_count: u32,
}

/// Cap on how much more loaded a pinned worker may be than the least-loaded
/// healthy worker before a flush abandons stickiness. Beyond
/// `min_load * FACTOR + SLACK` in-flight messages the pin is ignored and the
/// group routes by load: a worker at its concurrency cap keeps 503ing the
/// flush until the batch's deferred-flush timeout kills the process, so
/// locality yields to load once the gap is this large. The slack keeps small
/// absolute gaps sticky — an idle candidate (min 0) must not disqualify a pin
/// holding a few hundred messages.
const STICKY_PIN_LOAD_FACTOR: usize = 2;
const STICKY_PIN_LOAD_SLACK: usize = 500;

/// The current scheduling semantics, moved out of the dispatcher: sticky
/// per-key pins, the deferred-message stash, and load-aware placement via the
/// configured routing strategy.
pub struct PinStashScheduler {
    /// Kafka message key → sticky assignment.
    pub(crate) pins: HashMap<String, Pin>,
    /// Messages deferred because their key's worker is draining/dead, keyed by
    /// batch, plus per-key outstanding counts. Flushed on `on_deadline`.
    pub(crate) stash: Stash,
    /// Worker selector for unpinned keys. Owned here because placement is a
    /// scheduling decision; P2C selection mutates the RNG.
    router: Router,
}

impl PinStashScheduler {
    pub fn new(router: Router) -> Self {
        Self {
            pins: HashMap::new(),
            stash: Stash::new(),
            router,
        }
    }

    /// Record a batch's arrival order for the stash. Must be called in true
    /// batch order, before `on_groups` — failed sends re-defer in gather
    /// order, so no later call site can establish the order reliably.
    pub fn register_batch(&mut self, batch_id: &str) {
        self.stash.register_batch(batch_id);
    }

    /// Forget a fully completed (committed) batch's arrival order and any
    /// leftover ledger state.
    pub fn release_batch(&mut self, batch_id: &str) {
        self.stash.release_batch(batch_id);
    }

    /// Whether `batch_id` still has deferred groups awaiting a retry.
    pub fn has_batch(&self, batch_id: &str) -> bool {
        self.stash.has_batch(batch_id)
    }

    pub fn pin_count(&self) -> usize {
        self.pins.len()
    }

    pub fn stashed_messages(&self) -> usize {
        self.stash.message_count()
    }

    pub fn stashed_batches(&self) -> usize {
        self.stash.batch_count()
    }

    /// Stash a failed send's runs for replay. Returns the number of groups
    /// stashed. Used by the failed-settlement arm, and directly by the
    /// caller's two-step test path.
    pub(crate) fn stash_failed(&mut self, batch_id: &str, runs: Vec<KeyRun>) -> u64 {
        let deferred = runs.len() as u64;
        for run in runs {
            self.stash.defer(
                batch_id,
                DeferredGroup {
                    routing_key: run.routing_key,
                    messages: run.messages,
                },
            );
        }
        record_stash_gauges(&self.stash);
        deferred
    }
}

impl Scheduler for PinStashScheduler {
    /// Per group:
    /// - honor an existing pin to a worker still taking work;
    /// - **defer** (stash under `batch_id`) a key pinned to a draining/dead
    ///   worker, or one that already has deferred groups pending, so newer
    ///   messages can't race ahead of the key's earlier ones;
    /// - otherwise route fresh via the configured strategy — or defer the
    ///   group when no worker is routable at all, so a transient full-pool
    ///   outage holds messages instead of failing the batch.
    fn on_groups(
        &mut self,
        snapshot: &WorkerSnapshot,
        batch_id: &str,
        groups: Vec<KeyRun>,
    ) -> SchedulerEffects {
        let mut effects = SchedulerEffects::with_dispatch_capacity(groups.len());

        // Working load for this round: each candidate's outstanding load,
        // bumped as groups are assigned, so intra-batch placement accounts
        // for earlier picks.
        let mut working_load: WorkerLoad = snapshot
            .healthy
            .iter()
            .map(|w| (w.clone(), snapshot.load.get(w).copied().unwrap_or(0)))
            .collect();

        let mut unpinned_groups: Vec<KeyRun> = Vec::new();

        for group in groups {
            let pinned_worker = self.pins.get(&group.routing_key).map(|p| p.worker.clone());
            match pinned_worker {
                Some(worker)
                    if !self.stash.is_deferring(&group.routing_key)
                        && !snapshot.is_dead(&worker)
                        && !snapshot.is_draining(&worker) =>
                {
                    // Live pin on a worker still taking work, nothing deferred
                    // ahead of it — honor it.
                    self.pins.get_mut(&group.routing_key).unwrap().ref_count += 1;
                    bump_load(&mut working_load, &worker, group.messages.len());
                    effects.dispatches.push(Dispatch {
                        worker,
                        routing_key: group.routing_key,
                        messages: group.messages,
                        kind: SendKind::Fresh,
                    });
                }
                Some(_) => {
                    // Pinned to a draining/dead worker, or the key already has
                    // deferred groups pending — defer so newer messages can't
                    // race ahead of the key's earlier in-flight/deferred ones.
                    // A key that is already deferring counts as cascade
                    // (queued behind its own deferred work) regardless of the
                    // pinned worker's state, so the seed (drain) and the
                    // amplification (cascade) are measured separately.
                    if self.stash.is_deferring(&group.routing_key) {
                        effects.deferred.queued_behind_deferral += 1;
                    } else {
                        effects.deferred.drain += 1;
                    }
                    self.stash.defer(
                        batch_id,
                        DeferredGroup {
                            routing_key: group.routing_key,
                            messages: group.messages,
                        },
                    );
                }
                None if self.stash.is_deferring(&group.routing_key) => {
                    // No pin, but the key already has stashed groups (it was
                    // unroutable earlier) — newer messages must queue behind
                    // them, not race ahead.
                    self.stash.defer(
                        batch_id,
                        DeferredGroup {
                            routing_key: group.routing_key,
                            messages: group.messages,
                        },
                    );
                    effects.deferred.queued_behind_deferral += 1;
                }
                None => unpinned_groups.push(group),
            }
        }

        // Route the unpinned groups via the configured strategy. Bin-packing
        // wants the biggest groups placed first so heavy hitters drive the load
        // distribution; P2C is per-group and order-independent.
        if self.router.prefers_largest_first() {
            unpinned_groups.sort_unstable_by(|a, b| b.messages.len().cmp(&a.messages.len()));
        }

        for group in unpinned_groups {
            let Some(worker) = self.router.select(&snapshot.candidates, &working_load) else {
                // No routable worker right now (e.g. the whole pool is draining
                // during a deploy overlap). Stash the group so the retry
                // deadline can route it once a worker returns — dropping it
                // would fail the whole batch and restart the process for a
                // transient condition.
                counter!("ingestion_consumer_dispatcher_unroutable_messages_total")
                    .increment(group.messages.len() as u64);
                self.stash.defer(
                    batch_id,
                    DeferredGroup {
                        routing_key: group.routing_key,
                        messages: group.messages,
                    },
                );
                effects.deferred.unroutable += 1;
                continue;
            };

            bump_load(&mut working_load, &worker, group.messages.len());
            self.pins.insert(
                group.routing_key.clone(),
                Pin {
                    worker: worker.clone(),
                    ref_count: 1,
                },
            );
            effects.dispatches.push(Dispatch {
                worker,
                routing_key: group.routing_key,
                messages: group.messages,
                kind: SendKind::Fresh,
            });
        }

        emit_deferred_counters(&effects.deferred);
        gauge!("ingestion_consumer_dispatcher_pins_total").set(self.pins.len() as f64);
        record_stash_gauges(&self.stash);

        effects
    }

    /// Subtracting the send from the caller's load table and completing a
    /// drain stay with the caller; here the settlement clears deferrals,
    /// requeues a failure, decrements ref-counts, and evicts idle pins so the
    /// key is re-assigned on its next arrival.
    fn on_settled(
        &mut self,
        _snapshot: &WorkerSnapshot,
        settlement: Settlement,
    ) -> SchedulerEffects {
        let mut effects = SchedulerEffects::default();

        if let SettlementOutcome::Failed { batch_id, runs } = settlement.outcome {
            // Re-stash the failed runs first, so the ref-count drop below
            // doesn't evict the pin while the key still has work to replay.
            // On the flush path this pairs with the `from_flush` decrement, so
            // the outstanding count nets to unchanged (never dipping to zero)
            // and the key keeps deferring across the retry.
            effects.deferred.send_failed = self.stash_failed(&batch_id, runs);
            emit_deferred_counters(&effects.deferred);
        }

        for key in &settlement.routing_keys {
            // For a flushed send, the key's flushed chunk has now landed —
            // clear one outstanding deferral before checking whether it can
            // evict.
            if settlement.from_flush {
                self.stash.completed(key);
            }
            // Don't evict a pin while the key still has deferred groups
            // awaiting a retry — new messages must keep deferring behind them
            // to preserve per-key order.
            let still_deferring = self.stash.is_deferring(key);
            if let Some(pin) = self.pins.get_mut(key) {
                // Skip stale resolves: a key's pin may have been re-pointed to
                // a different worker (e.g. by a deferred flush). A resolve
                // from the original send must not touch the new pin's
                // ref_count.
                if pin.worker != settlement.worker {
                    continue;
                }
                pin.ref_count = pin.ref_count.saturating_sub(1);
                if pin.ref_count == 0 && !still_deferring {
                    self.pins.remove(key);
                    // All sends for the key resolved and nothing is deferred —
                    // its order-sentinel history has nothing left to check.
                    effects.evicted_keys.push(key.clone());
                }
            }
        }

        gauge!("ingestion_consumer_dispatcher_pins_total").set(self.pins.len() as f64);
        record_stash_gauges(&self.stash);

        effects
    }

    /// Retry `batch_id`'s deferred groups: route each to a healthy worker now
    /// that the key's earlier in-flight has resolved, re-pinning it. Groups
    /// that can't route yet (no healthy worker) stay stashed for the next
    /// deadline. Cross-key order is preserved because the caller fires
    /// deadlines oldest batch first.
    fn on_deadline(&mut self, snapshot: &WorkerSnapshot, batch_id: &str) -> SchedulerEffects {
        let groups = self.stash.take_batch(batch_id);
        if groups.is_empty() {
            return SchedulerEffects::default();
        }

        let mut effects = SchedulerEffects::with_dispatch_capacity(groups.len());
        let mut working_load: WorkerLoad = snapshot
            .healthy
            .iter()
            .map(|w| (w.clone(), snapshot.load.get(w).copied().unwrap_or(0)))
            .collect();

        for group in groups {
            // Prefer the key's existing pin when it still points to a healthy
            // worker, so a key deferred across several batches re-homes to a
            // single survivor — preserving per-key (person-batching)
            // locality instead of scattering its messages across workers.
            // Fall back to load-based selection for a fresh key, when the
            // pinned worker is itself unhealthy (e.g. the drainer we're
            // leaving), or when it is far more loaded than the rest of the
            // pool (a saturated worker bounces the flush with 503s until the
            // batch times out — see `sticky_pin_for`).
            let sticky = sticky_pin_for(
                &self.pins,
                &group.routing_key,
                &snapshot.healthy,
                &working_load,
            );
            let worker = match sticky {
                Some(worker) => worker,
                None => {
                    let Some(worker) = self.router.select(&snapshot.healthy, &working_load) else {
                        // No healthy worker yet — keep it stashed for a later
                        // deadline.
                        self.stash.put_back(batch_id, group);
                        continue;
                    };
                    worker
                }
            };
            bump_load(&mut working_load, &worker, group.messages.len());
            // Re-pin the key to the new worker. The deferral is NOT cleared here:
            // the flushed messages are now in flight but not yet ACKed, so the key
            // must keep deferring until that send resolves (see the `from_flush`
            // path in `on_settled`). Otherwise a newer batch could honor
            // this fresh pin and race the not-yet-landed flushed messages.
            match self.pins.get_mut(&group.routing_key) {
                Some(pin) => {
                    pin.worker = worker.clone();
                    pin.ref_count += 1;
                }
                None => {
                    self.pins.insert(
                        group.routing_key.clone(),
                        Pin {
                            worker: worker.clone(),
                            ref_count: 1,
                        },
                    );
                }
            }
            effects.dispatches.push(Dispatch {
                worker,
                routing_key: group.routing_key,
                messages: group.messages,
                kind: SendKind::Resend,
            });
        }

        gauge!("ingestion_consumer_dispatcher_pins_total").set(self.pins.len() as f64);
        record_stash_gauges(&self.stash);

        effects
    }
}

/// The key's pinned worker, if the pin may be honored for a flush: it must be
/// healthy and not drastically more loaded than the least-loaded candidate
/// (see `STICKY_PIN_LOAD_FACTOR`). Only consulted at flush time, when the key
/// has no send in flight — so declining the pin and routing elsewhere cannot
/// reorder the key.
fn sticky_pin_for(
    pins: &HashMap<String, Pin>,
    routing_key: &str,
    healthy: &[WorkerId],
    working_load: &WorkerLoad,
) -> Option<WorkerId> {
    let worker = pins.get(routing_key).map(|pin| pin.worker.clone())?;
    if !healthy.contains(&worker) {
        return None;
    }
    let pinned_load = working_load.get(&worker).copied().unwrap_or(0);
    let min_load = healthy
        .iter()
        .map(|w| working_load.get(w).copied().unwrap_or(0))
        .min()
        .unwrap_or(0);
    if pinned_load > min_load.saturating_mul(STICKY_PIN_LOAD_FACTOR) + STICKY_PIN_LOAD_SLACK {
        counter!("ingestion_consumer_dispatcher_sticky_pin_overrides_total").increment(1);
        return None;
    }
    Some(worker)
}

/// Add `count` to a worker's working load for this round, if it is a candidate.
/// Workers that aren't routing candidates (e.g. a pin honored on an unhealthy
/// worker) have no entry and don't affect selection, so they're skipped.
fn bump_load(working_load: &mut WorkerLoad, worker: &WorkerId, count: usize) {
    if let Some(load) = working_load.get_mut(worker) {
        *load = load.saturating_add(count);
    }
}

fn emit_deferred_counters(deferred: &DeferredCounts) {
    for (reason, count) in [
        ("drain", deferred.drain),
        ("queued_behind_deferral", deferred.queued_behind_deferral),
        ("unroutable", deferred.unroutable),
        ("send_failed", deferred.send_failed),
    ] {
        if count > 0 {
            counter!(
                "ingestion_consumer_dispatcher_deferred_groups_total",
                "reason" => reason,
            )
            .increment(count);
        }
    }
}

/// Publish point-in-time stash depth so a drain's backlog is observable and can
/// be alerted on if it fails to drain to zero. Call after every mutation.
fn record_stash_gauges(stash: &Stash) {
    gauge!("ingestion_consumer_dispatcher_stashed_batches").set(stash.batch_count() as f64);
    gauge!("ingestion_consumer_dispatcher_stashed_groups").set(stash.len() as f64);
    gauge!("ingestion_consumer_dispatcher_stashed_messages").set(stash.message_count() as f64);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::routing::RoutingStrategy;

    const A: &str = "http://worker:1";
    const B: &str = "http://worker:2";

    fn wid(s: &str) -> WorkerId {
        WorkerId::from(s)
    }

    fn msg(key: &str) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            topic: "test".to_string(),
            partition: 0,
            offset: 0,
            timestamp: 0,
            key: Some(key.to_string()),
            value: None,
            headers: HashMap::new(),
        }
    }

    fn run(key: &str, n: usize) -> KeyRun {
        KeyRun {
            routing_key: key.to_string(),
            messages: (0..n).map(|_| msg(key)).collect(),
        }
    }

    /// Snapshot where every listed worker is live, with the given loads.
    /// Workers in `draining` are marked draining (and excluded from
    /// healthy/candidates, matching what the dispatcher passes). Workers not
    /// listed at all are absent from the health map, i.e. dead.
    fn snapshot(live: &[&str], draining: &[&str], load: &[(&str, usize)]) -> WorkerSnapshot {
        let healthy: Vec<WorkerId> = live.iter().map(|w| wid(w)).collect();
        let mut workers: HashMap<WorkerId, WorkerHealth> = HashMap::new();
        for w in live {
            workers.insert(
                wid(w),
                WorkerHealth {
                    dead: false,
                    draining: false,
                },
            );
        }
        for w in draining {
            workers.insert(
                wid(w),
                WorkerHealth {
                    dead: false,
                    draining: true,
                },
            );
        }
        let load: WorkerLoad = load.iter().map(|(w, n)| (wid(w), *n)).collect();
        WorkerSnapshot::new(healthy.clone(), healthy, load, workers)
    }

    fn scheduler() -> PinStashScheduler {
        PinStashScheduler::new(Router::with_seed(RoutingStrategy::BinPack, 0))
    }

    fn delivered(worker: &str, keys: &[&str], from_flush: bool) -> Settlement {
        Settlement {
            worker: wid(worker),
            message_count: keys.len(),
            routing_keys: keys.iter().map(|k| k.to_string()).collect(),
            from_flush,
            outcome: SettlementOutcome::Delivered,
        }
    }

    fn failed(worker: &str, batch_id: &str, runs: Vec<KeyRun>, from_flush: bool) -> Settlement {
        Settlement {
            worker: wid(worker),
            message_count: runs.iter().map(|r| r.messages.len()).sum(),
            routing_keys: runs.iter().map(|r| r.routing_key.clone()).collect(),
            from_flush,
            outcome: SettlementOutcome::Failed {
                batch_id: batch_id.to_string(),
                runs,
            },
        }
    }

    // ---- on_groups: placement ----

    #[test]
    fn test_fresh_key_is_routed_pinned_and_dispatched_fresh() {
        let mut sched = scheduler();
        sched.register_batch("b1");

        let effects = sched.on_groups(&snapshot(&[A], &[], &[]), "b1", vec![run("t:a", 2)]);

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].worker, wid(A));
        assert_eq!(effects.dispatches[0].kind, SendKind::Fresh);
        assert_eq!(effects.deferred.total(), 0);
        let pin = sched.pins.get("t:a").expect("key is pinned");
        assert_eq!(pin.ref_count, 1);
    }

    #[test]
    fn test_pinned_key_sticks_to_its_worker_despite_load() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        sched.on_groups(&snapshot(&[A], &[], &[]), "b1", vec![run("t:a", 1)]);

        // B is now available and far less loaded — the pin still wins.
        sched.register_batch("b2");
        let effects = sched.on_groups(
            &snapshot(&[A, B], &[], &[(A, 10_000)]),
            "b2",
            vec![run("t:a", 1)],
        );

        assert_eq!(effects.dispatches[0].worker, wid(A));
        assert_eq!(sched.pins.get("t:a").unwrap().ref_count, 2);
    }

    #[test]
    fn test_intra_batch_placement_accounts_for_earlier_picks() {
        let mut sched = scheduler();
        sched.register_batch("b1");

        // Two fresh equal-size groups, two idle workers: the first pick must
        // bump the working load so the second group lands on the other worker.
        let effects = sched.on_groups(
            &snapshot(&[A, B], &[], &[]),
            "b1",
            vec![run("t:a", 3), run("t:b", 3)],
        );

        assert_eq!(effects.dispatches.len(), 2);
        assert_ne!(effects.dispatches[0].worker, effects.dispatches[1].worker);
    }

    #[test]
    fn test_binpack_places_largest_group_first() {
        let mut sched = scheduler();
        sched.register_batch("b1");

        let effects = sched.on_groups(
            &snapshot(&[A, B], &[], &[]),
            "b1",
            vec![run("t:small", 1), run("t:big", 5)],
        );

        assert_eq!(
            effects.dispatches[0].routing_key, "t:big",
            "heavy hitters drive the load distribution"
        );
    }

    #[test]
    fn test_unroutable_group_is_stashed_not_dropped() {
        let mut sched = scheduler();
        sched.register_batch("b1");

        let effects = sched.on_groups(&snapshot(&[], &[], &[]), "b1", vec![run("t:a", 2)]);

        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.unroutable, 1);
        assert_eq!(sched.pin_count(), 0, "an unrouted group takes no pin");
        assert!(sched.has_batch("b1"));
        assert_eq!(sched.stashed_messages(), 2);
    }

    // ---- on_groups: deferral ----

    #[test]
    fn test_pinned_key_defers_when_worker_draining() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        sched.on_groups(&snapshot(&[A, B], &[], &[]), "b1", vec![run("t:a", 1)]);
        let pinned = sched.pins.get("t:a").unwrap().worker.clone();
        let pinned_str = pinned.to_string();

        sched.register_batch("b2");
        let survivor = if pinned == wid(A) { B } else { A };
        let effects = sched.on_groups(
            &snapshot(&[survivor], &[&pinned_str], &[]),
            "b2",
            vec![run("t:a", 1)],
        );

        assert!(effects.dispatches.is_empty(), "must not reorder the key");
        assert_eq!(effects.deferred.drain, 1);
        assert!(sched.has_batch("b2"));
    }

    #[test]
    fn test_pinned_key_defers_when_worker_absent_from_snapshot() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        sched.on_groups(&snapshot(&[A], &[], &[]), "b1", vec![run("t:a", 1)]);

        // A is gone from the health map entirely (removed from the registry):
        // absent must count as dead, not as healthy.
        sched.register_batch("b2");
        let effects = sched.on_groups(&snapshot(&[B], &[], &[]), "b2", vec![run("t:a", 1)]);

        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.drain, 1);
    }

    #[test]
    fn test_deferring_key_keeps_deferring_even_when_worker_recovers() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        sched.on_groups(&snapshot(&[A], &[], &[]), "b1", vec![run("t:a", 1)]);
        sched.register_batch("b2");
        sched.on_groups(&snapshot(&[B], &[A], &[]), "b2", vec![run("t:a", 1)]);

        // A is healthy again, but b2's deferred group hasn't flushed — newer
        // messages must queue behind it, and count as cascade, not drain.
        sched.register_batch("b3");
        let effects = sched.on_groups(&snapshot(&[A, B], &[], &[]), "b3", vec![run("t:a", 1)]);

        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.queued_behind_deferral, 1);
        assert_eq!(effects.deferred.drain, 0);
    }

    #[test]
    fn test_unpinned_key_queues_behind_its_stashed_groups() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        // Unroutable: stashed with no pin.
        sched.on_groups(&snapshot(&[], &[], &[]), "b1", vec![run("t:a", 1)]);

        // A worker appears, but the stashed group must go first.
        sched.register_batch("b2");
        let effects = sched.on_groups(&snapshot(&[A], &[], &[]), "b2", vec![run("t:a", 1)]);

        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.queued_behind_deferral, 1);
    }

    // ---- on_settled ----

    #[test]
    fn test_settlement_evicts_idle_pin() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        sched.on_groups(&snapshot(&[A], &[], &[]), "b1", vec![run("t:a", 1)]);

        let effects = sched.on_settled(&snapshot(&[A], &[], &[]), delivered(A, &["t:a"], false));

        assert_eq!(effects.evicted_keys, vec!["t:a".to_string()]);
        assert_eq!(sched.pin_count(), 0);
    }

    #[test]
    fn test_settlement_keeps_pin_while_key_still_defers() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        sched.on_groups(&snapshot(&[A], &[], &[]), "b1", vec![run("t:a", 1)]);
        sched.register_batch("b2");
        sched.on_groups(&snapshot(&[B], &[A], &[]), "b2", vec![run("t:a", 1)]);

        // b1's send lands, dropping the ref-count to zero — but b2's deferred
        // group is still stashed, so the pin must survive for it.
        let effects = sched.on_settled(&snapshot(&[B], &[A], &[]), delivered(A, &["t:a"], false));

        assert!(effects.evicted_keys.is_empty());
        assert_eq!(sched.pin_count(), 1);
    }

    #[test]
    fn test_stale_settlement_does_not_touch_repointed_pin() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        sched.on_groups(&snapshot(&[A], &[], &[]), "b1", vec![run("t:a", 1)]);
        sched.register_batch("b2");
        sched.on_groups(&snapshot(&[B], &[A], &[]), "b2", vec![run("t:a", 1)]);

        // The deferred flush re-points the pin to B while b1's send is still
        // unresolved on A.
        let effects = sched.on_deadline(&snapshot(&[B], &[A], &[]), "b2");
        assert_eq!(effects.dispatches[0].worker, wid(B));
        let ref_count = sched.pins.get("t:a").unwrap().ref_count;

        // b1's resolve from A must not decrement the new pin's ref-count.
        let effects = sched.on_settled(&snapshot(&[B], &[A], &[]), delivered(A, &["t:a"], false));

        assert!(effects.evicted_keys.is_empty());
        assert_eq!(sched.pins.get("t:a").unwrap().ref_count, ref_count);
    }

    #[test]
    fn test_failed_settlement_restashes_before_releasing_the_key() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        sched.on_groups(&snapshot(&[A, B], &[], &[]), "b1", vec![run("t:a", 2)]);

        let effects = sched.on_settled(
            &snapshot(&[A, B], &[], &[]),
            failed(A, "b1", vec![run("t:a", 2)], false),
        );

        assert_eq!(effects.deferred.send_failed, 1);
        assert!(
            effects.evicted_keys.is_empty(),
            "the pin must survive: the key still has work to replay"
        );
        assert_eq!(sched.stashed_messages(), 2);

        // Newer messages queue behind the replay instead of overtaking it.
        sched.register_batch("b2");
        let effects = sched.on_groups(&snapshot(&[A, B], &[], &[]), "b2", vec![run("t:a", 1)]);
        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.queued_behind_deferral, 1);
    }

    #[test]
    fn test_failed_flush_keeps_key_deferring() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        sched.on_groups(&snapshot(&[], &[], &[]), "b1", vec![run("t:a", 1)]);
        let effects = sched.on_deadline(&snapshot(&[A], &[], &[]), "b1");
        assert_eq!(effects.dispatches.len(), 1);

        // The flushed send fails: the re-stash and the from_flush decrement
        // must net out so the key never stops deferring across the retry.
        sched.on_settled(
            &snapshot(&[A], &[], &[]),
            failed(A, "b1", vec![run("t:a", 1)], true),
        );

        sched.register_batch("b2");
        let effects = sched.on_groups(&snapshot(&[A], &[], &[]), "b2", vec![run("t:a", 1)]);
        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.queued_behind_deferral, 1);
    }

    // ---- on_deadline ----

    #[test]
    fn test_deadline_with_nothing_stashed_is_a_noop() {
        let mut sched = scheduler();

        let effects = sched.on_deadline(&snapshot(&[A], &[], &[]), "b1");

        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.total(), 0);
        assert!(effects.evicted_keys.is_empty());
    }

    #[test]
    fn test_deadline_keeps_group_stashed_when_no_worker_is_healthy() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        sched.on_groups(&snapshot(&[], &[], &[]), "b1", vec![run("t:a", 1)]);

        let effects = sched.on_deadline(&snapshot(&[], &[], &[]), "b1");

        assert!(effects.dispatches.is_empty());
        assert!(sched.has_batch("b1"), "kept for a later deadline");
        assert_eq!(sched.stashed_messages(), 1);
    }

    #[test]
    fn test_flushed_key_keeps_deferring_until_the_flush_settles() {
        let mut sched = scheduler();
        sched.register_batch("b1");
        sched.on_groups(&snapshot(&[A], &[], &[]), "b1", vec![run("t:a", 1)]);
        sched.register_batch("b2");
        sched.on_groups(&snapshot(&[B], &[A], &[]), "b2", vec![run("t:a", 1)]);
        sched.on_settled(&snapshot(&[B], &[A], &[]), delivered(A, &["t:a"], false));

        let effects = sched.on_deadline(&snapshot(&[B], &[A], &[]), "b2");
        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].kind, SendKind::Resend);
        assert_eq!(
            effects.dispatches[0].worker,
            wid(B),
            "re-pinned off the drainer"
        );

        // The flushed send is in flight but not ACKed — newer messages must
        // not honor the fresh pin and race it.
        sched.register_batch("b3");
        let effects = sched.on_groups(&snapshot(&[B], &[A], &[]), "b3", vec![run("t:a", 1)]);
        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.queued_behind_deferral, 1);

        // The flush ACKs: the deferral clears, the pin evicts, b3's group is
        // free to flush and the key's life cycle ends clean.
        let effects = sched.on_settled(&snapshot(&[B], &[A], &[]), delivered(B, &["t:a"], true));
        assert!(effects.evicted_keys.is_empty(), "b3's group still stashed");
        let effects = sched.on_deadline(&snapshot(&[B], &[A], &[]), "b3");
        assert_eq!(effects.dispatches.len(), 1);
        let effects = sched.on_settled(&snapshot(&[B], &[A], &[]), delivered(B, &["t:a"], true));
        assert_eq!(effects.evicted_keys, vec!["t:a".to_string()]);
        assert_eq!(sched.pin_count(), 0);
        assert_eq!(sched.stashed_messages(), 0);
    }

    // ---- sticky pin at flush time ----

    #[test]
    fn test_sticky_pin_honored_when_healthy_and_load_comparable() {
        let mut pins = HashMap::new();
        pins.insert(
            "t:a".to_string(),
            Pin {
                worker: wid(A),
                ref_count: 1,
            },
        );
        let healthy = [wid(A), wid(B)];
        // Load within min * FACTOR + SLACK: an idle candidate must not
        // disqualify a pin holding a few hundred messages.
        let load: WorkerLoad = [(wid(A), STICKY_PIN_LOAD_SLACK), (wid(B), 0)].into();

        assert_eq!(sticky_pin_for(&pins, "t:a", &healthy, &load), Some(wid(A)));

        let load: WorkerLoad = [(wid(A), STICKY_PIN_LOAD_SLACK + 1), (wid(B), 0)].into();
        assert_eq!(
            sticky_pin_for(&pins, "t:a", &healthy, &load),
            None,
            "beyond the slack the pin yields to load"
        );
    }

    #[test]
    fn test_sticky_pin_declined_when_worker_unhealthy() {
        let mut pins = HashMap::new();
        pins.insert(
            "t:a".to_string(),
            Pin {
                worker: wid(A),
                ref_count: 1,
            },
        );

        assert_eq!(
            sticky_pin_for(&pins, "t:a", &[wid(B)], &WorkerLoad::new()),
            None
        );
        assert_eq!(
            sticky_pin_for(&pins, "t:other", &[wid(A)], &WorkerLoad::new()),
            None,
            "no pin, no stickiness"
        );
    }
}
