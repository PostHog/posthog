//! Partition-affined routing. Maps a `cohort_stream_events` partition to its owning worker's
//! bounded channel and dispatches per-partition sub-batches, so every state mutation for a given
//! `(team_id, person_id)` serializes through exactly one worker (the worker-affinity invariant).
//! The router does not own the worker: [`PartitionRouter::add_partition`] hands the `Receiver` to
//! the caller.
//!
//! Two independent backpressure-isolation measures keep one slow partition from stalling the rest:
//! - the [`DashMap`] guard is dropped (by cloning the `Sender`) before any `.await`, so a blocking
//!   send never holds a shard lock against `add`/`remove`/`route`;
//! - per-partition sends fan out concurrently via [`join_all`](futures::future::join_all), so a
//!   full channel parks only itself within one [`route_batch`](PartitionRouter::route_batch) call.

use std::collections::HashMap;

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

// `reason` label values for `PARTITION_ROUTE_DROPPED_TOTAL`.
const REASON_NO_WORKER: &str = "no_worker";
const REASON_CHANNEL_CLOSED: &str = "channel_closed";

/// A per-partition routing failure surfaced by [`PartitionRouter::route_batch`] without failing the
/// rest of the batch. Both reasons mean the target worker is gone (usually a partition revoked
/// mid-rebalance); the dropped messages are recovered when Kafka replays the uncommitted offsets.
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
///
/// A worker channel must be registered via [`add_partition`](Self::add_partition) before
/// [`route_batch`](Self::route_batch) can reach it; routing to an unregistered partition yields a
/// [`RouteError`] rather than panicking, so a rebalance race degrades to dropped-and-replayed work.
pub struct PartitionRouter {
    /// Partition → the sending half of its worker's bounded channel (the receiving half is owned by
    /// the worker). `DashMap` shards so `add`/`remove`/`route` for different partitions don't contend.
    senders: DashMap<i32, mpsc::Sender<Vec<ShuffleMessage>>>,
    /// Bounded buffer for every per-partition channel — the backpressure knob.
    channel_buffer: usize,
}

impl PartitionRouter {
    pub fn new(channel_buffer: usize) -> Self {
        Self {
            senders: DashMap::new(),
            channel_buffer,
        }
    }

