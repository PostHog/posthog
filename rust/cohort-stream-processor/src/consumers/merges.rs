//! The merge-protocol follower consumers (TDD §4.5.1): `KAFKA_PERSON_MERGE_EVENTS` (the drain
//! trigger, keyed by P_old) and `cohort_merge_state_transfer` (the packaged state, keyed by P_new).
//!
//! Both are one [`FollowerConsumer`], generic over a [`FollowerRoute`] that picks the decode and
//! dispatch ends; everything between — the consume loop, the deadline-driven commit, the final sync
//! commit — is shared and mirrors [`CohortStreamEventsConsumer`]'s
//! [`process`](CohortStreamEventsConsumer::process) exactly, for the same cancellation-safety
//! reasons.
//!
//! Followers never `subscribe()`: the events group's rebalance mirrors partition ownership onto
//! them ([`crate::partitions::follower`]), so there is exactly one ownership lifecycle across all
//! three co-partitioned topics. Their `group.id`s exist only so commits land on observable groups.
//!
//! [`CohortStreamEventsConsumer`]: crate::consumers::events::CohortStreamEventsConsumer
//! [`process`]: crate::consumers::events::CohortStreamEventsConsumer::process

use std::collections::{HashMap, HashSet};
use std::marker::PhantomData;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use lifecycle::Handle;
use metrics::{counter, histogram};
use rdkafka::consumer::{CommitMode, StreamConsumer};
use rdkafka::message::Message;
use tracing::{debug, info, warn};

use crate::consumers::events::{commit_offsets, EventDispatcher, RECV_ERROR_BACKOFF};
use crate::merge::transfer::{MergeStateTransfer, PersonMergeEvent};
use crate::observability::metrics::{
    COHORT_STREAM_KAFKA_RECV_ERRORS, COHORT_STREAM_MERGES_CONSUMED,
    COHORT_STREAM_MERGES_CONSUME_BATCH_SIZE, COHORT_STREAM_MERGE_DESERIALIZE_ERRORS,
    COHORT_STREAM_TRANSFERS_CONSUMED, COHORT_STREAM_TRANSFERS_CONSUME_BATCH_SIZE,
    COHORT_STREAM_TRANSFER_DESERIALIZE_ERRORS,
};
use crate::partitions::offset_tracker::OffsetTracker;
use crate::workers::MergeWorkerDeps;

/// One merge trigger consumed from `KAFKA_PERSON_MERGE_EVENTS`, paired with its position on that
/// topic — the commit coordinates for the merge [`OffsetTracker`](crate::partitions::OffsetTracker)
/// (never the events tracker; the two topics commit independently, D7). The topics are
/// co-partitioned, so `partition` is also the worker that owns P_old's state.
#[derive(Debug)]
pub struct ConsumedMerge {
    pub event: PersonMergeEvent,
    pub partition: i32,
    pub offset: i64,
}

/// One state transfer consumed from `cohort_merge_state_transfer`, paired with its position on that
/// topic — the commit coordinates for the transfer tracker (D7). `partition` is the worker that
/// owns P_new's state. Replay idempotence is keyed by the transfer's *source* merge-message
/// coordinates, not these (see [`MergeStateTransfer`]).
#[derive(Debug)]
pub struct ConsumedTransfer {
    pub transfer: MergeStateTransfer,
    pub partition: i32,
    pub offset: i64,
}

