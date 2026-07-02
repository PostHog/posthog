//! Partition-affined routing. Maps a `cohort_stream_events` partition to its owning worker's
//! bounded channel and dispatches per-partition sub-batches, so every state mutation for a given
//! `(team_id, person_id)` serializes through exactly one worker.
//!
//! A slow partition cannot stall the rest: the `DashMap` guard is cloned (dropped) before any
//! `.await`, and per-partition sends fan out concurrently via `join_all`.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};

use dashmap::mapref::entry::Entry;
use dashmap::DashMap;
use futures::future::join_all;
use metrics::{counter, gauge};
use thiserror::Error;
use tokio::sync::mpsc;
use tokio::sync::mpsc::error::TrySendError;
use tracing::warn;

use super::shuffle_message::ShuffleMessage;
use crate::observability::metrics::{
    PARTITIONS_ACTIVE, PARTITION_CHANNEL_DEPTH, PARTITION_CHANNEL_FULL_TOTAL,
    PARTITION_ROUTE_DROPPED_TOTAL,
};

const REASON_NO_WORKER: &str = "no_worker";
const REASON_CHANNEL_CLOSED: &str = "channel_closed";

/// A per-partition routing failure. The target worker is gone (usually revoked mid-rebalance);
/// dropped messages are recovered when Kafka replays the uncommitted offsets.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum RouteError {
    /// No worker channel registered for the partition (never assigned, or already revoked).
    #[error("no worker for partition {partition}: not assigned or revoked ({dropped} message(s) dropped)")]
    NoWorker { partition: i32, dropped: usize },

    /// The channel exists but its receiver was dropped, so the worker has stopped.
    #[error("worker channel for partition {partition} is closed ({dropped} message(s) dropped)")]
    ChannelClosed { partition: i32, dropped: usize },
}

/// Per-partition result of [`try_route_batch`](PartitionRouter::try_route_batch). `Full` is
/// backpressure — the events are returned to be held and retried — not a drop.
#[derive(Debug)]
pub enum SendOutcome {
    /// Delivered. `max_offset` is the highest event offset — used to raise the dispatch ceiling, and
    /// `None` for a batch that carries no events (no offset to ceiling on); `count` the number of
    /// messages delivered.
    Sent {
        max_offset: Option<i64>,
        count: usize,
    },
    /// Channel full: carries the un-sent sub-batch to hold, pause, and redispatch. No drop recorded.
    Full(Vec<ShuffleMessage>),
    /// No worker registered (never assigned, or revoked): dropped and recorded; Kafka replays.
    NoWorker,
    /// Worker channel closed (worker exited): dropped and recorded; Kafka replays.
    ChannelClosed,
}

/// Routes per-partition sub-batches to long-lived per-partition worker channels.
pub struct PartitionRouter {
    senders: DashMap<i32, mpsc::Sender<Vec<ShuffleMessage>>>,
    channel_buffer: usize,
    /// Terminal: set by [`clear`](Self::clear), never unset. Read under the shard guard so no
    /// sender can be registered after the clear's removal pass.
    closed: AtomicBool,
}

impl PartitionRouter {
    pub fn new(channel_buffer: usize) -> Self {
        Self {
            senders: DashMap::new(),
            channel_buffer,
            closed: AtomicBool::new(false),
        }
    }

    /// Register a worker channel for `partition` and return its `Receiver`.
    ///
    /// Returns `None` if: already registered with a live channel (reuses existing), or the router
    /// is closed. If the existing channel is dead (receiver dropped), replaces it (self-heal).
    pub fn add_partition(&self, partition: i32) -> Option<mpsc::Receiver<Vec<ShuffleMessage>>> {
        let entry = self.senders.entry(partition);
        if self.closed.load(Ordering::SeqCst) {
            drop(entry);
            warn!(
                partition,
                "router is closed (cleared for shutdown); refusing to register a worker channel"
            );
            return None;
        }
        let receiver = match entry {
            Entry::Occupied(mut slot) => {
                if slot.get().is_closed() {
                    let (sender, receiver) = mpsc::channel(self.channel_buffer);
                    slot.insert(sender);
                    warn!(
                        partition,
                        "replacing closed worker channel on reassign (previous worker exited without revoke)"
                    );
                    Some(receiver)
                } else {
                    warn!(
                        partition,
                        "partition already registered; reusing the existing worker channel"
                    );
                    None
                }
            }
            Entry::Vacant(slot) => {
                let (sender, receiver) = mpsc::channel(self.channel_buffer);
                slot.insert(sender);
                Some(receiver)
            }
        };
        if receiver.is_some() {
            self.emit_active_gauge();
        }
        receiver
    }

