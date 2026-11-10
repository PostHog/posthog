//! The follower consumers: `person_merge_events`, `cohort_merge_state_transfer`, and, when their
//! gates are on, `cohort_cascade_events` and `cohort_stream_seed_events`. They never subscribe.
//! Each is assigned the partitions this pod owns, like the events consumer, so the pod owns
//! partition N on every input at once. The topics are co-partitioned, so the events topic's
//! partition numbers index every follower.

use std::sync::Arc;

use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::error::KafkaResult;

use crate::partitions::ClaimedSplit;

/// One follower consumer and the topic its assignment is built against.
pub struct Follower {
    consumer: Arc<StreamConsumer>,
    topic: String,
}

impl Follower {
    pub fn new(consumer: Arc<StreamConsumer>, topic: String) -> Self {
        Self { consumer, topic }
    }
}

/// The follower consumers of one pod. Their topics must all be co-partitioned with
/// `cohort_stream_events`.
pub struct FollowerSet {
    followers: Vec<Follower>,
}

impl FollowerSet {
    pub fn new(followers: impl IntoIterator<Item = Follower>) -> Self {
        Self {
            followers: followers.into_iter().collect(),
        }
    }

    /// Assigns every follower the partitions `claimed` owns, each at its group's committed
    /// offset. A follower that fails would never consume its topic, so the first failure stops.
    pub fn assign(&self, claimed: &ClaimedSplit) -> KafkaResult<()> {
        let ownership = claimed.ownership();
        for follower in &self.followers {
            follower
                .consumer
                .assign(&ownership.assignment(&follower.topic)?)?;
        }
        Ok(())
    }
}