/// What distinguishes the two follower topics: how a payload decodes and which dispatcher entry
/// point routes the batch. The decode end is pure, so the wire seam is unit-testable without a
/// broker; the loop around it is exercised by the broker-backed integration tests.
#[async_trait]
pub trait FollowerRoute: Send + Sync + 'static {
    /// The consumed envelope [`dispatch`](Self::dispatch) routes.
    type Consumed: Send + 'static;
    /// Topic role for logs.
    const KIND: &'static str;
    /// Counter: envelopes consumed and successfully decoded.
    const CONSUMED_TOTAL: &'static str;
    /// Counter: payloads that were empty or failed to decode.
    const DESERIALIZE_ERRORS_TOTAL: &'static str;
    /// Histogram: decoded envelopes accumulated per consume → dispatch cycle.
    const CONSUME_BATCH_SIZE: &'static str;

    /// This route's commit tracker within the worker deps (D7). The route selects it — rather than
    /// the consumer's constructor taking a free tracker parameter — so the merge route can never
    /// commit on the transfer tracker or vice versa: crossed trackers would commit one topic's
    /// offsets from the other's marks, and nothing short of a broker test would notice.
    fn tracker(deps: &MergeWorkerDeps) -> &Arc<OffsetTracker>;

    /// Decode one payload into its consumed envelope, pairing it with its commit coordinates.
    fn decode(
        payload: &[u8],
        partition: i32,
        offset: i64,
    ) -> Result<Self::Consumed, serde_json::Error>;

    /// Hand a decoded batch to the dispatcher's matching entry point. The owned/draining gate and
    /// its skip counters live there — the consumer never pre-filters, so each drop is counted
    /// exactly once.
    async fn dispatch(dispatcher: &EventDispatcher, batch: Vec<Self::Consumed>);
}

/// The `KAFKA_PERSON_MERGE_EVENTS` route: P_old-keyed merge triggers into
/// [`EventDispatcher::dispatch_merges`].
pub struct MergeRoute;

#[async_trait]
impl FollowerRoute for MergeRoute {
    type Consumed = ConsumedMerge;
    const KIND: &'static str = "person_merge_events";
    const CONSUMED_TOTAL: &'static str = COHORT_STREAM_MERGES_CONSUMED;
    const DESERIALIZE_ERRORS_TOTAL: &'static str = COHORT_STREAM_MERGE_DESERIALIZE_ERRORS;
    const CONSUME_BATCH_SIZE: &'static str = COHORT_STREAM_MERGES_CONSUME_BATCH_SIZE;

    fn tracker(deps: &MergeWorkerDeps) -> &Arc<OffsetTracker> {
        &deps.merge_tracker
    }

    fn decode(
        payload: &[u8],
        partition: i32,
        offset: i64,
    ) -> Result<Self::Consumed, serde_json::Error> {
        PersonMergeEvent::decode(payload).map(|event| ConsumedMerge {
            event,
            partition,
            offset,
        })
    }

    async fn dispatch(dispatcher: &EventDispatcher, batch: Vec<Self::Consumed>) {
        dispatcher.dispatch_merges(batch).await;
    }
}

/// The `cohort_merge_state_transfer` route: P_new-keyed packaged drains into
/// [`EventDispatcher::dispatch_transfers`].
pub struct TransferRoute;

#[async_trait]
impl FollowerRoute for TransferRoute {
    type Consumed = ConsumedTransfer;
    const KIND: &'static str = "cohort_merge_state_transfer";
    const CONSUMED_TOTAL: &'static str = COHORT_STREAM_TRANSFERS_CONSUMED;
    const DESERIALIZE_ERRORS_TOTAL: &'static str = COHORT_STREAM_TRANSFER_DESERIALIZE_ERRORS;
    const CONSUME_BATCH_SIZE: &'static str = COHORT_STREAM_TRANSFERS_CONSUME_BATCH_SIZE;

    fn tracker(deps: &MergeWorkerDeps) -> &Arc<OffsetTracker> {
        &deps.transfer_tracker
    }

    fn decode(
        payload: &[u8],
        partition: i32,
        offset: i64,
    ) -> Result<Self::Consumed, serde_json::Error> {
        MergeStateTransfer::decode(payload).map(|transfer| ConsumedTransfer {
            transfer,
            partition,
            offset,
        })
    }

    async fn dispatch(dispatcher: &EventDispatcher, batch: Vec<Self::Consumed>) {
        dispatcher.dispatch_transfers(batch).await;
    }
}