    /// Drop the sender for `partition`, signalling the worker to shut down. Idempotent.
    pub fn remove_partition(&self, partition: i32) {
        if self.senders.remove(&partition).is_some() {
            self.emit_active_gauge();
        }
    }

    /// Drop every sender and terminally close the router. All later `add_partition` calls refuse.
    pub fn clear(&self) {
        self.closed.store(true, Ordering::SeqCst);
        self.senders.clear();
        self.emit_active_gauge();
    }

    /// Whether the router has been terminally closed.
    pub fn is_closed(&self) -> bool {
        self.closed.load(Ordering::SeqCst)
    }

    /// Group a batch by partition and dispatch each sub-batch to its worker, preserving
    /// per-partition order. Per-partition failures are collected rather than aborting the batch.
    pub async fn route_batch(&self, messages: Vec<(i32, ShuffleMessage)>) -> Vec<RouteError> {
        if messages.is_empty() {
            return Vec::new();
        }

        let mut by_partition: HashMap<i32, Vec<ShuffleMessage>> = HashMap::new();
        for (partition, message) in messages {
            by_partition.entry(partition).or_default().push(message);
        }

        let sends = by_partition
            .into_iter()
            .map(|(partition, batch)| self.send_to_partition(partition, batch));
        join_all(sends).await.into_iter().flatten().collect()
    }

    async fn send_to_partition(
        &self,
        partition: i32,
        batch: Vec<ShuffleMessage>,
    ) -> Option<RouteError> {
        let dropped = batch.len();

        let Some(sender) = self.sender_for(partition) else {
            self.record_drop(partition, dropped, REASON_NO_WORKER);
            return Some(RouteError::NoWorker { partition, dropped });
        };

        match sender.send(batch).await {
            Ok(()) => {
                self.emit_channel_depth(partition, &sender);
                None
            }
            Err(mpsc::error::SendError(returned)) => {
                self.record_drop(partition, returned.len(), REASON_CHANNEL_CLOSED);
                Some(RouteError::ChannelClosed {
                    partition,
                    dropped: returned.len(),
                })
            }
        }
    }

    /// Non-blocking sibling of [`route_batch`](Self::route_batch): group by partition and `try_send`
    /// each sub-batch, returning the per-partition [`SendOutcome`] instead of awaiting a drain.
    pub fn try_route_batch(
        &self,
        messages: Vec<(i32, ShuffleMessage)>,
    ) -> HashMap<i32, SendOutcome> {
        if messages.is_empty() {
            return HashMap::new();
        }
        let mut by_partition: HashMap<i32, Vec<ShuffleMessage>> = HashMap::new();
        for (partition, message) in messages {
            by_partition.entry(partition).or_default().push(message);
        }
        by_partition
            .into_iter()
            .map(|(partition, batch)| (partition, self.try_send_to_partition(partition, batch)))
            .collect()
    }

    fn try_send_to_partition(&self, partition: i32, batch: Vec<ShuffleMessage>) -> SendOutcome {
        let Some(sender) = self.sender_for(partition) else {
            self.record_drop(partition, batch.len(), REASON_NO_WORKER);
            return SendOutcome::NoWorker;
        };
        let count = batch.len();
        // `None` for a batch carrying no events. Carried through as-is rather than defaulted to 0, so a
        // future non-Event caller can't fabricate a ceiling; `route_and_fold` only marks when `Some`.
        let max_offset = batch.iter().filter_map(ShuffleMessage::event_offset).max();
        match sender.try_send(batch) {
            Ok(()) => {
                self.emit_channel_depth(partition, &sender);
                SendOutcome::Sent { max_offset, count }
            }
            Err(TrySendError::Full(returned)) => {
                counter!(PARTITION_CHANNEL_FULL_TOTAL, "partition" => partition.to_string())
                    .increment(returned.len() as u64);
                SendOutcome::Full(returned)
            }
            Err(TrySendError::Closed(returned)) => {
                self.record_drop(partition, returned.len(), REASON_CHANNEL_CLOSED);
                SendOutcome::ChannelClosed
            }
        }
    }