    /// Register a worker channel for `partition` and return its `Receiver`. Call synchronously from
    /// the partition-assignment callback.
    ///
    /// `Some(receiver)` on first registration. If already registered:
    /// - **Live channel**: reuse the existing sender and return `None` — a channel has one receiver,
    ///   so a second can't be handed out. Guards the revoke→assign race before cleanup has run.
    /// - **Closed channel** (receiver dropped): the previous worker exited without
    ///   [`remove_partition`](Self::remove_partition). Replace the orphaned sender with a fresh
    ///   channel and hand out the new `Receiver` so the partition self-heals instead of stranding.
    ///
    /// Self-heal is a safety net, **not** a substitute for cleanup: the caller must still run
    /// [`remove_partition`](Self::remove_partition) on every worker-exit path, because until the
    /// next reassignment a silently-dead worker keeps dropping (and Kafka replaying) its messages.
    pub fn add_partition(&self, partition: i32) -> Option<mpsc::Receiver<Vec<ShuffleMessage>>> {
        let receiver = match self.senders.entry(partition) {
            Entry::Occupied(mut slot) => {
                if slot.get().is_closed() {
                    // Orphaned sender from a worker that exited without `remove_partition`; replace it.
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
        // The `entry`/`insert` guard dropped with the match, so `len()` here can't deadlock our write.
        if receiver.is_some() {
            self.emit_active_gauge();
        }
        receiver
    }

    /// Drop the sender for `partition`, so the worker's next `recv()` returns `None` — its shutdown
    /// signal. Idempotent. Call during partition revocation.
    pub fn remove_partition(&self, partition: i32) {
        if self.senders.remove(&partition).is_some() {
            self.emit_active_gauge();
        }
    }

    /// Drop every sender at once, signalling all workers to drain and exit. Used on shutdown, where
    /// the router is shared (`Arc`) so it cannot be dropped to close the channels.
    pub fn clear(&self) {
        self.senders.clear();
        self.emit_active_gauge();
    }

    /// Group a mixed-partition batch by partition and dispatch each sub-batch to its worker,
    /// preserving per-partition arrival order (the affinity guarantee). Per-partition failures are
    /// collected into the returned `Vec` rather than aborting the batch.
    pub async fn route_batch(&self, messages: Vec<(i32, ShuffleMessage)>) -> Vec<RouteError> {
        if messages.is_empty() {
            return Vec::new();
        }

        let mut by_partition: HashMap<i32, Vec<ShuffleMessage>> = HashMap::new();
        for (partition, message) in messages {
            by_partition.entry(partition).or_default().push(message);
        }

        // `join_all` polls every send each poll, so a full channel parks only itself. The futures
        // borrow `&self` and are awaited in place (never spawned), so no `'static`/`Arc` is needed.
        let sends = by_partition
            .into_iter()
            .map(|(partition, batch)| self.send_to_partition(partition, batch));
        join_all(sends).await.into_iter().flatten().collect()
    }

    /// Dispatch one partition's sub-batch, returning the failure (if any) rather than propagating —
    /// the per-partition unit of [`route_batch`](Self::route_batch)'s fan-out, and the one place
    /// that accounts for a send.
    async fn send_to_partition(
        &self,
        partition: i32,
        batch: Vec<ShuffleMessage>,
    ) -> Option<RouteError> {
        let dropped = batch.len();

        // `sender_for` drops the `DashMap` guard before we await the send, so one full channel can't
        // block routing to the other partitions.
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

    /// Clone the partition's sender so the `DashMap` guard drops here, letting the caller `.await`
    /// without holding a shard lock.
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
        // Send-side approximation of queue depth: configured buffer minus currently-free slots.
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

    /// An event tagged by its `source_offset` so a routed sub-batch is identifiable without needing
    /// `PartialEq` on the foreign event type.
    fn event(tag: i64) -> ShuffleMessage {
        ShuffleMessage::Event {
            event: CohortStreamEvent {
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
            },
            cse_offset: 0,
        }
    }

    fn tags(batch: &[ShuffleMessage]) -> Vec<i64> {
        batch
            .iter()
            .map(|message| match message {
                ShuffleMessage::Event { event, .. } => event.source_offset,
                ShuffleMessage::Sweep { .. } => unreachable!("router tests route only events"),
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

        // A second route appends behind the first (FIFO per channel).
        assert!(router.route_batch(vec![(5, event(4))]).await.is_empty());
        assert_eq!(tags(&rx5.recv().await.unwrap()), vec![4]);
    }

    #[tokio::test]
    async fn routing_to_a_removed_partition_surfaces_an_error_without_panicking() {
        let router = PartitionRouter::new(16);
        // Keep the receiver alive to exercise the "sender removed" path, not "receiver dropped".
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
        // Rapid revoke→assign before cleanup ran: the existing channel is kept, no second receiver.
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
        drop(rx); // receiver dropped, sender still registered

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
        // A missing partition does not stop the others from routing.
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
        // Buffer of 1: fill partition 1's channel so its next send parks; partition 2's send must
        // still complete in the same `route_batch` call.
        let router = PartitionRouter::new(1);
        let mut rx1 = router.add_partition(1).unwrap();
        let mut rx2 = router.add_partition(2).unwrap();

        // Fill partition 1's single slot and never drain rx1, so its next send blocks.
        assert!(router.route_batch(vec![(1, event(100))]).await.is_empty());

        let routed = router.route_batch(vec![(1, event(1)), (2, event(2))]);
        tokio::pin!(routed);

        // One poll can't complete the call (partition 1 still full), but `join_all` polls every send
        // that poll, so partition 2 finishes. Sequential routing would block and never reach it.
        assert!(
            routed.as_mut().now_or_never().is_none(),
            "route_batch must stay pending while partition 1 is backpressured"
        );

        assert_eq!(tags(&rx2.try_recv().unwrap()), vec![2]);

        // Partition 1 still holds only the pre-fill; the new sub-batch is queued in the pending future.
        assert_eq!(tags(&rx1.try_recv().unwrap()), vec![100]);
        assert!(rx1.try_recv().is_err());
    }

    #[tokio::test]
    async fn re_adding_a_partition_whose_worker_died_without_revoke_self_heals() {
        // A worker that drops its receiver without `remove_partition` orphans the sender;
        // reassignment must replace the dead channel and hand out a fresh receiver.
        let router = PartitionRouter::new(16);
        let rx_dead = router.add_partition(5).unwrap();
        drop(rx_dead); // worker exited without revoke; sender now orphaned

        let mut rx_new = router
            .add_partition(5)
            .expect("closed slot self-heals to a fresh receiver");
        assert_eq!(router.partition_count(), 1);

        assert!(router.route_batch(vec![(5, event(7))]).await.is_empty());
        assert_eq!(tags(&rx_new.recv().await.unwrap()), vec![7]);
    }
}
