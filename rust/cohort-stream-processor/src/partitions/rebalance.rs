//! The events consumer's [`ConsumerContext`]. Every consumer assigns itself the partitions this pod
//! owns (see [`super::ownership`]) and never joins its group, so a rebalance callback means this
//! consumer subscribed after all, which static ownership rules out. It is a tripwire for a code
//! change, not for another client.

use metrics::counter;
use rdkafka::consumer::{BaseConsumer, ConsumerContext, Rebalance};
use rdkafka::ClientContext;
use tracing::error;

use crate::observability::metrics::REBALANCES_TOTAL;

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
}
