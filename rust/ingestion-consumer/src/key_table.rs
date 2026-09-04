//! The key-table scheduler: at most one request per key is in flight.
//!
//! The key table holds one FIFO queue per routing key, an outstanding flag,
//! and a parked list. A key is runnable when it has queued work and no
//! outstanding request. Arrival enqueues and dispatches a runnable key's
//! queued run; a dispatch marks the key outstanding. A delivered settlement
//! clears the flag and dispatches the key's next run. A failed settlement
//! returns the run to the front of its queue, then clears the flag — requeue
//! before release, in one seam call — and parks the key. The parked-retry
//! deadline ([`Deadline::ParkedRetry`]) covers the keys no settlement can
//! release: unroutable groups, and keys behind a failed send.
//!
//! At most one outstanding request per key preserves per-key order. Nothing
//! else does, and nothing else must: placement is stateless — the configured
//! router picks a worker per dispatch, with no pins and no stash.
//!
//! Not selected by any production caller yet; the scheduler switch is the
//! next change.

use std::collections::{HashMap, VecDeque};

use metrics::{counter, gauge};

use crate::order_sentinel::SendKind;
use crate::routing::{Router, WorkerLoad};
use crate::scheduler::{
    bump_load, working_load, Deadline, Dispatch, KeyRun, Scheduler, SchedulerEffects, Settlement,
    SettlementOutcome, WorkerSnapshot,
};
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

/// One key's scheduling state.
struct KeyState {
    /// Queued messages in arrival order. A failed run returns to the front.
    queue: VecDeque<SerializedKafkaMessage>,
    /// A request for this key is in flight. No second dispatch may happen
    /// until it settles.
    outstanding: bool,
    /// The key waits for the parked-retry deadline. A parked key is never
    /// outstanding: it parks only when nothing of its is in flight.
    parked: bool,
}

impl KeyState {
    fn new() -> Self {
        Self {
            queue: VecDeque::new(),
            outstanding: false,
            parked: false,
        }
    }
}

/// Per-key FIFO queues, outstanding flags, and the parked list.
#[derive(Default)]
pub struct KeyTable {
    keys: HashMap<String, KeyState>,
    /// Keys awaiting the parked-retry deadline, in park order, so retries
    /// preserve arrival fairness across keys.
    parked: Vec<String>,
    /// Total queued messages across all keys, kept incrementally for the
    /// gauges.
    queued_messages: usize,
    outstanding_keys: usize,
}

impl KeyTable {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn key_count(&self) -> usize {
        self.keys.len()
    }

    pub fn queued_messages(&self) -> usize {
        self.queued_messages
    }

    pub fn outstanding_keys(&self) -> usize {
        self.outstanding_keys
    }

    pub fn parked_keys(&self) -> usize {
        self.parked.len()
    }

    /// Whether the key may dispatch now: queued work, nothing outstanding,
    /// not waiting for the parked-retry deadline.
    fn is_runnable(&self, key: &str) -> bool {
        self.keys
            .get(key)
            .is_some_and(|state| !state.queue.is_empty() && !state.outstanding && !state.parked)
    }

    /// Append messages to the key's queue, creating the key when new.
    fn enqueue_back(&mut self, key: &str, messages: Vec<SerializedKafkaMessage>) {
        self.queued_messages += messages.len();
        self.keys
            .entry(key.to_string())
            .or_insert_with(KeyState::new)
            .queue
            .extend(messages);
    }

    /// Return a failed run to the front of its queue, ahead of anything that
    /// arrived while the run was in flight, so the replay keeps offset order.
    fn requeue_front(&mut self, key: &str, messages: Vec<SerializedKafkaMessage>) {
        self.queued_messages += messages.len();
        let state = self
            .keys
            .entry(key.to_string())
            .or_insert_with(KeyState::new);
        for message in messages.into_iter().rev() {
            state.queue.push_front(message);
        }
    }

