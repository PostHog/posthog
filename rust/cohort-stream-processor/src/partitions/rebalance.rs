//! The events consumer's [`ConsumerContext`]. Every consumer assigns itself the partitions this pod
//! owns (see [`super::ownership`]) and never joins its group, so two of its callbacks matter:
//!
//! - A rebalance callback means this consumer subscribed after all, which static ownership rules
//!   out. It is a tripwire for a code change, not for another client.
//! - An async offset commit the broker refuses. A member-less commit is refused while the group
//!   has a live member: the static member a subscribing build left behind, until its session
//!   expires, or any client that subscribes to the group. A refused commit leaves the offset where
//!   it was, so the next commit retries it.

use metrics::counter;
use rdkafka::consumer::{BaseConsumer, ConsumerContext, Rebalance};
use rdkafka::error::KafkaResult;
use rdkafka::{ClientContext, TopicPartitionList};
use tracing::{error, warn};

use crate::observability::metrics::{COHORT_STREAM_OFFSET_COMMIT_ERRORS, REBALANCES_TOTAL};

pub struct CohortConsumerContext;

impl ClientContext for CohortConsumerContext {}

impl ConsumerContext for CohortConsumerContext {
    fn pre_rebalance(&self, _base: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        let event_type = match rebalance {
            Rebalance::Assign(_) => "assign",
            Rebalance::Revoke(_) => "revoke",
            Rebalance::Error(_) => "error",
        };
        counter!(REBALANCES_TOTAL, "event_type" => event_type).increment(1);
        error!(
            ?rebalance,
            "the events consumer rebalanced, which static partition ownership rules out",
        );
    }

    fn commit_callback(&self, result: KafkaResult<()>, _offsets: &TopicPartitionList) {
        if let Err(err) = result {
            counter!(COHORT_STREAM_OFFSET_COMMIT_ERRORS).increment(1);
            warn!(
                error = %err,
                "the broker refused an events offset commit; the next commit retries it",
            );
        }
    }
}
