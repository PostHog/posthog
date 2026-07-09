//! Merge-protocol follower consumers: `person_merge_events` (drain trigger, keyed by P_old) and
//! `cohort_merge_state_transfer` (packaged state, keyed by P_new).
//!
//! Both use [`FollowerConsumer`] generic over a [`FollowerRoute`]. Followers never `subscribe()` —
//! the events group's rebalance mirrors partition ownership onto them.

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

use crate::cascade::CascadeMessage;
use crate::consumers::events::{fsync_then_commit, EventDispatcher, RECV_ERROR_BACKOFF};
use crate::merge::transfer::{MergeStateTransfer, PersonMergeEvent};
use crate::observability::metrics::{
    COHORT_STREAM_CASCADES_CONSUMED, COHORT_STREAM_CASCADES_CONSUME_BATCH_SIZE,
    COHORT_STREAM_CASCADE_DESERIALIZE_ERRORS, COHORT_STREAM_KAFKA_RECV_ERRORS,
    COHORT_STREAM_MERGES_CONSUMED, COHORT_STREAM_MERGES_CONSUME_BATCH_SIZE,
    COHORT_STREAM_MERGE_DESERIALIZE_ERRORS, COHORT_STREAM_TRANSFERS_CONSUMED,
    COHORT_STREAM_TRANSFERS_CONSUME_BATCH_SIZE, COHORT_STREAM_TRANSFER_DESERIALIZE_ERRORS,
};
use crate::partitions::offset_tracker::OffsetTracker;
use crate::workers::MergeWorkerDeps;

/// One merge trigger consumed from `person_merge_events`, paired with its commit coordinates.
#[derive(Debug)]
pub struct ConsumedMerge {
    pub event: PersonMergeEvent,
    pub partition: i32,
    pub offset: i64,
}

/// One state transfer consumed from `cohort_merge_state_transfer`, paired with its commit
/// coordinates. Replay idempotence is keyed by the transfer's source merge-message coordinates
/// (`source_partition` + `source_offset`).
#[derive(Debug)]
pub struct ConsumedTransfer {
    pub transfer: MergeStateTransfer,
    pub partition: i32,
    pub offset: i64,
}

/// One cohort flip consumed from `cohort_cascade_events`, paired with its commit coordinates.
/// Replay idempotence is the handler's own bit-flip check (no stored offset field).
#[derive(Debug)]
pub struct ConsumedCascade {
    pub message: CascadeMessage,
    pub partition: i32,
    pub offset: i64,
}

/// How a follower topic's payload decodes and which dispatcher entry point routes the batch.
#[async_trait]
pub trait FollowerRoute: Send + Sync + 'static {
    type Consumed: Send + 'static;
    const KIND: &'static str;
    const CONSUMED_TOTAL: &'static str;
    const DESERIALIZE_ERRORS_TOTAL: &'static str;
    const CONSUME_BATCH_SIZE: &'static str;

    /// The route-specific commit tracker. Each route selects its own so commits never cross topics.
    fn tracker(deps: &MergeWorkerDeps) -> &Arc<OffsetTracker>;

    /// Decode one payload into its consumed envelope.
    fn decode(
        payload: &[u8],
        partition: i32,
        offset: i64,
    ) -> Result<Self::Consumed, serde_json::Error>;

    /// Hand a decoded batch to the dispatcher.
    async fn dispatch(dispatcher: &EventDispatcher, batch: Vec<Self::Consumed>);
}

/// P_old-keyed merge triggers into [`EventDispatcher::dispatch_merges`].
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

/// P_new-keyed packaged drains into [`EventDispatcher::dispatch_transfers`].
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

/// `(team, person)`-keyed cohort flips into [`EventDispatcher::dispatch_cascade`].
pub struct CascadeRoute;

#[async_trait]
impl FollowerRoute for CascadeRoute {
    type Consumed = ConsumedCascade;
    const KIND: &'static str = "cohort_cascade_events";
    const CONSUMED_TOTAL: &'static str = COHORT_STREAM_CASCADES_CONSUMED;
    const DESERIALIZE_ERRORS_TOTAL: &'static str = COHORT_STREAM_CASCADE_DESERIALIZE_ERRORS;
    const CONSUME_BATCH_SIZE: &'static str = COHORT_STREAM_CASCADES_CONSUME_BATCH_SIZE;

    fn tracker(deps: &MergeWorkerDeps) -> &Arc<OffsetTracker> {
        &deps.cascade_tracker
    }

    fn decode(
        payload: &[u8],
        partition: i32,
        offset: i64,
    ) -> Result<Self::Consumed, serde_json::Error> {
        serde_json::from_slice::<CascadeMessage>(payload).map(|message| ConsumedCascade {
            message,
            partition,
            offset,
        })
    }

