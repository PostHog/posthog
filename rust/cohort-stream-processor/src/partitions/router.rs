//! Partition-affined routing (TDD §2.3, §2.5). Maps a `cohort_stream_events` partition to its
//! owning worker's bounded channel and dispatches per-partition sub-batches to it, so that every
//! state mutation for a given `(team_id, person_id)` serializes through exactly one worker — the
//! §2.5 worker-affinity invariant the whole pipeline rests on.
//!
//! This lifts the *pattern*, not the bytes, from `rust/kafka-deduplicator`:
//! - the group-by-partition fan-out of `routing_processor.rs:64-78`, and
//! - the "clone the sender, release the [`DashMap`] guard before `.await`" discipline of
//!   `partition_router.rs:145-158`. Holding the guard across a blocking send would let one
//!   partition's backpressure stall routing to *every other* partition (and stall
//!   [`add_partition`]/[`remove_partition`] during a rebalance), so the guard is always dropped
//!   first by cloning the `Sender` out from under it.
//!
//! Unlike dedup, the router does **not** own the worker. [`PartitionRouter::add_partition`]
//! returns the channel `Receiver` for the caller (PR 1.6's `worker.rs`; tests drain it directly)
//! to own, which keeps the routing layer free of any Stage 1 concern for M1.
//!
//! Deferred (decision 3): dedup's `routing_processor` fans the per-partition sends out
//! concurrently via `join_all` so a slow channel never delays the others within one batch. M1
//! routes the grouped sub-batches sequentially to avoid pulling `futures` for the infra-only
//! slice; with no live worker draining yet (PR 1.6/1.7) there is nothing to delay. The
//! guard-release above already isolates partitions at the `DashMap` level. Promote to concurrent
//! fan-out when the live consumer lands.

use std::collections::HashMap;

use dashmap::mapref::entry::Entry;
use dashmap::DashMap;
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

/// A per-partition routing failure surfaced by [`PartitionRouter::route_batch`] *without* failing
/// the rest of the batch. Both reasons mean the target worker is gone — nearly always a partition
/// revoked mid-rebalance — so the messages for that partition were dropped here. At-least-once
/// delivery is recovered downstream: Kafka replays the uncommitted offsets after the rebalance
/// settles. The caller decides whether to log, count, or react.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum RouteError {
    /// No worker channel is registered for the partition (never assigned, or already revoked).
    #[error("no worker for partition {partition}: not assigned or revoked ({dropped} message(s) dropped)")]
    NoWorker { partition: i32, dropped: usize },

    /// The worker channel exists but its receiver was dropped, so the worker has stopped.
    #[error("worker channel for partition {partition} is closed ({dropped} message(s) dropped)")]
    ChannelClosed { partition: i32, dropped: usize },
}

/// Routes per-partition sub-batches to long-lived per-partition worker channels.
///
/// A worker channel must be registered via [`add_partition`](Self::add_partition) — synchronously,
/// during partition assignment — before [`route_batch`](Self::route_batch) can reach it. Routing
/// to an unregistered partition yields a [`RouteError`] rather than panicking, so a rebalance race
/// degrades to dropped-and-replayed work instead of a crash.
pub struct PartitionRouter {
    /// Partition → the sending half of that partition worker's bounded channel. The receiving half
    /// is owned by the worker (handed out by [`add_partition`](Self::add_partition)). Sharded
    /// locks (`DashMap`) keep `add`/`remove`/`route` for different partitions off each other's path.
    senders: DashMap<i32, mpsc::Sender<Vec<ShuffleMessage>>>,
    /// Bounded buffer applied to every per-partition channel — the backpressure knob (§2.3),
    /// sourced from `Config::partition_channel_buffer`.
    channel_buffer: usize,
}

impl PartitionRouter {
    pub fn new(channel_buffer: usize) -> Self {
        Self {
            senders: DashMap::new(),
            channel_buffer,
        }
    }

    /// Register a worker channel for `partition` and return its `Receiver` for the caller to own.
    ///
    /// Returns `Some(receiver)` the first time a partition is registered. Returns `None` if the
    /// partition is *already* registered: the existing sender — and therefore the existing worker
    /// — is reused, and since a channel has exactly one receiver, a second one cannot be handed
    /// out. This mirrors dedup's reuse-on-rapid-reassign behavior (`partition_router.rs:72-95`),
    /// which guards the revoke→assign race where the previous worker's cleanup has not run yet.
    ///
    /// Call this synchronously from the partition-assignment callback (PR 1.7).
    pub fn add_partition(&self, partition: i32) -> Option<mpsc::Receiver<Vec<ShuffleMessage>>> {
        let receiver = match self.senders.entry(partition) {
            Entry::Occupied(_) => {
                warn!(
                    partition,
                    "partition already registered; reusing the existing worker channel"
                );
                None
            }
            Entry::Vacant(slot) => {
                let (sender, receiver) = mpsc::channel(self.channel_buffer);
                slot.insert(sender);
                Some(receiver)
            }
        };
        // The `DashMap` guard from `entry`/`insert` is dropped with the match above, so reading
        // `len()` here cannot deadlock against our own shard write.
        if receiver.is_some() {
            self.emit_active_gauge();
        }
        receiver
    }