    pub fn partition_count(&self) -> usize {
        self.senders.len()
    }

    /// Whether a worker channel is registered for `partition`.
    ///
    /// A registered-but-closed channel (a worker that exited without a revoke) still returns `true`:
    /// this gates maintenance-tick fan-out, and a tick to such a partition should still be attempted
    /// so it surfaces as `channel_closed` rather than being silently skipped. Only a partition with no
    /// channel at all — the idle steady state — is reported absent, letting a tick skip the guaranteed
    /// `no_worker` no-op.
    pub fn has_partition(&self, partition: i32) -> bool {
        self.senders.contains_key(&partition)
    }

    fn sender_for(&self, partition: i32) -> Option<mpsc::Sender<Vec<ShuffleMessage>>> {
        let sender = self.senders.get(&partition)?;
        Some(sender.clone())
    }

    fn record_drop(&self, partition: i32, dropped: usize, reason: &'static str) {
        warn!(
            partition,
            dropped, reason, "dropped messages while routing: target worker is gone"
        );
        counter!(PARTITION_ROUTE_DROPPED_TOTAL, "reason" => reason).increment(dropped as u64);
    }

    fn emit_channel_depth(&self, partition: i32, sender: &mpsc::Sender<Vec<ShuffleMessage>>) {
        let depth = sender.max_capacity().saturating_sub(sender.capacity());
        gauge!(PARTITION_CHANNEL_DEPTH, "partition" => partition.to_string()).set(depth as f64);
    }

