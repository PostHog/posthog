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

/// Work shipped from the synchronous rebalance callbacks to the async [`run_rebalance_worker`],
/// which can do the I/O the callbacks must not.
#[derive(Debug, Clone)]
pub enum RebalanceEvent {
    /// Reclaim these revoked partitions: drain each worker (produce + ack its tail), then delete its
    /// on-disk state slice.
    Revoke(Vec<i32>),
    /// Partitions newly assigned.
    Assign(Vec<i32>),
}

/// Receiving half of a context's rebalance channel, handed to [`run_rebalance_worker`].
pub type RebalanceEventReceiver = mpsc::UnboundedReceiver<RebalanceEvent>;

/// Commands from the rebalance worker to the consume loop for seeking and resuming partition
/// consumption. Currently unused.
#[derive(Debug)]
pub enum ConsumerCommand {
    /// Resume consumption for these partitions.
    Resume(TopicPartitionList),
    /// Seek these partitions to specific offsets.
    SeekPartitions(TopicPartitionList),
}

/// Sending half of the consumer-command channel.
pub type ConsumerCommandSender = mpsc::UnboundedSender<ConsumerCommand>;
/// Receiving half of the consumer-command channel.
pub type ConsumerCommandReceiver = mpsc::UnboundedReceiver<ConsumerCommand>;

/// The rdkafka [`ConsumerContext`] for `cohort_stream_events`. Its rebalance callbacks drive the
/// shared [`EventDispatcher`]'s partition lifecycle and hand slow cleanup to the async worker.
pub struct CohortConsumerContext {
    dispatcher: Arc<EventDispatcher>,
    rebalance_tx: mpsc::UnboundedSender<RebalanceEvent>,
}

impl CohortConsumerContext {
    /// Build the context and the receiver half of its rebalance channel. The caller spawns
    /// [`run_rebalance_worker`] with the returned receiver, so the slow revoke cleanup runs off the
    /// librdkafka poll thread.
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

    /// Sync, on the poll thread: mark each revoked partition un-owned and hand the slow reclaim
    /// (drain + delete) to the async worker. No `.await` and no panic — both are forbidden here.
    fn on_revoke(&self, partitions: &TopicPartitionList) {
        if partitions.count() == 0 {
            // Cooperative-sticky fires empty callbacks whenever group membership changes without
            // moving this consumer's partitions.
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
            // Only at teardown (worker gone); the slice is reclaimed on the next clean start.
            error!(error = %err, "failed to queue revoke cleanup");
        }
    }

    /// Sync, on the poll thread: record ownership for each assigned partition. Workers spawn lazily
    /// on first message.
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
    /// Never calls `assign`/`unassign`: rdkafka performs the incremental (un)assign automatically
    /// between `pre_`/`post_` under the cooperative protocol, and calling the non-incremental form
    /// forces eager semantics.
    fn pre_rebalance(&self, _base: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        match rebalance {
            Rebalance::Revoke(partitions) => self.on_revoke(partitions),
            // Cooperative pre-assign reports the to-be-added set; ownership is recorded in post.
            Rebalance::Assign(_) => {}
            Rebalance::Error(err) => error!(error = %err, "pre-rebalance error"),
        }
    }

    fn post_rebalance(&self, _base: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        match rebalance {
            // Assign in post, not pre: the partitions are ours and messages start flowing now.
            Rebalance::Assign(partitions) => self.on_assign(partitions),
            Rebalance::Revoke(_) => {}
            Rebalance::Error(err) => error!(error = %err, "post-rebalance error"),
        }
    }
}

/// Drain the async half of rebalancing: mirror every (un)assignment onto the merge-protocol
/// follower consumers, and reclaim revoked partitions (drain worker + delete state) off the poll
/// thread. Runs until the [`shutdown`](CancellationToken) token fires or the context (its only
/// sender) is dropped.
///
/// Both mirror calls are **unconditional** (D5) — no ownership re-check, even on the rapid
/// revoke→assign path where the drain itself skips. Between the sync revoke and the unassign here,
/// the followers keep fetching and the owned-gate drops their messages while the in-session fetch
/// position advances; only an unconditional re-assign at `Offset::Stored` rewinds over that dropped
/// window, and the drain/apply source-coords markers absorb the redelivered prefix.
///
/// An in-flight cleanup is never interrupted: `select!` only races the *futures* — once a
/// `RebalanceEvent` is received and its handler is running, it completes before the next shutdown
/// check, so a partition is never left half-drained.
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
                        // Unassign the followers *before* the drain: the drain joins the worker, and
                        // anything the followers fetched during that window would be dropped at the
                        // owned-gate while still advancing their fetch position. Deliberately **no**
                        // follower offset commit here: the worker may still be marking the drained
                        // tail, and an uncommitted offset simply redelivers to the partition's next
                        // owner, whose drain/apply source-coords markers absorb the replay.
                        mirror.unassign(&partitions);
                        for partition in partitions {
                            dispatcher.revoke_partition_drain(partition).await;
                        }
                    }
                    // The dispatcher side needs no async work (workers spawn lazily on first
                    // message); the followers resume from each group's committed offset.
                    RebalanceEvent::Assign(partitions) => mirror.assign(&partitions),
                }
            }
        }
    }
}