/// A follower-topic group consumer: consume → route → commit, one per merge-protocol topic.
///
/// Commits via the route's tracker inside the dispatcher's [`MergeWorkerDeps`]
/// ([`FollowerRoute::tracker`], D7) and shares the follower `StreamConsumer` with the rebalance
/// mirror, which drives its (un)assignments.
pub struct FollowerConsumer<R: FollowerRoute> {
    consumer: Arc<StreamConsumer>,
    topic: String,
    dispatcher: Arc<EventDispatcher>,
    handle: Handle,
    recv_batch_size: usize,
    recv_batch_timeout: Duration,
    offset_commit_interval: Duration,
    _route: PhantomData<R>,
}

impl<R: FollowerRoute> FollowerConsumer<R> {
    pub fn new(
        consumer: Arc<StreamConsumer>,
        topic: String,
        dispatcher: Arc<EventDispatcher>,
        handle: Handle,
        recv_batch_size: usize,
        recv_batch_timeout: Duration,
        offset_commit_interval: Duration,
    ) -> Self {
        Self {
            consumer,
            topic,
            dispatcher,
            handle,
            recv_batch_size,
            recv_batch_timeout,
            offset_commit_interval,
            _route: PhantomData,
        }
    }

    /// The route-selected commit tracker (D7) — resolved through the dispatcher so this consumer
    /// can never be wired to the wrong topic's tracker.
    fn tracker(&self) -> &Arc<OffsetTracker> {
        R::tracker(self.dispatcher.merge_deps())
    }

    /// Run until the lifecycle handle signals shutdown. Mirrors
    /// [`CohortStreamEventsConsumer::process`] exactly: the commit is deadline-driven after
    /// `handle_outcome`, never a `select!` arm, because a commit arm winning the race would cancel
    /// the in-flight `consume_batch` and drop messages already `recv()`'d off librdkafka — gone
    /// from the broker, never dispatched, then committed past by a later batch's mark. The only
    /// future the `select!` can cancel is `consume_batch` on shutdown, whose dropped buffer was
    /// never marked and so replays.
    ///
    /// [`CohortStreamEventsConsumer::process`]: crate::consumers::events::CohortStreamEventsConsumer::process
    pub async fn process(self) {
        let _guard = self.handle.process_scope();
        info!(topic = %self.topic, "follower consume loop starting");

        let mut commit_deadline = tokio::time::Instant::now() + self.offset_commit_interval;

        loop {
            tokio::select! {
                // Check shutdown before `consume_batch` so a steady topic can't starve it.
                biased;
                _ = self.handle.shutdown_recv() => {
                    info!(topic = %self.topic, "shutdown signal received, stopping follower consume loop");
                    break;
                }
                outcome = self.consume_batch() => {
                    self.handle_outcome(outcome).await;
                    let now = tokio::time::Instant::now();
                    if now >= commit_deadline {
                        commit_offsets(
                            &self.consumer,
                            self.tracker(),
                            self.owned_committable_offsets(),
                            &self.topic,
                            CommitMode::Async,
                        );
                        commit_deadline = now + self.offset_commit_interval;
                    }
                }
            }
        }

        // Final sync commit of whatever is marked *now*. Unlike the events consumer, no worker
        // drain precedes this — that drain belongs to the events consumer's shutdown, which may
        // still be marking merge/transfer offsets after this commit runs. That tail is deliberately
        // left uncommitted: it redelivers to the partition's next owner, whose drain/apply
        // source-coords markers absorb the replay (the same posture as the skipped revoke-time
        // commit in the rebalance worker).
        commit_offsets(
            &self.consumer,
            self.tracker(),
            self.owned_committable_offsets(),
            &self.topic,
            CommitMode::Sync,
        );
        info!(topic = %self.topic, "follower consume loop stopped");
    }