    /// Drain the key's queue into one run and mark the key outstanding.
    /// Call only on a runnable or parked-and-retried key.
    fn take_run(&mut self, key: &str) -> Vec<SerializedKafkaMessage> {
        let state = self.keys.get_mut(key).expect("key exists when dispatched");
        debug_assert!(!state.outstanding, "at most one request per key");
        let run: Vec<SerializedKafkaMessage> = state.queue.drain(..).collect();
        self.queued_messages -= run.len();
        state.outstanding = true;
        state.parked = false;
        self.outstanding_keys += 1;
        run
    }

    /// Put the key on the parked list, to be retried at the parked-retry
    /// deadline. A no-op when it is already parked.
    fn park(&mut self, key: &str) {
        let state = self
            .keys
            .entry(key.to_string())
            .or_insert_with(KeyState::new);
        if !state.parked {
            state.parked = true;
            self.parked.push(key.to_string());
        }
    }

    /// Take the parked list for one retry pass. Keys that still cannot route
    /// go back via [`KeyTable::repark`]; their `parked` flag stays set so
    /// arrivals keep queueing behind them in the meantime.
    fn take_parked(&mut self) -> Vec<String> {
        std::mem::take(&mut self.parked)
    }

    /// Restore a key's parked-list entry after a retry pass could not route
    /// it. Its `parked` flag never dropped, so only the entry returns.
    fn repark(&mut self, key: String) {
        self.parked.push(key);
    }

    /// Messages queued for the key.
    fn queued_len(&self, key: &str) -> usize {
        self.keys.get(key).map_or(0, |state| state.queue.len())
    }

    /// Clear the key's outstanding flag when its request settles. Returns
    /// false for a key this table is not tracking as outstanding — a stale
    /// settlement to ignore.
    fn settle_key(&mut self, key: &str) -> bool {
        match self.keys.get_mut(key) {
            Some(state) if state.outstanding => {
                state.outstanding = false;
                self.outstanding_keys -= 1;
                true
            }
            _ => false,
        }
    }

    /// Drop the key when nothing is queued, outstanding, or parked, so its
    /// order-sentinel state can go too. Returns true when it was removed.
    fn evict_if_idle(&mut self, key: &str) -> bool {
        let idle = self
            .keys
            .get(key)
            .is_some_and(|state| state.queue.is_empty() && !state.outstanding && !state.parked);
        if idle {
            self.keys.remove(key);
        }
        idle
    }
}

/// The target scheduler: the key table plus stateless placement via the
/// configured routing strategy (P2C within the aperture slice, or bin-pack).
pub struct KeyTableScheduler {
    table: KeyTable,
    router: Router,
}

impl KeyTableScheduler {
    pub fn new(router: Router) -> Self {
        Self {
            table: KeyTable::new(),
            router,
        }
    }

    pub fn table(&self) -> &KeyTable {
        &self.table
    }

    /// Route the key's queued run to a worker, or park the key when no worker
    /// is routable. `pool` is the candidate set for this dispatch kind.
    fn dispatch_or_park(
        &mut self,
        pool: &[WorkerId],
        working_load: &mut WorkerLoad,
        key: &str,
        kind: SendKind,
        effects: &mut SchedulerEffects,
    ) {
        let Some(worker) = self.router.select(pool, working_load) else {
            counter!("ingestion_consumer_dispatcher_unroutable_messages_total")
                .increment(self.table.queued_len(key) as u64);
            self.table.park(key);
            effects.deferred.unroutable += 1;
            return;
        };
        let messages = self.table.take_run(key);
        bump_load(working_load, &worker, messages.len());
        effects.dispatches.push(Dispatch {
            worker,
            routing_key: key.to_string(),
            messages,
            kind,
        });
    }

    fn record_gauges(&self) {
        gauge!("ingestion_consumer_key_table_keys").set(self.table.key_count() as f64);
        gauge!("ingestion_consumer_key_table_queued_messages")
            .set(self.table.queued_messages() as f64);
        gauge!("ingestion_consumer_key_table_outstanding_keys")
            .set(self.table.outstanding_keys() as f64);
        gauge!("ingestion_consumer_key_table_parked_keys").set(self.table.parked_keys() as f64);
    }
}