/// This consumer's partition numbers from a rebalance TPL. It subscribes to a single topic, so the
/// partition number alone identifies a partition.
fn partition_numbers(partitions: &TopicPartitionList) -> Vec<i32> {
    partitions
        .elements()
        .iter()
        .map(|elem| elem.partition())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;
    use tempfile::TempDir;

    use crate::filters::{CatalogHandle, FilterCatalog};
    use crate::partitions::{MarkOutcome, OffsetTracker, PartitionRouter};
    use crate::producer::{CaptureSink, MembershipSink};
    use crate::store::{CohortStore, StoreConfig};
    use crate::workers::MergeWorkerDeps;

    const TOPIC: &str = "cohort_stream_events";

    fn tpl(partitions: &[i32]) -> TopicPartitionList {
        let mut list = TopicPartitionList::new();
        for &partition in partitions {
            list.add_partition(TOPIC, partition);
        }
        list
    }

    /// A dispatcher over an empty catalog: enough to exercise the ownership/queue plumbing without
    /// processing any events. Also returns the shared events tracker, the seam the mirror tests
    /// use to observe whether the revoke drain has run yet.
    fn test_dispatcher() -> (TempDir, Arc<EventDispatcher>, Arc<OffsetTracker>) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        let catalog = Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([])));
        let sink: Arc<dyn MembershipSink> = Arc::new(CaptureSink::new());
        let tracker = Arc::new(OffsetTracker::new());
        let dispatcher = EventDispatcher::new(
            PartitionRouter::new(64),
            tracker.clone(),
            store,
            catalog,
            sink,
            MergeWorkerDeps::capture(),
        );
        (dir, Arc::new(dispatcher), tracker)
    }

    #[derive(Debug, Clone, PartialEq, Eq)]
    enum MirrorCall {
        Assign(Vec<i32>),
        Unassign(Vec<i32>),
    }

    /// Records every mirror call in order. At unassign time it also snapshots whether the events
    /// tracker still held every revoked partition's entry — the drain forgets those entries, so a
    /// `true` observation proves the unassign ran *before* the drain.
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

    /// Queue the context's pending events, drop it, and run the worker to completion — the closed
    /// channel drains every queued event before `recv()` yields `None`, so no polling or token
    /// cancellation is needed.
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
        // The short-circuit precondition both callbacks rely on.
        assert_eq!(TopicPartitionList::new().count(), 0);
        assert_eq!(tpl(&[0]).count(), 1);
    }

    #[tokio::test]
    async fn on_assign_records_ownership_and_queues_an_assign_event() {
        let (_dir, dispatcher, _tracker) = test_dispatcher();
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
        let (_dir, dispatcher, _tracker) = test_dispatcher();
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
        let (_dir, dispatcher, _tracker) = test_dispatcher();
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
        let (_dir, dispatcher, tracker) = test_dispatcher();
        let (ctx, rx) = CohortConsumerContext::new(dispatcher.clone());
        let mirror = RecordingMirror::new(tracker);

        ctx.on_assign(&tpl(&[0, 4]));
        drop(ctx);
        run_worker_to_completion(rx, dispatcher, mirror.clone()).await;

        assert_eq!(mirror.calls(), vec![MirrorCall::Assign(vec![0, 4])]);
    }

    #[tokio::test]
    async fn revoke_unassigns_the_followers_before_the_drain() {
        let (_dir, dispatcher, tracker) = test_dispatcher();
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

    #[tokio::test]
    async fn rapid_revoke_assign_mirrors_both_calls_unconditionally() {
        let (_dir, dispatcher, tracker) = test_dispatcher();
        let (ctx, rx) = CohortConsumerContext::new(dispatcher.clone());
        let mirror = RecordingMirror::new(tracker.clone());

        tracker.mark_dispatched(3, 10);
        assert_eq!(tracker.mark_processed(3, 10), MarkOutcome::WithinDispatch);

        // Cooperative-sticky can revoke and immediately hand the partition back. The drain skips
        // (re-acquired at its entry check) but the mirror must still unassign *and* re-assign:
        // skipping the re-assign would leave the follower's in-session position past the
        // owned-gate-dropped window, which a later monotonic-max mark would commit over.
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
            "the drain skipped for the re-acquired partition, so its tracker entry survives",
        );
    }
}
