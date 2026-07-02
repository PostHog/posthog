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
use tracing::warn;

use super::shuffle_message::ShuffleMessage;
use crate::observability::metrics::{
    PARTITIONS_ACTIVE, PARTITION_CHANNEL_DEPTH, PARTITION_ROUTE_DROPPED_TOTAL,
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