    /// Drop the sender for `partition`. The worker's next `recv()` then returns `None`, which is
    /// its shutdown signal (the dedup pattern). Idempotent — removing an unregistered partition is
    /// a no-op. Call this during partition revocation (PR 1.7).
    pub fn remove_partition(&self, partition: i32) {
        if self.senders.remove(&partition).is_some() {
            self.emit_active_gauge();
        }
    }

    /// Group a mixed-partition batch by partition and dispatch each sub-batch to its worker
    /// channel, preserving per-partition arrival order (the affinity guarantee). Per-partition
    /// failures are collected into the returned `Vec` instead of aborting the batch — mirrors
    /// dedup's "log and continue" (`routing_processor.rs:100-109`).
    pub async fn route_batch(&self, messages: Vec<(i32, ShuffleMessage)>) -> Vec<RouteError> {
        if messages.is_empty() {
            return Vec::new();
        }

        let mut by_partition: HashMap<i32, Vec<ShuffleMessage>> = HashMap::new();
        for (partition, message) in messages {
            by_partition.entry(partition).or_default().push(message);
        }

        let mut errors = Vec::new();
        for (partition, batch) in by_partition {
            let dropped = batch.len();

            // Clone the sender and let the `DashMap` guard drop *before* awaiting the send, so one
            // full channel can never block routing to the other partitions (the load-bearing
            // backpressure-isolation detail lifted from `partition_router.rs:145-158`).
            let Some(sender) = self.sender_for(partition) else {
                self.record_drop(partition, dropped, REASON_NO_WORKER);
                errors.push(RouteError::NoWorker { partition, dropped });
                continue;
            };

            match sender.send(batch).await {
                Ok(()) => self.emit_channel_depth(partition, &sender),
                Err(mpsc::error::SendError(returned)) => {
                    self.record_drop(partition, returned.len(), REASON_CHANNEL_CLOSED);
                    errors.push(RouteError::ChannelClosed {
                        partition,
                        dropped: returned.len(),
                    });
                }
            }
        }
        errors
    }

    /// Number of partitions with a registered worker channel.
    pub fn partition_count(&self) -> usize {
        self.senders.len()
    }

    /// Clone a partition's channel sender, releasing the `DashMap` guard immediately so the caller
    /// can `.await` on the clone without holding a shard lock. Mirrors dedup's `get_partition_sender`.
    fn sender_for(&self, partition: i32) -> Option<mpsc::Sender<Vec<ShuffleMessage>>> {
        let sender = self.senders.get(&partition)?;
        Some(sender.clone())
        // The `Ref` guard is dropped here as the borrow ends.
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

    /// An event tagged by its `source_offset` so a routed sub-batch can be identified by tag
    /// without needing `PartialEq` on the (foreign) event type.
    fn event(tag: i64) -> ShuffleMessage {
        ShuffleMessage::Event(Box::new(CohortStreamEvent {
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
        }))
    }

    /// Project a received sub-batch back to its tags, in order.
    fn tags(batch: &[ShuffleMessage]) -> Vec<i64> {
        batch
            .iter()
            .map(|message| match message {
                ShuffleMessage::Event(event) => event.source_offset,
            })
            .collect()
    }

    #[tokio::test]
    async fn same_partition_messages_land_on_one_channel_in_order_isolated_per_partition() {
        // Acceptance #1: same-key always lands on the same worker (affinity + ordering + isolation).
        let router = PartitionRouter::new(16);
        let mut rx5 = router
            .add_partition(5)
            .expect("first add returns the receiver");
        let mut rx6 = router
            .add_partition(6)
            .expect("first add returns the receiver");

        // A single mixed batch tagged [(5,1), (6,2), (5,3)].
        let errors = router
            .route_batch(vec![(5, event(1)), (6, event(2)), (5, event(3))])
            .await;
        assert!(errors.is_empty(), "no worker should be missing");

        // Partition 5's worker receives exactly its messages, in arrival order; 6 receives only its own.
        assert_eq!(tags(&rx5.recv().await.unwrap()), vec![1, 3]);
        assert_eq!(tags(&rx6.recv().await.unwrap()), vec![2]);

        // A second route to partition 5 appends a new sub-batch behind the first (FIFO per channel).
        assert!(router.route_batch(vec![(5, event(4))]).await.is_empty());
        assert_eq!(tags(&rx5.recv().await.unwrap()), vec![4]);
    }

    #[tokio::test]
    async fn routing_to_a_removed_partition_surfaces_an_error_without_panicking() {
        let router = PartitionRouter::new(16);
        // Keep the receiver alive so we exercise the "sender removed" path, not "receiver dropped".
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
        // Rapid revoke→assign where cleanup has not run: the existing worker channel is kept and
        // no second receiver is handed out.
        let router = PartitionRouter::new(16);
        let mut rx = router.add_partition(5).unwrap();

        assert!(router.add_partition(5).is_none());
        assert_eq!(router.partition_count(), 1);

        // Routing still reaches the original receiver.
        assert!(router.route_batch(vec![(5, event(1))]).await.is_empty());
        assert_eq!(tags(&rx.recv().await.unwrap()), vec![1]);
    }

    #[tokio::test]
    async fn routing_after_the_worker_dropped_its_receiver_reports_channel_closed() {
        let router = PartitionRouter::new(16);
        let rx = router.add_partition(5).unwrap();
        drop(rx); // worker stopped and dropped its receiver, but the sender is still registered

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
        // Isolation: a missing partition does not stop other partitions from being routed.
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
}