    async fn dispatch(dispatcher: &EventDispatcher, batch: Vec<Self::Consumed>) {
        dispatcher.dispatch_cascade(batch).await;
    }
}

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

    fn tracker(&self) -> &Arc<OffsetTracker> {
        R::tracker(self.dispatcher.merge_deps())
    }

    pub async fn process(self) {
        let _guard = self.handle.process_scope();
        info!(topic = %self.topic, "follower consume loop starting");

        let mut commit_deadline = tokio::time::Instant::now() + self.offset_commit_interval;

        loop {
            tokio::select! {
                biased;
                _ = self.handle.shutdown_recv() => {
                    info!(topic = %self.topic, "shutdown signal received, stopping follower consume loop");
                    break;
                }
                outcome = self.consume_batch() => {
                    self.handle_outcome(outcome).await;
                    let now = tokio::time::Instant::now();
                    if now >= commit_deadline {
                        fsync_then_commit(
                            self.dispatcher.handle(),
                            &self.consumer,
                            self.tracker(),
                            self.owned_committable_offsets(),
                            &self.topic,
                            CommitMode::Async,
                        )
                        .await;
                        commit_deadline = now + self.offset_commit_interval;
                    }
                }
            }
        }

        // Final sync commit runs before the events consumer's shutdown; workers may still be marking
        // offsets at this point, but follower offsets are independent.
        fsync_then_commit(
            self.dispatcher.handle(),
            &self.consumer,
            self.tracker(),
            self.owned_committable_offsets(),
            &self.topic,
            CommitMode::Sync,
        )
        .await;
        info!(topic = %self.topic, "follower consume loop stopped");
    }

    async fn handle_outcome(&self, outcome: FollowerOutcome<R::Consumed>) {
        histogram!(R::CONSUME_BATCH_SIZE).record(outcome.messages.len() as f64);
        if !outcome.messages.is_empty() {
            counter!(R::CONSUMED_TOTAL).increment(outcome.messages.len() as u64);
        }
        if outcome.deserialize_errors > 0 {
            counter!(R::DESERIALIZE_ERRORS_TOTAL).increment(outcome.deserialize_errors);
        }

        // Follower keeps the blocking dispatch on purpose: merges/transfers/cascades are low-volume, so
        // a full channel here can await a drain without risking the heartbeat — unlike the events
        // consumer's non-blocking, partition-pausing path (`EventDispatcher::dispatch_events_nonblocking`).
        // Port that path here if any of these topics ever approaches events-topic volume.
        R::dispatch(&self.dispatcher, outcome.messages).await;

        if outcome.transport_error {
            tokio::time::sleep(RECV_ERROR_BACKOFF).await;
        } else {
            self.handle.report_healthy();
        }
    }

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

    fn owned_committable_offsets(&self) -> HashMap<i32, i64> {
        restrict_to_owned(
            self.tracker().committable_offsets(),
            &self.dispatcher.owned_partitions(),
        )
    }
}

struct FollowerOutcome<T> {
    messages: Vec<T>,
    deserialize_errors: u64,
    transport_error: bool,
}

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
            forward_hops: 0,

            person_dedup: None,
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

    fn cascade_message() -> CascadeMessage {
        crate::cascade::first_cascade(
            crate::producer::CohortMembershipChange {
                team_id: 42,
                cohort_id: 91204,
                person_id: Uuid::from_u128(0xCAFE).to_string(),
                last_updated: "2026-05-26 12:34:56.789000".to_string(),
                status: crate::producer::MembershipStatus::Entered,
            },
            123,
        )
    }

    #[test]
    fn cascade_route_decodes_an_envelope_with_its_commit_coords() {
        let wire = cascade_message();

        let consumed = CascadeRoute::decode(&serde_json::to_vec(&wire).unwrap(), 5, 88).unwrap();

        assert_eq!(consumed.message, wire);
        assert_eq!(consumed.partition, 5);
        assert_eq!(consumed.offset, 88);
    }

    #[test]
    fn garbage_payloads_decode_to_err_for_every_route() {
        assert!(MergeRoute::decode(b"not json", 0, 0).is_err());
        assert!(TransferRoute::decode(&[], 0, 0).is_err());
        assert!(CascadeRoute::decode(b"not json", 0, 0).is_err());
    }

    #[test]
    fn each_route_selects_its_own_tracker_from_the_merge_deps() {
        let deps = MergeWorkerDeps::capture();

        assert!(
            Arc::ptr_eq(MergeRoute::tracker(&deps), &deps.merge_tracker),
            "merge route must commit via the merge tracker"
        );
        assert!(
            Arc::ptr_eq(TransferRoute::tracker(&deps), &deps.transfer_tracker),
            "transfer route must commit via the transfer tracker"
        );
        assert!(
            Arc::ptr_eq(CascadeRoute::tracker(&deps), &deps.cascade_tracker),
            "cascade route must commit via the cascade tracker"
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
