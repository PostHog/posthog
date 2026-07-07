//! The rebalance bridge: a [`ConsumerContext`] that turns Kafka's rebalance callbacks into the
//! partition lifecycle a stateful, partition-affined consumer needs.
//!
//! Correctness rests on one invariant: all of a `(team_id, person_id)`'s state lives on exactly one
//! partition → one pod → one store slice. So ownership must *move* — on revoke, reclaim the slice; on
//! assign, record ownership.
//!
//! librdkafka fires `pre_rebalance`/`post_rebalance` synchronously on the poll thread, where blocking
//! or panicking is forbidden (a panic across the FFI boundary is UB). The callbacks therefore do only
//! fast sync work and ship the slow part (draining a worker is async I/O) to [`run_rebalance_worker`]
//! over an mpsc channel.
//!
//! Cooperative-sticky can revoke a partition and immediately re-assign it to the same pod. The async
//! cleanup re-checks ownership against current state (not the queued snapshot) and skips when the
//! partition was re-acquired, leaving the live worker and its slice untouched — see
//! [`EventDispatcher::revoke_partition_drain`].

use std::sync::Arc;

use metrics::counter;
use rdkafka::consumer::{BaseConsumer, ConsumerContext, Rebalance};
use rdkafka::{ClientContext, TopicPartitionList};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, info};

use crate::consumers::events::EventDispatcher;
use crate::observability::metrics::{REBALANCES_TOTAL, REBALANCE_EMPTY_SKIPPED_TOTAL};
use crate::partitions::follower::PartitionMirror;

/// Work shipped from the synchronous rebalance callbacks to the async [`run_rebalance_worker`].
#[derive(Debug, Clone)]
pub enum RebalanceEvent {
    /// Reclaim these revoked partitions: drain each worker, then delete its state slice.
    Revoke(Vec<i32>),
    /// Partitions newly assigned.
    Assign(Vec<i32>),
}

pub type RebalanceEventReceiver = mpsc::UnboundedReceiver<RebalanceEvent>;

/// Commands from the rebalance worker to the consume loop. Currently unused.
#[derive(Debug)]
pub enum ConsumerCommand {
    /// Resume consumption for these partitions.
    Resume(TopicPartitionList),
    /// Seek these partitions to specific offsets.
    SeekPartitions(TopicPartitionList),
}

pub type ConsumerCommandSender = mpsc::UnboundedSender<ConsumerCommand>;
pub type ConsumerCommandReceiver = mpsc::UnboundedReceiver<ConsumerCommand>;

/// The rdkafka [`ConsumerContext`] for `cohort_stream_events`. Rebalance callbacks drive the
/// [`EventDispatcher`]'s partition lifecycle and hand slow cleanup to the async worker.
pub struct CohortConsumerContext {
    dispatcher: Arc<EventDispatcher>,
    rebalance_tx: mpsc::UnboundedSender<RebalanceEvent>,
}

impl CohortConsumerContext {
    /// Build the context and the receiver half of its rebalance channel.
    pub fn new(dispatcher: Arc<EventDispatcher>) -> (Self, RebalanceEventReceiver) {
        let (rebalance_tx, rebalance_rx) = mpsc::unbounded_channel();
        (
            Self {
                dispatcher,
                rebalance_tx,
            },
            rebalance_rx,
        )
    }

    /// Sync, on the poll thread: mark each revoked partition un-owned and queue async cleanup.
    fn on_revoke(&self, partitions: &TopicPartitionList) {
        if partitions.count() == 0 {
            counter!(REBALANCE_EMPTY_SKIPPED_TOTAL, "event_type" => "revoke").increment(1);
            debug!("skipping empty revoke");
            return;
        }
        let partitions = partition_numbers(partitions);
        counter!(REBALANCES_TOTAL, "event_type" => "revoke").increment(1);
        info!(count = partitions.len(), "revoking partitions");
        for &partition in &partitions {
            self.dispatcher.revoke_partition_sync(partition);
        }
        if let Err(err) = self.rebalance_tx.send(RebalanceEvent::Revoke(partitions)) {
            error!(error = %err, "failed to queue revoke cleanup");
        }
    }

