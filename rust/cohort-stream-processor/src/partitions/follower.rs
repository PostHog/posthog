//! Assignment mirroring for the internal follower consumers.
//!
//! The follower consumers (`person_merge_events`, `cohort_merge_state_transfer`, and — when the
//! cascade gate is on — `cohort_cascade_events`) never `subscribe()`: the `cohort_stream_events`
//! group's rebalance is the single source of partition ownership, and the rebalance worker mirrors
//! every Assign/Revoke onto them through [`PartitionMirror`] — `incremental_assign` at
//! [`Offset::Stored`] and `incremental_unassign`, both unconditional. The topics are co-partitioned,
//! so the events topic's partition numbers index every follower.
//!
//! Why unconditional, including the rapid revoke→assign path: between the sync revoke and the async
//! unassign the followers keep fetching, and the dispatcher's owned-gate drops those messages while
//! their fetch position advances in-session. If a re-acquire skipped re-assignment, a later
//! monotonic-max mark would commit past the dropped window — a permanently lost merge, not lag.
//! Re-assigning at `Offset::Stored` rewinds to the last commit and redelivers the window; the
//! drain/apply source-coords markers absorb the replays.

use std::sync::Arc;

use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::{Offset, TopicPartitionList};
use tracing::warn;

/// Mirror an events-group (un)assignment onto the follower consumers.
/// Trait-based so the rebalance worker is unit-testable; production impl is [`FollowerSet`].
pub trait PartitionMirror: Send + Sync {
    /// Mirror newly-assigned partitions onto every follower.
    fn assign(&self, partitions: &[i32]);
    /// Mirror revoked partitions off every follower.
    fn unassign(&self, partitions: &[i32]);
}

/// One follower consumer and the topic its assignments are built against.
pub struct Follower {
    consumer: Arc<StreamConsumer>,
    topic: String,
}

impl Follower {
    pub fn new(consumer: Arc<StreamConsumer>, topic: String) -> Self {
        Self { consumer, topic }
    }
}

/// Production [`PartitionMirror`]: drives `incremental_assign`/`incremental_unassign` on a set of
/// follower consumers (`person_merge_events`, `cohort_merge_state_transfer`, and — when the gate is
/// on — `cohort_cascade_events`). Errors are warned and skipped: the rebalance worker must keep
/// draining. A missed assign degrades to visible group lag; a missed unassign is practically
/// unreachable (either "partition wasn't assigned" or a fatally-dead consumer).
pub struct FollowerSet {
    followers: Vec<Follower>,
}

impl FollowerSet {
    /// The followers' topics must all be co-partitioned with `cohort_stream_events`.
    pub fn new(followers: impl IntoIterator<Item = Follower>) -> Self {
        Self {
            followers: followers.into_iter().collect(),
        }
    }
}

impl PartitionMirror for FollowerSet {
    fn assign(&self, partitions: &[i32]) {
        for follower in &self.followers {
            let tpl = stored_tpl(&follower.topic, partitions);
            if let Err(err) = follower.consumer.incremental_assign(&tpl) {
                warn!(
                    topic = %follower.topic,
                    ?partitions,
                    error = %err,
                    "follower incremental_assign failed; surfaces as lag on its consumer group",
                );
            }
        }
    }

    fn unassign(&self, partitions: &[i32]) {
        for follower in &self.followers {
            let tpl = bare_tpl(&follower.topic, partitions);
            if let Err(err) = follower.consumer.incremental_unassign(&tpl) {
                warn!(
                    topic = %follower.topic,
                    ?partitions,
                    error = %err,
                    "follower incremental_unassign failed; owned-gate still drops its messages",
                );
            }
        }
    }
}

pub(crate) fn stored_tpl(topic: &str, partitions: &[i32]) -> TopicPartitionList {
    let mut tpl = TopicPartitionList::new();
    for &partition in partitions {
        if let Err(err) = tpl.add_partition_offset(topic, partition, Offset::Stored) {
            warn!(topic, partition, error = %err, "skipping partition in follower assign list");
        }
    }
    tpl
}

pub(crate) fn bare_tpl(topic: &str, partitions: &[i32]) -> TopicPartitionList {
    let mut tpl = TopicPartitionList::new();
    for &partition in partitions {
        tpl.add_partition(topic, partition);
    }
    tpl
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stored_tpl_maps_each_partition_to_offset_stored() {
        let tpl = stored_tpl("person_merge_events", &[3, 7, 0]);

        assert_eq!(tpl.count(), 3);
        let mut partitions = Vec::new();
        for elem in tpl.elements() {
            assert_eq!(elem.topic(), "person_merge_events");
            assert_eq!(elem.offset(), Offset::Stored);
            partitions.push(elem.partition());
        }
        partitions.sort_unstable();
        assert_eq!(partitions, vec![0, 3, 7]);
    }

    #[test]
    fn stored_tpl_for_no_partitions_is_empty() {
        assert_eq!(stored_tpl("cohort_merge_state_transfer", &[]).count(), 0);
    }

    #[test]
    fn bare_tpl_carries_partitions_without_a_real_offset() {
        let tpl = bare_tpl("cohort_merge_state_transfer", &[5]);

        assert_eq!(tpl.count(), 1);
        let elems = tpl.elements();
        assert_eq!(elems[0].topic(), "cohort_merge_state_transfer");
        assert_eq!(elems[0].partition(), 5);
        assert_eq!(elems[0].offset(), Offset::Invalid);
    }
}