    fn emit_active_gauge(&self) {
        gauge!(PARTITIONS_ACTIVE).set(self.senders.len() as f64);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::consumers::events::CohortStreamEvent;
    use futures::future::FutureExt;

    fn event(tag: i64) -> ShuffleMessage {
        ShuffleMessage::Event {
            event: Box::new(CohortStreamEvent {
                team_id: 1,
                person_id: "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
                distinct_id: "d".to_string(),
                uuid: "u".to_string(),
                event: "$pageview".to_string(),
                timestamp: "2026-05-26 12:34:56.789000".to_string(),
                properties: None,
                person_properties: None,
                elements_chain: None,
                source_offset: tag,
                source_partition: 0,
                redirected_from: None,
                redirect_hops: 0,
            }),
            cse_offset: 0,
        }
    }

    fn tags(batch: &[ShuffleMessage]) -> Vec<i64> {
        batch
            .iter()
            .map(|message| match message {
                ShuffleMessage::Event { event, .. } => event.source_offset,
                ShuffleMessage::Sweep { .. }
                | ShuffleMessage::Merge { .. }
                | ShuffleMessage::Transfer { .. }
                | ShuffleMessage::Cascade { .. }
                | ShuffleMessage::RedrivePendingTransfers
                | ShuffleMessage::MergeCfGc { .. } => {
                    unreachable!("router tests route only events")
                }
            })
            .collect()
    }

    #[tokio::test]
    async fn same_partition_messages_land_on_one_channel_in_order_isolated_per_partition() {
        let router = PartitionRouter::new(16);
        let mut rx5 = router
            .add_partition(5)
            .expect("first add returns the receiver");
        let mut rx6 = router
            .add_partition(6)
            .expect("first add returns the receiver");

        let errors = router
            .route_batch(vec![(5, event(1)), (6, event(2)), (5, event(3))])
            .await;
        assert!(errors.is_empty(), "no worker should be missing");

        assert_eq!(tags(&rx5.recv().await.unwrap()), vec![1, 3]);
        assert_eq!(tags(&rx6.recv().await.unwrap()), vec![2]);

        assert!(router.route_batch(vec![(5, event(4))]).await.is_empty());
        assert_eq!(tags(&rx5.recv().await.unwrap()), vec![4]);
    }

    #[tokio::test]
    async fn routing_to_a_removed_partition_surfaces_an_error_without_panicking() {
        let router = PartitionRouter::new(16);
        let _rx5 = router.add_partition(5).unwrap();

        router.remove_partition(5);
        assert_eq!(router.partition_count(), 0);

        let errors = router.route_batch(vec![(5, event(1))]).await;
        assert_eq!(
            errors,
            vec![RouteError::NoWorker {
                partition: 5,
                dropped: 1
            }]
        );
    }

    #[tokio::test]
    async fn re_adding_a_partition_after_removal_routes_cleanly() {
        let router = PartitionRouter::new(16);
        let _rx_old = router.add_partition(5).unwrap();
        router.remove_partition(5);

        let mut rx_new = router
            .add_partition(5)
            .expect("re-add after removal yields a fresh receiver");
        assert!(router.route_batch(vec![(5, event(9))]).await.is_empty());
        assert_eq!(tags(&rx_new.recv().await.unwrap()), vec![9]);
    }

    #[tokio::test]
    async fn re_adding_an_active_partition_reuses_the_channel() {
        let router = PartitionRouter::new(16);
        let mut rx = router.add_partition(5).unwrap();

        assert!(router.add_partition(5).is_none());
        assert_eq!(router.partition_count(), 1);

        assert!(router.route_batch(vec![(5, event(1))]).await.is_empty());
        assert_eq!(tags(&rx.recv().await.unwrap()), vec![1]);
    }

    #[tokio::test]
    async fn routing_after_the_worker_dropped_its_receiver_reports_channel_closed() {
        let router = PartitionRouter::new(16);
        let rx = router.add_partition(5).unwrap();
        drop(rx);

        let errors = router.route_batch(vec![(5, event(1)), (5, event(2))]).await;
        assert_eq!(
            errors,
            vec![RouteError::ChannelClosed {
                partition: 5,
                dropped: 2
            }]
        );
    }

    #[tokio::test]
    async fn mixed_batch_with_one_missing_partition_routes_the_rest() {
        let router = PartitionRouter::new(16);
        let mut rx5 = router.add_partition(5).unwrap();

        let errors = router
            .route_batch(vec![(5, event(1)), (7, event(2)), (5, event(3))])
            .await;

        assert_eq!(
            errors,
            vec![RouteError::NoWorker {
                partition: 7,
                dropped: 1
            }]
        );
        assert_eq!(tags(&rx5.recv().await.unwrap()), vec![1, 3]);
    }

    #[tokio::test]
    async fn empty_batch_is_a_no_op() {
        let router = PartitionRouter::new(16);
        assert!(router.route_batch(vec![]).await.is_empty());
    }

    #[tokio::test]
    async fn route_batch_fans_out_so_a_full_channel_does_not_block_other_partitions() {
        let router = PartitionRouter::new(1);
        let mut rx1 = router.add_partition(1).unwrap();
        let mut rx2 = router.add_partition(2).unwrap();

        assert!(router.route_batch(vec![(1, event(100))]).await.is_empty());

        let routed = router.route_batch(vec![(1, event(1)), (2, event(2))]);
        tokio::pin!(routed);

        assert!(
            routed.as_mut().now_or_never().is_none(),
            "route_batch must stay pending while partition 1 is backpressured"
        );

        assert_eq!(tags(&rx2.try_recv().unwrap()), vec![2]);

        assert_eq!(tags(&rx1.try_recv().unwrap()), vec![100]);
        assert!(rx1.try_recv().is_err());
    }

    #[tokio::test]
    async fn clear_closes_the_router_so_add_partition_refuses() {
        let router = PartitionRouter::new(16);
        let mut rx = router.add_partition(5).unwrap();

        router.clear();
        assert!(router.is_closed());
        assert!(rx.recv().await.is_none(), "clear dropped the live sender");

        assert!(
            router.add_partition(5).is_none(),
            "re-registration after clear is refused",
        );
        assert!(
            router.add_partition(6).is_none(),
            "first-time registration after clear is refused too",
        );
        assert_eq!(router.partition_count(), 0, "nothing was inserted");

        let errors = router.route_batch(vec![(5, event(1))]).await;
        assert_eq!(
            errors,
            vec![RouteError::NoWorker {
                partition: 5,
                dropped: 1
            }]
        );
    }

    #[tokio::test]
    async fn re_adding_a_partition_whose_worker_died_without_revoke_self_heals() {
        let router = PartitionRouter::new(16);
        let rx_dead = router.add_partition(5).unwrap();
        drop(rx_dead);

        let mut rx_new = router
            .add_partition(5)
            .expect("closed slot self-heals to a fresh receiver");
        assert_eq!(router.partition_count(), 1);

        assert!(router.route_batch(vec![(5, event(7))]).await.is_empty());
        assert_eq!(tags(&rx_new.recv().await.unwrap()), vec![7]);
    }

    /// An event whose `cse_offset` matches its `source_offset` tag, so [`tags`] and `max_offset`
    /// assertions line up.
    fn event_off(cse_offset: i64) -> ShuffleMessage {
        match event(cse_offset) {
            ShuffleMessage::Event { event, .. } => ShuffleMessage::Event { event, cse_offset },
            other => other,
        }
    }

    #[tokio::test]
    async fn try_route_batch_delivers_and_reports_the_max_offset_and_count() {
        let router = PartitionRouter::new(16);
        let mut rx5 = router.add_partition(5).unwrap();
        let mut rx6 = router.add_partition(6).unwrap();

        let mut outcomes = router.try_route_batch(vec![
            (5, event_off(1)),
            (6, event_off(2)),
            (5, event_off(3)),
        ]);

        match outcomes.remove(&5) {
            Some(SendOutcome::Sent { max_offset, count }) => {
                assert_eq!((max_offset, count), (Some(3), 2));
            }
            other => panic!("expected Sent for 5, got {other:?}"),
        }
        match outcomes.remove(&6) {
            Some(SendOutcome::Sent { max_offset, count }) => {
                assert_eq!((max_offset, count), (Some(2), 1));
            }
            other => panic!("expected Sent for 6, got {other:?}"),
        }
        assert_eq!(tags(&rx5.try_recv().unwrap()), vec![1, 3]);
        assert_eq!(tags(&rx6.try_recv().unwrap()), vec![2]);
    }

    #[tokio::test]
    async fn try_route_batch_returns_the_batch_on_full_without_recording_a_drop() {
        let router = PartitionRouter::new(1);
        let mut rx = router.add_partition(1).unwrap();

        // Saturate the slot, then the next try hands the batch back untouched.
        assert!(matches!(
            router.try_route_batch(vec![(1, event_off(100))]).remove(&1),
            Some(SendOutcome::Sent { .. }),
        ));

        match router.try_route_batch(vec![(1, event_off(7))]).remove(&1) {
            Some(SendOutcome::Full(returned)) => assert_eq!(tags(&returned), vec![7]),
            other => panic!("expected Full, got {other:?}"),
        }
        assert_eq!(tags(&rx.try_recv().unwrap()), vec![100]);
        assert!(rx.try_recv().is_err());
    }

    #[tokio::test]
    async fn try_route_batch_reports_no_worker_and_channel_closed() {
        let router = PartitionRouter::new(16);
        assert!(matches!(
            router.try_route_batch(vec![(9, event_off(1))]).remove(&9),
            Some(SendOutcome::NoWorker),
        ));

        let rx = router.add_partition(3).unwrap();
        drop(rx);
        assert!(matches!(
            router.try_route_batch(vec![(3, event_off(1))]).remove(&3),
            Some(SendOutcome::ChannelClosed),
        ));
    }

    #[tokio::test]
    async fn try_route_batch_isolates_a_full_partition_from_a_free_one() {
        let router = PartitionRouter::new(1);
        let mut rx2 = router.add_partition(2).unwrap();
        let _rx1 = router.add_partition(1).unwrap();
        router.try_route_batch(vec![(1, event_off(100))]);

        let mut outcomes = router.try_route_batch(vec![(1, event_off(1)), (2, event_off(2))]);
        assert!(matches!(outcomes.remove(&1), Some(SendOutcome::Full(_))));
        assert!(matches!(
            outcomes.remove(&2),
            Some(SendOutcome::Sent { .. })
        ));
        assert_eq!(tags(&rx2.try_recv().unwrap()), vec![2]);
    }

    #[tokio::test]
    async fn try_route_batch_is_empty_for_an_empty_batch() {
        let router = PartitionRouter::new(16);
        assert!(router.try_route_batch(vec![]).is_empty());
    }

    #[tokio::test]
    async fn has_partition_tracks_registration_not_channel_liveness() {
        let router = PartitionRouter::new(16);
        assert!(!router.has_partition(5), "absent before any registration");

        let rx = router.add_partition(5).unwrap();
        assert!(
            router.has_partition(5),
            "present once a channel is registered"
        );

        // Worker exited without a revoke: the channel is closed but still registered. It must stay
        // "present" so a maintenance tick still attempts it and surfaces `channel_closed`, rather than
        // being silently skipped as if it were idle.
        drop(rx);
        assert!(
            router.has_partition(5),
            "a closed-but-registered channel still counts as present",
        );

        router.remove_partition(5);
        assert!(!router.has_partition(5), "absent after removal");
    }
}