    /// Account for a consumed batch, dispatch it, and heartbeat — the follower counterpart of the
    /// events consumer's `handle_outcome`. The heartbeat is informational here (followers carry no
    /// liveness deadline; their health signal is consumer-group lag), but the transport back-off
    /// still prevents a fast-failing `recv()` from spinning the loop.
    async fn handle_outcome(&self, outcome: FollowerOutcome<R::Consumed>) {
        histogram!(R::CONSUME_BATCH_SIZE).record(outcome.messages.len() as f64);
        if !outcome.messages.is_empty() {
            counter!(R::CONSUMED_TOTAL).increment(outcome.messages.len() as u64);
        }
        if outcome.deserialize_errors > 0 {
            counter!(R::DESERIALIZE_ERRORS_TOTAL).increment(outcome.deserialize_errors);
        }

        R::dispatch(&self.dispatcher, outcome.messages).await;

        if outcome.transport_error {
            tokio::time::sleep(RECV_ERROR_BACKOFF).await;
        } else {
            self.handle.report_healthy();
        }
    }

    /// Accumulate up to `recv_batch_size` decoded messages within `recv_batch_timeout`, decoding
    /// each payload immediately so no `BorrowedMessage` lifetime escapes the loop. An empty payload
    /// counts as a deserialize error rather than its own bucket — these internal topics never emit
    /// one, so a separate conservation leg would never move.
    async fn consume_batch(&self) -> FollowerOutcome<R::Consumed> {
        let mut outcome = FollowerOutcome {
            messages: Vec::with_capacity(self.recv_batch_size),
            deserialize_errors: 0,
            transport_error: false,
        };

        tokio::select! {
            _ = tokio::time::sleep(self.recv_batch_timeout) => {}
            _ = async {
                while outcome.messages.len() < self.recv_batch_size {
                    match self.consumer.recv().await {
                        Ok(message) => {
                            let partition = message.partition();
                            let offset = message.offset();
                            let Some(payload) = message.payload() else {
                                outcome.deserialize_errors += 1;
                                debug!(
                                    topic = %self.topic, partition, offset,
                                    "skipping follower message with empty payload",
                                );
                                continue;
                            };
                            match R::decode(payload, partition, offset) {
                                Ok(consumed) => outcome.messages.push(consumed),
                                Err(err) => {
                                    outcome.deserialize_errors += 1;
                                    debug!(
                                        topic = %self.topic, partition, offset, error = %err,
                                        "skipping undeserializable follower message",
                                    );
                                }
                            }
                        }
                        Err(err) => {
                            outcome.transport_error = true;
                            counter!(COHORT_STREAM_KAFKA_RECV_ERRORS).increment(1);
                            warn!(topic = %self.topic, error = %err, "kafka recv error while consuming follower topic");
                            break;
                        }
                    }
                }
            } => {}
        }

        outcome
    }

    /// This follower's committable offsets, restricted to partitions the events consumer still
    /// owns — ownership is mirrored, so the events `owned` set is authoritative across all three
    /// co-partitioned topics. This is the *commit-side* owned filter only: the message-side gate
    /// (and its skip counters) lives in the dispatcher's `dispatch_merges`/`dispatch_transfers`.
    fn owned_committable_offsets(&self) -> HashMap<i32, i64> {
        restrict_to_owned(
            self.tracker().committable_offsets(),
            &self.dispatcher.owned_partitions(),
        )
    }
}

/// What one [`consume_batch`](FollowerConsumer::consume_batch) cycle gathered.
struct FollowerOutcome<T> {
    messages: Vec<T>,
    /// Empty or undecodable payloads, skipped (counted on the route's deserialize-error counter).
    deserialize_errors: u64,
    transport_error: bool,
}

