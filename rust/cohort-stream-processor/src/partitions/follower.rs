//! Assignment mirroring for the merge-protocol follower consumers (TDD §4.5.1).
//!
//! The two follower consumers (`person_merge_events`, `cohort_merge_state_transfer`) never
//! `subscribe()`: the `cohort_stream_events` group's rebalance is the single source of partition
//! ownership, and the rebalance worker mirrors every Assign/Revoke onto them through
//! [`PartitionMirror`] — `incremental_assign` at [`Offset::Stored`] and `incremental_unassign`,
//! both **unconditional** (D5). The topics are co-partitioned (asserted at startup, D14), so the
//! events topic's partition numbers index all three.
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

/// The rebalance worker's seam onto the follower consumers: mirror an events-group (un)assignment.
/// A trait so the rebalance worker is unit-testable with a recording fake; the production impl is
/// [`MergeFollowers`].
pub trait PartitionMirror: Send + Sync {
    /// Mirror newly-assigned partitions onto every follower, resuming from each group's committed
    /// offset.
    fn assign(&self, partitions: &[i32]);
    /// Mirror revoked partitions off every follower.
    fn unassign(&self, partitions: &[i32]);
}

/// One follower consumer and the topic its assignments are built against.
struct Follower {
    consumer: Arc<StreamConsumer>,
    topic: String,
}

/// The production [`PartitionMirror`]: drives `incremental_assign`/`incremental_unassign` on both
/// follower consumers. Errors are warned and skipped, never panicked or retried — the rebalance
/// worker must keep draining. A missed assign degrades to visible group lag on the follower's
/// consumer group (the owned-gate still drops misdelivered messages unmarked, so Kafka redelivers
/// them to the true owner). A missed unassign is not universally that benign: were it to leave the
/// partition assigned, the next mirrored re-assign would hit the intersecting-partition error,
/// also warn-and-continue, and keep the in-session fetch position — skipping past the gate-dropped
/// window instead of rewinding to the stored offset. That compound path is practically
/// unreachable: every realistic unassign failure is either "partition wasn't assigned" (no fetch
/// position to preserve) or a fatally-dead consumer (whose fetches and commits died with it).
pub struct MergeFollowers {
    merges: Follower,
    transfers: Follower,
}

impl MergeFollowers {
    pub fn new(
        merges_consumer: Arc<StreamConsumer>,
        merges_topic: String,
        transfers_consumer: Arc<StreamConsumer>,
        transfers_topic: String,
    ) -> Self {
        Self {
            merges: Follower {
                consumer: merges_consumer,
                topic: merges_topic,
            },
            transfers: Follower {
                consumer: transfers_consumer,
                topic: transfers_topic,
            },
        }
    }

    fn followers(&self) -> [&Follower; 2] {
        [&self.merges, &self.transfers]
    }
}

impl PartitionMirror for MergeFollowers {
    fn assign(&self, partitions: &[i32]) {
        for follower in self.followers() {
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
        for follower in self.followers() {
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

/// The TPL for a follower `incremental_assign`: every partition at [`Offset::Stored`], so
/// consumption resumes from the group's committed offset — and, when the broker has pruned the
/// `Empty` group's commits, falls back to the hard-coded `auto.offset.reset=earliest` rather than
/// skipping the tail. Pure (no consumer, no I/O) so the mapping is unit-testable.
pub(crate) fn stored_tpl(topic: &str, partitions: &[i32]) -> TopicPartitionList {
    let mut tpl = TopicPartitionList::new();
    for &partition in partitions {
        // `add_partition_offset` only errors on an invalid sentinel; `Stored` is always valid.
        if let Err(err) = tpl.add_partition_offset(topic, partition, Offset::Stored) {
            warn!(topic, partition, error = %err, "skipping partition in follower assign list");
        }
    }
    tpl
}

/// The TPL for a follower `incremental_unassign`: offsets are irrelevant on removal, so partitions
/// carry the default sentinel.
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