    /// Sync, on the poll thread: record ownership for each assigned partition.
    fn on_assign(&self, partitions: &TopicPartitionList) {
        if partitions.count() == 0 {
            counter!(REBALANCE_EMPTY_SKIPPED_TOTAL, "event_type" => "assign").increment(1);
            debug!("skipping empty assign");
            return;
        }
        let partitions = partition_numbers(partitions);
        counter!(REBALANCES_TOTAL, "event_type" => "assign").increment(1);
        info!(count = partitions.len(), "assigned partitions");
        for &partition in &partitions {
            self.dispatcher.assign_partition(partition);
        }
        if let Err(err) = self.rebalance_tx.send(RebalanceEvent::Assign(partitions)) {
            error!(error = %err, "failed to queue assign setup");
        }
    }
}

impl ClientContext for CohortConsumerContext {}

impl ConsumerContext for CohortConsumerContext {
    fn pre_rebalance(&self, _base: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        match rebalance {
            Rebalance::Revoke(partitions) => self.on_revoke(partitions),
            Rebalance::Assign(_) => {}
            Rebalance::Error(err) => error!(error = %err, "pre-rebalance error"),
        }
    }

    fn post_rebalance(&self, _base: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        match rebalance {
            Rebalance::Assign(partitions) => self.on_assign(partitions),
            Rebalance::Revoke(_) => {}
            Rebalance::Error(err) => error!(error = %err, "post-rebalance error"),
        }
    }
}

/// Async rebalance worker: mirrors (un)assignments onto follower consumers and drains revoked
/// partitions off the poll thread. Runs until shutdown or the sender is dropped.
///
/// Mirror calls are unconditional — even on rapid revoke→assign where the drain skips — because
/// the followers' in-session fetch position advances past owned-gate-dropped messages and only a
/// re-assign at `Offset::Stored` rewinds over that gap.
pub async fn run_rebalance_worker(
    mut events: RebalanceEventReceiver,
    dispatcher: Arc<EventDispatcher>,
    mirror: Arc<dyn PartitionMirror>,
    // Currently unused; held so the command channel's receiver stays open.
    _consumer_command_tx: ConsumerCommandSender,
    shutdown: CancellationToken,
) {
    info!("rebalance worker started");
    loop {
        tokio::select! {
            biased;
            _ = shutdown.cancelled() => {
                info!("rebalance worker stopping on shutdown signal");
                break;
            }
            event = events.recv() => {
                let Some(event) = event else {
                    info!("rebalance worker channel closed; stopping");
                    break;
                };
                match event {
                    RebalanceEvent::Revoke(partitions) => {
                        // Unassign followers before drain: during drain, their fetch position
                        // would advance past owned-gate-dropped messages.
                        mirror.unassign(&partitions);
                        for partition in partitions {
                            dispatcher.revoke_partition_drain(partition).await;
                        }
                    }
                    RebalanceEvent::Assign(partitions) => {
                        // Stale-slice reclamation for post-boot move-ins now happens at worker-spawn
                        // time (`EventDispatcher::ensure_worker`), under the partition's shard guard,
                        // so the wipe deterministically precedes the eviction-queue rebuild. The assign
                        // arm only mirrors followers.
                        mirror.assign(&partitions);
                    }
                }
            }
        }
    }
}

fn partition_numbers(partitions: &TopicPartitionList) -> Vec<i32> {
    partitions
        .elements()
        .iter()
        .map(|elem| elem.partition())
        .collect()
}

#[cfg(test)]
// Tests seed and probe partition slices against `CohortStore` directly while the dispatcher holds
// the `StoreHandle` facade.
#[allow(clippy::disallowed_methods)]
mod tests {
    use super::*;
    use std::sync::Mutex;
    use tempfile::TempDir;

    use crate::filters::{CatalogHandle, FilterCatalog};
    use crate::partitions::{MarkOutcome, OffsetTracker, PartitionRouter};
    use crate::producer::{CaptureSink, MembershipSink};
    use crate::store::{
        Behavioral, BehavioralKey, CohortStore, LeafStateKey, OffloadConfig, OffloadMode,
        StoreConfig, StoreHandle,
    };
    use crate::workers::MergeWorkerDeps;
    use uuid::Uuid;

    const TOPIC: &str = "cohort_stream_events";

    fn tpl(partitions: &[i32]) -> TopicPartitionList {
        let mut list = TopicPartitionList::new();
        for &partition in partitions {
            list.add_partition(TOPIC, partition);
        }
        list
    }