impl Scheduler for KeyTableScheduler {
    /// Enqueue each run, then dispatch every runnable key it touched. A key
    /// that is outstanding or parked just queues the new messages — they go
    /// out behind the earlier ones, when the request settles or the parked
    /// retry fires.
    fn on_groups(
        &mut self,
        snapshot: &WorkerSnapshot,
        _batch_id: &str,
        groups: Vec<KeyRun>,
    ) -> SchedulerEffects {
        let mut effects = SchedulerEffects::with_dispatch_capacity(groups.len());
        let mut load = working_load(snapshot);

        let mut touched: Vec<String> = Vec::with_capacity(groups.len());
        for group in groups {
            if !touched.contains(&group.routing_key) {
                touched.push(group.routing_key.clone());
            }
            self.table.enqueue_back(&group.routing_key, group.messages);
        }
        touched.retain(|key| self.table.is_runnable(key));

        // Bin-packing wants the biggest runs placed first so heavy hitters
        // drive the load distribution; P2C is per-run and order-independent.
        if self.router.prefers_largest_first() {
            touched.sort_by_key(|key| std::cmp::Reverse(self.table.queued_len(key)));
        }

        // Fresh work routes within the aperture slice, like an unpinned key
        // in the pin-stash scheduler.
        let candidates = snapshot.candidates.clone();
        for key in touched {
            self.dispatch_or_park(&candidates, &mut load, &key, SendKind::Fresh, &mut effects);
        }

        self.record_gauges();
        effects
    }

    /// Clear each settled key. Success dispatches the key's next run, or
    /// evicts an emptied key. Failure requeues the failed runs at the front
    /// of their queues, then clears the flags — requeue before release, so a
    /// newer send can never overtake the failed messages — and parks the keys
    /// for the parked-retry deadline.
    fn on_settled(
        &mut self,
        snapshot: &WorkerSnapshot,
        settlement: Settlement,
    ) -> SchedulerEffects {
        let mut effects = SchedulerEffects::default();
        let mut load = working_load(snapshot);
        let candidates = snapshot.candidates.clone();

        match settlement.outcome {
            SettlementOutcome::Delivered => {
                for key in &settlement.routing_keys {
                    if !self.table.settle_key(key) {
                        continue;
                    }
                    if self.table.is_runnable(key) {
                        self.dispatch_or_park(
                            &candidates,
                            &mut load,
                            key,
                            SendKind::Fresh,
                            &mut effects,
                        );
                    } else if self.table.evict_if_idle(key) {
                        effects.evicted_keys.push(key.clone());
                    }
                }
            }
            SettlementOutcome::Failed { runs, .. } => {
                effects.deferred.send_failed = runs.len() as u64;
                for run in runs {
                    self.table.requeue_front(&run.routing_key, run.messages);
                }
                for key in &settlement.routing_keys {
                    self.table.settle_key(key);
                    // Failed work waits for the parked-retry deadline instead
                    // of retrying at once, so a failing worker pool gets a
                    // pause before the replay.
                    self.table.park(key);
                }
            }
        }

        self.record_gauges();
        effects
    }