/// Keep only the offsets of still-owned partitions. Pure (mirrors the events consumer's
/// `owned_committable_offsets` guard) so the restriction is unit-testable.
fn restrict_to_owned(offsets: HashMap<i32, i64>, owned: &[i32]) -> HashMap<i32, i64> {
    let owned: HashSet<i32> = owned.iter().copied().collect();
    offsets
        .into_iter()
        .filter(|(partition, _)| owned.contains(partition))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    use crate::merge::transfer::{TransferLeaf, MERGE_EVENT_SCHEMA_VERSION};
    use crate::stage1::key::LeafStateKey;
    use crate::stage1::state::{AppliedOffsets, Stage1State, StatefulRecord};

    fn merge_event() -> PersonMergeEvent {
        PersonMergeEvent {
            team_id: 42,
            old_person_uuid: Uuid::from_u128(0xAAAA),
            new_person_uuid: Uuid::from_u128(0xBBBB),
            merged_at_ms: 1_716_800_000_000,
            schema_version: MERGE_EVENT_SCHEMA_VERSION,
        }
    }

    fn transfer() -> MergeStateTransfer {
        MergeStateTransfer {
            team_id: 42,
            old_person_uuid: Uuid::from_u128(0xAAAA),
            new_person_uuid: Uuid::from_u128(0xBBBB),
            merged_at_ms: 1_716_800_000_000,
            source_partition: 17,
            source_offset: 12_345,
            leaves: vec![TransferLeaf::new(
                LeafStateKey([0xAB; 16]),
                StatefulRecord::new(
                    Stage1State::BehavioralSingle {
                        has_match: true,
                        last_event_at_ms: 1_700_000_000_000,
                        earliest_eviction_at_ms: i64::MAX,
                    },
                    AppliedOffsets::default(),
                ),
            )],
        }
    }

    #[test]
    fn merge_route_decodes_an_envelope_with_its_commit_coords() {
        let event = merge_event();

        let consumed = MergeRoute::decode(&event.encode(), 17, 12_345).unwrap();

        assert_eq!(consumed.event, event);
        assert_eq!(consumed.partition, 17);
        assert_eq!(consumed.offset, 12_345);
    }

    #[test]
    fn transfer_route_decodes_an_envelope_with_its_commit_coords() {
        let wire = transfer();

        let consumed = TransferRoute::decode(&wire.encode(), 9, 77).unwrap();

        assert_eq!(consumed.transfer, wire);
        assert_eq!(consumed.partition, 9);
        assert_eq!(consumed.offset, 77);
    }

    #[test]
    fn garbage_payloads_decode_to_err_for_both_routes() {
        assert!(MergeRoute::decode(b"not json", 0, 0).is_err());
        assert!(TransferRoute::decode(&[], 0, 0).is_err());
    }

    #[test]
    fn each_route_selects_its_own_tracker_from_the_merge_deps() {
        let deps = MergeWorkerDeps::capture();

        assert!(
            Arc::ptr_eq(MergeRoute::tracker(&deps), &deps.merge_tracker),
            "merge route must commit via the merge tracker (D7)"
        );
        assert!(
            Arc::ptr_eq(TransferRoute::tracker(&deps), &deps.transfer_tracker),
            "transfer route must commit via the transfer tracker (D7)"
        );
    }

    #[test]
    fn restrict_to_owned_keeps_only_owned_partitions() {
        let offsets: HashMap<i32, i64> = [(0, 10), (3, 30), (7, 70)].into_iter().collect();

        let restricted = restrict_to_owned(offsets, &[3, 7]);

        assert_eq!(restricted.len(), 2);
        assert_eq!(restricted.get(&0), None, "revoked partition is dropped");
        assert_eq!(restricted.get(&3), Some(&30));
        assert_eq!(restricted.get(&7), Some(&70));
    }

    #[test]
    fn restrict_to_owned_with_no_owned_partitions_is_empty() {
        let offsets: HashMap<i32, i64> = [(0, 10)].into_iter().collect();
        assert!(restrict_to_owned(offsets, &[]).is_empty());
    }
}