    /// Returns the raw store alongside the dispatcher (which wraps a clone of it) so tests can
    /// seed/probe slices directly; the dispatcher itself only exposes the async facade.
    fn test_dispatcher() -> (
        TempDir,
        Arc<EventDispatcher>,
        Arc<OffsetTracker>,
        CohortStore,
    ) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        let handle = StoreHandle::new(
            store.clone(),
            OffloadConfig {
                mode: OffloadMode::All,
                event_read_permits: 16,
                maintenance_permits: 6,
            },
        );
        let catalog = Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([])));
        let sink: Arc<dyn MembershipSink> = Arc::new(CaptureSink::new());
        let tracker = Arc::new(OffsetTracker::new());
        let dispatcher = EventDispatcher::new(
            PartitionRouter::new(64),
            tracker.clone(),
            handle,
            catalog,
            sink,
            MergeWorkerDeps::capture(),
        );
        (dir, Arc::new(dispatcher), tracker, store)
    }

    #[derive(Debug, Clone, PartialEq, Eq)]
    enum MirrorCall {
        Assign(Vec<i32>),
        Unassign(Vec<i32>),
    }

    /// Records mirror calls. At unassign time, snapshots whether the tracker still held the
    /// partition's entry (proving unassign ran before drain).
    struct RecordingMirror {
        tracker: Arc<OffsetTracker>,
        calls: Mutex<Vec<MirrorCall>>,
        unassign_saw_tracker_entry: Mutex<Vec<bool>>,
    }

    impl RecordingMirror {
        fn new(tracker: Arc<OffsetTracker>) -> Arc<Self> {
            Arc::new(Self {
                tracker,
                calls: Mutex::new(Vec::new()),
                unassign_saw_tracker_entry: Mutex::new(Vec::new()),
            })
        }

        fn calls(&self) -> Vec<MirrorCall> {
            self.calls.lock().unwrap().clone()
        }
    }

    impl PartitionMirror for RecordingMirror {
        fn assign(&self, partitions: &[i32]) {
            self.calls
                .lock()
                .unwrap()
                .push(MirrorCall::Assign(partitions.to_vec()));
        }

        fn unassign(&self, partitions: &[i32]) {
            let offsets = self.tracker.committable_offsets();
            let saw_all = partitions
                .iter()
                .all(|partition| offsets.contains_key(partition));
            self.unassign_saw_tracker_entry
                .lock()
                .unwrap()
                .push(saw_all);
            self.calls
                .lock()
                .unwrap()
                .push(MirrorCall::Unassign(partitions.to_vec()));
        }
    }

    async fn run_worker_to_completion(
        events: RebalanceEventReceiver,
        dispatcher: Arc<EventDispatcher>,
        mirror: Arc<RecordingMirror>,
    ) {
        let (cmd_tx, _cmd_rx) = mpsc::unbounded_channel();
        run_rebalance_worker(events, dispatcher, mirror, cmd_tx, CancellationToken::new()).await;
    }

    #[test]
    fn partition_numbers_extracts_each_partition() {
        let mut numbers = partition_numbers(&tpl(&[3, 7, 1]));
        numbers.sort_unstable();
        assert_eq!(numbers, vec![1, 3, 7]);
    }

    #[test]
    fn empty_tpl_has_zero_count() {
        assert_eq!(TopicPartitionList::new().count(), 0);
        assert_eq!(tpl(&[0]).count(), 1);
    }

    #[tokio::test]
    async fn on_assign_records_ownership_and_queues_an_assign_event() {
        let (_dir, dispatcher, _tracker, _store) = test_dispatcher();
        let (ctx, mut rx) = CohortConsumerContext::new(dispatcher.clone());

        ctx.on_assign(&tpl(&[0, 1, 4]));

        assert!(dispatcher.owns(0) && dispatcher.owns(1) && dispatcher.owns(4));
        assert!(!dispatcher.owns(2));
        match rx.try_recv().expect("an assign event was queued") {
            RebalanceEvent::Assign(mut partitions) => {
                partitions.sort_unstable();
                assert_eq!(partitions, vec![0, 1, 4]);
            }
            other => panic!("expected Assign, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn on_revoke_clears_ownership_and_queues_a_revoke_event() {
        let (_dir, dispatcher, _tracker, _store) = test_dispatcher();
        let (ctx, mut rx) = CohortConsumerContext::new(dispatcher.clone());

        ctx.on_assign(&tpl(&[0, 1]));
        assert!(
            matches!(rx.try_recv(), Ok(RebalanceEvent::Assign(_))),
            "assign is queued first",
        );
        ctx.on_revoke(&tpl(&[1]));

        assert!(dispatcher.owns(0), "unrevoked partition stays owned");
        assert!(!dispatcher.owns(1), "revoked partition is un-owned");
        match rx.try_recv().expect("a revoke event was queued") {
            RebalanceEvent::Revoke(partitions) => assert_eq!(partitions, vec![1]),
            other => panic!("expected Revoke, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn empty_callbacks_are_noops_and_queue_nothing() {
        let (_dir, dispatcher, _tracker, _store) = test_dispatcher();
        let (ctx, mut rx) = CohortConsumerContext::new(dispatcher.clone());

        ctx.on_assign(&tpl(&[]));
        ctx.on_revoke(&tpl(&[]));

        assert!(!dispatcher.owns(0));
        assert!(
            rx.try_recv().is_err(),
            "an empty callback must not queue work",
        );
    }

    #[tokio::test]
    async fn assign_event_mirrors_the_followers() {
        let (_dir, dispatcher, tracker, _store) = test_dispatcher();
        let (ctx, rx) = CohortConsumerContext::new(dispatcher.clone());
        let mirror = RecordingMirror::new(tracker);

        ctx.on_assign(&tpl(&[0, 4]));
        drop(ctx);
        run_worker_to_completion(rx, dispatcher, mirror.clone()).await;

        assert_eq!(mirror.calls(), vec![MirrorCall::Assign(vec![0, 4])]);
    }

    #[tokio::test]
    async fn revoke_unassigns_the_followers_before_the_drain() {
        let (_dir, dispatcher, tracker, _store) = test_dispatcher();
        let (ctx, rx) = CohortConsumerContext::new(dispatcher.clone());
        let mirror = RecordingMirror::new(tracker.clone());

        // Seed a committable entry the drain will forget — the order probe.
        tracker.mark_dispatched(3, 10);
        assert_eq!(tracker.mark_processed(3, 10), MarkOutcome::WithinDispatch);

        ctx.on_assign(&tpl(&[3]));
        ctx.on_revoke(&tpl(&[3]));
        drop(ctx);
        run_worker_to_completion(rx, dispatcher.clone(), mirror.clone()).await;

        assert_eq!(
            mirror.calls(),
            vec![MirrorCall::Assign(vec![3]), MirrorCall::Unassign(vec![3])],
        );
        assert_eq!(
            *mirror.unassign_saw_tracker_entry.lock().unwrap(),
            vec![true],
            "the tracker entry was still live at unassign time, so the unassign ran before the drain",
        );
        assert!(
            !tracker.committable_offsets().contains_key(&3),
            "the drain then forgot the revoked partition's entry",
        );
        assert!(!dispatcher.owns(3));
    }

    fn slice_key(partition: u16) -> BehavioralKey {
        BehavioralKey::new(partition, 7, Uuid::from_u128(1), LeafStateKey([0xAB; 16]))
    }

    fn seed_slice(store: &CohortStore, partition: u16) {
        store
            .write_batch(|b| b.put::<Behavioral>(&slice_key(partition), b"state"))
            .unwrap();
    }

    /// Probe whether `partition`'s slice is present without seeding it, so the caller controls seed
    /// ordering relative to a boot reconcile.
    fn present_probe(store: &CohortStore, partition: u16) -> impl Fn() -> bool + '_ {
        move || {
            store
                .get_behavioral(&slice_key(partition))
                .unwrap()
                .is_some()
        }
    }

    fn seed_and_present(store: &CohortStore, partition: u16) -> impl Fn() -> bool + '_ {
        seed_slice(store, partition);
        present_probe(store, partition)
    }

    #[tokio::test]
    async fn assign_arm_does_not_reclaim_slices_reclamation_is_deferred_to_worker_spawn() {
        // The rebalance Assign arm only mirrors followers; it never wipes a slice. A post-boot move-in's
        // stale slice is reclaimed at `ensure_worker` spawn time instead (under the shard guard, before
        // the eviction-queue rebuild), so the slice survives the assign path until the first event —
        // regardless of the durable-restore gate.
        for durable_on in [false, true] {
            let (_dir, dispatcher, tracker, store) = test_dispatcher();
            if durable_on {
                dispatcher.enable_durable_restore();
            }
            // Snapshot excludes 3; seeding *after* reconcile keeps the boot wipe from deleting it, so
            // only the (now inert) assign path could have wiped it.
            dispatcher
                .reconcile_boot_assignment(&[0].into_iter().collect(), 64)
                .await;
            let present = seed_and_present(&store, 3);
            let (ctx, rx) = CohortConsumerContext::new(dispatcher.clone());
            let mirror = RecordingMirror::new(tracker);
            ctx.on_assign(&tpl(&[3]));
            drop(ctx);
            run_worker_to_completion(rx, dispatcher.clone(), mirror).await;
            assert!(
                present(),
                "the assign arm leaves the slice in place (durable_on={durable_on}); reclamation is deferred to spawn",
            );
        }
    }

    #[tokio::test]
    async fn durable_boot_assign_keeps_restored_slices() {
        // The pod's own initial assignment routes through the assign path; the restored slices for the
        // assigned partitions must survive it (the assign arm never wipes; spawn-time reclaim keeps
        // boot-snapshot partitions).
        let (_dir, dispatcher, tracker, store) = test_dispatcher();
        dispatcher.enable_durable_restore();
        seed_slice(&store, 0);
        seed_slice(&store, 1);
        let present_0 = present_probe(&store, 0);
        let present_1 = present_probe(&store, 1);
        dispatcher
            .reconcile_boot_assignment(&[0, 1].into_iter().collect(), 64)
            .await;

        let (ctx, rx) = CohortConsumerContext::new(dispatcher.clone());
        let mirror = RecordingMirror::new(tracker);
        ctx.on_assign(&tpl(&[0, 1]));
        drop(ctx);
        run_worker_to_completion(rx, dispatcher.clone(), mirror).await;

        assert!(present_0() && present_1(), "boot-assigned slices survive");
    }

    #[tokio::test]
    async fn durable_assign_before_boot_reconcile_keeps_slices() {
        // The rebalance worker can process the initial Assign before the consume loop records the
        // snapshot; the assign path never wipes, so the slices survive until they are either reopened
        // live or reclaimed at spawn time.
        let (_dir, dispatcher, tracker, store) = test_dispatcher();
        dispatcher.enable_durable_restore();
        seed_slice(&store, 0);
        seed_slice(&store, 1);
        let present_0 = present_probe(&store, 0);
        let present_1 = present_probe(&store, 1);

        let (ctx, rx) = CohortConsumerContext::new(dispatcher.clone());
        let mirror = RecordingMirror::new(tracker);
        ctx.on_assign(&tpl(&[0, 1]));
        drop(ctx);
        run_worker_to_completion(rx, dispatcher.clone(), mirror).await;

        assert!(
            present_0() && present_1(),
            "with no snapshot yet, the assign path skips and the slices survive",
        );
    }

    #[tokio::test]
    async fn rapid_revoke_assign_mirrors_both_calls_unconditionally() {
        let (_dir, dispatcher, tracker, _store) = test_dispatcher();
        let (ctx, rx) = CohortConsumerContext::new(dispatcher.clone());
        let mirror = RecordingMirror::new(tracker.clone());

        tracker.mark_dispatched(3, 10);
        assert_eq!(tracker.mark_processed(3, 10), MarkOutcome::WithinDispatch);

        ctx.on_assign(&tpl(&[3]));
        ctx.on_revoke(&tpl(&[3]));
        ctx.on_assign(&tpl(&[3]));
        drop(ctx);
        run_worker_to_completion(rx, dispatcher.clone(), mirror.clone()).await;

        assert_eq!(
            mirror.calls(),
            vec![
                MirrorCall::Assign(vec![3]),
                MirrorCall::Unassign(vec![3]),
                MirrorCall::Assign(vec![3]),
            ],
        );
        assert!(dispatcher.owns(3), "the rapid re-assign restored ownership");
        assert_eq!(
            tracker.committable_offsets().get(&3),
            Some(&10),
            "drain skipped for re-acquired partition, so tracker entry survives",
        );
    }
}