    /// Retry every parked key: dispatch the ones that can route now, keep the
    /// rest parked for the next deadline. The per-batch arm belongs to the
    /// pin-stash scheduler and is a no-op here.
    fn on_deadline(
        &mut self,
        snapshot: &WorkerSnapshot,
        deadline: Deadline<'_>,
    ) -> SchedulerEffects {
        let Deadline::ParkedRetry = deadline else {
            return SchedulerEffects::default();
        };

        let parked = self.table.take_parked();
        let mut effects = SchedulerEffects::with_dispatch_capacity(parked.len());
        let mut load = working_load(snapshot);

        for key in parked {
            // A retry escapes the aperture slice and routes over the whole
            // healthy pool, like a deferred flush: the slice may be exactly
            // what the key could not route into.
            let Some(worker) = self.router.select(&snapshot.healthy, &load) else {
                self.table.repark(key);
                continue;
            };
            let messages = self.table.take_run(&key);
            bump_load(&mut load, &worker, messages.len());
            counter!("ingestion_consumer_parked_retries_total").increment(1);
            effects.dispatches.push(Dispatch {
                worker,
                routing_key: key,
                messages,
                kind: SendKind::Resend,
            });
        }

        self.record_gauges();
        effects
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;
    use crate::routing::RoutingStrategy;
    use crate::scheduler::WorkerHealth;

    const A: &str = "http://worker:1";
    const B: &str = "http://worker:2";

    fn wid(s: &str) -> WorkerId {
        WorkerId::from(s)
    }

    fn msg(key: &str, offset: i64) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            topic: "test".to_string(),
            partition: 0,
            offset,
            timestamp: 0,
            key: Some(key.to_string()),
            value: None,
            headers: HashMap::new(),
        }
    }

    fn run(key: &str, offsets: &[i64]) -> KeyRun {
        KeyRun {
            routing_key: key.to_string(),
            messages: offsets.iter().map(|o| msg(key, *o)).collect(),
        }
    }

    /// Snapshot where every listed worker is live, with the given loads and
    /// candidates equal to the healthy pool.
    fn snapshot(live: &[&str], load: &[(&str, usize)]) -> WorkerSnapshot {
        snapshot_narrowed(live, live, load)
    }

    /// Snapshot with an aperture-narrowed candidate slice.
    fn snapshot_narrowed(
        live: &[&str],
        candidates: &[&str],
        load: &[(&str, usize)],
    ) -> WorkerSnapshot {
        let healthy: Vec<WorkerId> = live.iter().map(|w| wid(w)).collect();
        let candidates: Vec<WorkerId> = candidates.iter().map(|w| wid(w)).collect();
        let workers: HashMap<WorkerId, WorkerHealth> = live
            .iter()
            .map(|w| {
                (
                    wid(w),
                    WorkerHealth {
                        dead: false,
                        draining: false,
                    },
                )
            })
            .collect();
        let load: WorkerLoad = load.iter().map(|(w, n)| (wid(w), *n)).collect();
        WorkerSnapshot::new(healthy, candidates, load, workers)
    }

    fn scheduler() -> KeyTableScheduler {
        KeyTableScheduler::new(Router::with_seed(RoutingStrategy::BinPack, 0))
    }

    fn delivered(worker: &str, keys: &[&str]) -> Settlement {
        Settlement {
            worker: wid(worker),
            message_count: keys.len(),
            routing_keys: keys.iter().map(|k| k.to_string()).collect(),
            from_flush: false,
            outcome: SettlementOutcome::Delivered,
        }
    }

    fn failed(worker: &str, runs: Vec<KeyRun>) -> Settlement {
        Settlement {
            worker: wid(worker),
            message_count: runs.iter().map(|r| r.messages.len()).sum(),
            routing_keys: runs.iter().map(|r| r.routing_key.clone()).collect(),
            from_flush: false,
            outcome: SettlementOutcome::Failed {
                batch_id: "b".to_string(),
                runs,
            },
        }
    }

    fn offsets_of(dispatch: &Dispatch) -> Vec<i64> {
        dispatch.messages.iter().map(|m| m.offset).collect()
    }

    // ---- on_groups: arrival ----

    #[test]
    fn test_fresh_key_dispatches_its_whole_run_and_goes_outstanding() {
        let mut sched = scheduler();

        let effects = sched.on_groups(&snapshot(&[A], &[]), "b1", vec![run("t:a", &[1, 2])]);

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].worker, wid(A));
        assert_eq!(effects.dispatches[0].kind, SendKind::Fresh);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2]);
        assert_eq!(effects.deferred.total(), 0);
        assert_eq!(sched.table().outstanding_keys(), 1);
        assert_eq!(sched.table().queued_messages(), 0);
    }

    #[test]
    fn test_arrival_behind_an_outstanding_request_only_enqueues() {
        let mut sched = scheduler();
        sched.on_groups(&snapshot(&[A], &[]), "b1", vec![run("t:a", &[1])]);

        let effects = sched.on_groups(&snapshot(&[A], &[]), "b2", vec![run("t:a", &[2])]);

        assert!(
            effects.dispatches.is_empty(),
            "at most one request per key may be in flight"
        );
        assert_eq!(sched.table().queued_messages(), 1);
        assert_eq!(sched.table().outstanding_keys(), 1);
    }

    #[test]
    fn test_intra_batch_placement_accounts_for_earlier_picks() {
        let mut sched = scheduler();

        // Two fresh equal-size runs, two idle workers: the first pick must
        // bump the working load so the second run lands on the other worker.
        let effects = sched.on_groups(
            &snapshot(&[A, B], &[]),
            "b1",
            vec![run("t:a", &[1, 2, 3]), run("t:b", &[1, 2, 3])],
        );

        assert_eq!(effects.dispatches.len(), 2);
        assert_ne!(effects.dispatches[0].worker, effects.dispatches[1].worker);
    }

    #[test]
    fn test_binpack_places_largest_run_first() {
        let mut sched = scheduler();

        let effects = sched.on_groups(
            &snapshot(&[A, B], &[]),
            "b1",
            vec![run("t:small", &[1]), run("t:big", &[1, 2, 3, 4, 5])],
        );

        assert_eq!(
            effects.dispatches[0].routing_key, "t:big",
            "heavy hitters drive the load distribution"
        );
    }

    #[test]
    fn test_duplicate_key_runs_in_one_call_merge_into_one_dispatch() {
        let mut sched = scheduler();

        let effects = sched.on_groups(
            &snapshot(&[A], &[]),
            "b1",
            vec![run("t:a", &[1]), run("t:a", &[2])],
        );

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2]);
    }

    #[test]
    fn test_fresh_work_routes_within_the_aperture_slice() {
        let mut sched = scheduler();

        // B is healthy but outside the candidate slice — fresh work must not
        // land there.
        let effects = sched.on_groups(
            &snapshot_narrowed(&[A, B], &[A], &[]),
            "b1",
            vec![run("t:a", &[1])],
        );

        assert_eq!(effects.dispatches[0].worker, wid(A));
    }

    // ---- on_groups: parking ----

    #[test]
    fn test_unroutable_arrival_parks_the_key() {
        let mut sched = scheduler();

        let effects = sched.on_groups(&snapshot(&[], &[]), "b1", vec![run("t:a", &[1, 2])]);

        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.unroutable, 1);
        assert_eq!(sched.table().parked_keys(), 1);
        assert_eq!(sched.table().queued_messages(), 2);
        assert_eq!(sched.table().outstanding_keys(), 0);
    }

    #[test]
    fn test_arrival_behind_a_parked_key_waits_for_the_deadline() {
        let mut sched = scheduler();
        sched.on_groups(&snapshot(&[], &[]), "b1", vec![run("t:a", &[1])]);

        // A worker is back, but the parked messages must go first, and only
        // the parked-retry deadline releases them.
        let effects = sched.on_groups(&snapshot(&[A], &[]), "b2", vec![run("t:a", &[2])]);

        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.table().parked_keys(), 1);
        assert_eq!(sched.table().queued_messages(), 2);
    }

    // ---- on_settled: delivered ----

    #[test]
    fn test_settlement_dispatches_the_next_queued_run() {
        let mut sched = scheduler();
        sched.on_groups(&snapshot(&[A], &[]), "b1", vec![run("t:a", &[1])]);
        sched.on_groups(&snapshot(&[A], &[]), "b2", vec![run("t:a", &[2, 3])]);

        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].kind, SendKind::Fresh);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![2, 3]);
        assert!(effects.evicted_keys.is_empty(), "the key is busy again");
        assert_eq!(sched.table().outstanding_keys(), 1);
        assert_eq!(sched.table().queued_messages(), 0);
    }

    #[test]
    fn test_settlement_with_an_empty_queue_evicts_the_key() {
        let mut sched = scheduler();
        sched.on_groups(&snapshot(&[A], &[]), "b1", vec![run("t:a", &[1])]);

        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));

        assert_eq!(effects.evicted_keys, vec!["t:a".to_string()]);
        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.table().key_count(), 0);
        assert_eq!(sched.table().outstanding_keys(), 0);
    }

    #[test]
    fn test_settlement_parks_the_next_run_when_no_worker_is_routable() {
        let mut sched = scheduler();
        sched.on_groups(&snapshot(&[A], &[]), "b1", vec![run("t:a", &[1])]);
        sched.on_groups(&snapshot(&[A], &[]), "b2", vec![run("t:a", &[2])]);

        // The pool emptied while the send was in flight (deploy overlap).
        let effects = sched.on_settled(&snapshot(&[], &[]), delivered(A, &["t:a"]));

        assert!(effects.dispatches.is_empty());
        assert_eq!(effects.deferred.unroutable, 1);
        assert_eq!(sched.table().parked_keys(), 1);
        assert_eq!(sched.table().outstanding_keys(), 0);
    }

    #[test]
    fn test_settlement_for_an_unknown_key_is_ignored() {
        let mut sched = scheduler();

        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:ghost"]));

        assert!(effects.dispatches.is_empty());
        assert!(effects.evicted_keys.is_empty());
        assert_eq!(sched.table().key_count(), 0);
    }

    // ---- on_settled: failed ----

    #[test]
    fn test_failed_settlement_requeues_at_the_front_and_parks() {
        let mut sched = scheduler();
        sched.on_groups(&snapshot(&[A, B], &[]), "b1", vec![run("t:a", &[1, 2])]);
        // Newer messages arrive while the send is in flight.
        sched.on_groups(&snapshot(&[A, B], &[]), "b2", vec![run("t:a", &[3])]);

        let effects = sched.on_settled(
            &snapshot(&[A, B], &[]),
            failed(A, vec![run("t:a", &[1, 2])]),
        );

        assert!(
            effects.dispatches.is_empty(),
            "failed work waits for the parked-retry deadline"
        );
        assert_eq!(effects.deferred.send_failed, 1);
        assert!(effects.evicted_keys.is_empty());
        assert_eq!(sched.table().parked_keys(), 1);
        assert_eq!(sched.table().outstanding_keys(), 0);

        // The retry replays the failed run ahead of the later arrival.
        let effects = sched.on_deadline(&snapshot(&[A, B], &[]), Deadline::ParkedRetry);
        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].kind, SendKind::Resend);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2, 3]);
    }

    #[test]
    fn test_new_arrivals_queue_behind_a_failure_awaiting_retry() {
        let mut sched = scheduler();
        sched.on_groups(&snapshot(&[A], &[]), "b1", vec![run("t:a", &[1])]);
        sched.on_settled(&snapshot(&[A], &[]), failed(A, vec![run("t:a", &[1])]));

        let effects = sched.on_groups(&snapshot(&[A], &[]), "b2", vec![run("t:a", &[2])]);

        assert!(
            effects.dispatches.is_empty(),
            "must not overtake the failed run"
        );
        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::ParkedRetry);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2]);
    }

    // ---- on_deadline ----

    #[test]
    fn test_batch_deadline_is_a_noop_for_the_key_table() {
        let mut sched = scheduler();
        sched.on_groups(&snapshot(&[], &[]), "b1", vec![run("t:a", &[1])]);

        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::Batch("b1"));

        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.table().parked_keys(), 1, "still parked");
    }

    #[test]
    fn test_parked_retry_dispatches_in_park_order_and_unparks() {
        let mut sched = scheduler();
        sched.on_groups(
            &snapshot(&[], &[]),
            "b1",
            vec![run("t:a", &[1]), run("t:b", &[1])],
        );
        assert_eq!(sched.table().parked_keys(), 2);

        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::ParkedRetry);

        assert_eq!(effects.dispatches.len(), 2);
        assert_eq!(effects.dispatches[0].routing_key, "t:a");
        assert_eq!(effects.dispatches[1].routing_key, "t:b");
        assert_eq!(sched.table().parked_keys(), 0);
        assert_eq!(sched.table().outstanding_keys(), 2);
    }

    #[test]
    fn test_parked_retry_keeps_keys_parked_when_no_worker_is_healthy() {
        let mut sched = scheduler();
        sched.on_groups(&snapshot(&[], &[]), "b1", vec![run("t:a", &[1])]);

        let effects = sched.on_deadline(&snapshot(&[], &[]), Deadline::ParkedRetry);

        assert!(effects.dispatches.is_empty());
        assert_eq!(sched.table().parked_keys(), 1, "kept for a later deadline");

        // Arrivals in the meantime still queue behind the parked work.
        let effects = sched.on_groups(&snapshot(&[], &[]), "b2", vec![run("t:a", &[2])]);
        assert!(effects.dispatches.is_empty());
        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::ParkedRetry);
        assert_eq!(offsets_of(&effects.dispatches[0]), vec![1, 2]);
    }

    #[test]
    fn test_parked_retry_routes_over_the_whole_healthy_pool() {
        let mut sched = scheduler();
        sched.on_groups(&snapshot(&[], &[]), "b1", vec![run("t:a", &[1])]);

        // The aperture slice is empty but a worker is healthy: the retry must
        // escape the slice, like a deferred flush.
        let effects = sched.on_deadline(&snapshot_narrowed(&[B], &[], &[]), Deadline::ParkedRetry);

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].worker, wid(B));
    }

    // ---- lifecycle ----

    #[test]
    fn test_full_lifecycle_preserves_per_key_order_and_ends_clean() {
        let mut sched = scheduler();
        let mut sent: Vec<i64> = Vec::new();
        let mut record = |effects: &SchedulerEffects| {
            for dispatch in &effects.dispatches {
                assert_eq!(dispatch.routing_key, "t:a");
                sent.extend(dispatch.messages.iter().map(|m| m.offset));
            }
            effects.dispatches.len()
        };

        // Arrive, dispatch, fail, queue more, retry, settle, queue drains.
        let effects = sched.on_groups(&snapshot(&[A], &[]), "b1", vec![run("t:a", &[1, 2])]);
        assert_eq!(record(&effects), 1);
        let effects = sched.on_groups(&snapshot(&[A], &[]), "b2", vec![run("t:a", &[3])]);
        assert_eq!(record(&effects), 0);
        let effects = sched.on_settled(&snapshot(&[A], &[]), failed(A, vec![run("t:a", &[1, 2])]));
        assert_eq!(record(&effects), 0);
        let effects = sched.on_deadline(&snapshot(&[A], &[]), Deadline::ParkedRetry);
        assert_eq!(record(&effects), 1);
        let effects = sched.on_groups(&snapshot(&[A], &[]), "b3", vec![run("t:a", &[4])]);
        assert_eq!(record(&effects), 0);
        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));
        assert_eq!(record(&effects), 1);
        let effects = sched.on_settled(&snapshot(&[A], &[]), delivered(A, &["t:a"]));
        assert_eq!(record(&effects), 0);

        // The failed prefix replays once, and every offset goes out in order.
        assert_eq!(sent, vec![1, 2, 1, 2, 3, 4]);
        assert_eq!(effects.evicted_keys, vec!["t:a".to_string()]);
        assert_eq!(sched.table().key_count(), 0);
        assert_eq!(sched.table().queued_messages(), 0);
        assert_eq!(sched.table().outstanding_keys(), 0);
        assert_eq!(sched.table().parked_keys(), 0);
    }

    #[test]
    fn test_keys_progress_independently() {
        let mut sched = scheduler();
        sched.on_groups(
            &snapshot(&[A, B], &[]),
            "b1",
            vec![run("t:a", &[1]), run("t:b", &[1])],
        );
        sched.on_groups(
            &snapshot(&[A, B], &[]),
            "b2",
            vec![run("t:a", &[2]), run("t:b", &[2])],
        );

        // Only t:a settles — only t:a's next run may go out.
        let effects = sched.on_settled(&snapshot(&[A, B], &[]), delivered(A, &["t:a"]));

        assert_eq!(effects.dispatches.len(), 1);
        assert_eq!(effects.dispatches[0].routing_key, "t:a");
        assert_eq!(sched.table().queued_messages(), 1, "t:b still queued");
    }
}
