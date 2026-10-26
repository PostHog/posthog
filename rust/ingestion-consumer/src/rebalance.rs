//! The consumer's rdkafka context: rebalance callbacks into hooks, plus rebalance counters and client statistics.

use std::sync::OnceLock;

use common_kafka_consumer::TopicPartition;
use metrics::counter;
use rdkafka::consumer::{BaseConsumer, Consumer, ConsumerContext, Rebalance};
use rdkafka::error::KafkaResult;
use rdkafka::{ClientContext, Statistics, TopicPartitionList};
use tracing::{error, info, warn};

pub type PartitionHook = Box<dyn Fn(&[TopicPartition]) + Send + Sync>;

/// Hooks run inside the callback, before the next poll delivers the new assignment.
#[derive(Default)]
pub struct RebalanceContext {
    on_revoke: OnceLock<PartitionHook>,
    on_assign: OnceLock<PartitionHook>,
}

impl RebalanceContext {
    pub fn new() -> Self {
        Self::default()
    }

    /// Settable after construction because the rdkafka consumer only hands out `&self`.
    pub fn set_on_revoke(&self, hook: PartitionHook) {
        let _ = self.on_revoke.set(hook);
    }

    pub fn set_on_assign(&self, hook: PartitionHook) {
        let _ = self.on_assign.set(hook);
    }
}

fn topic_partitions(tpl: &TopicPartitionList) -> Vec<TopicPartition> {
    let mut partitions: Vec<TopicPartition> = tpl
        .elements()
        .iter()
        .map(|element| TopicPartition::new(element.topic(), element.partition()))
        .collect();
    partitions.sort_unstable_by(|a, b| (&a.topic, a.partition).cmp(&(&b.topic, b.partition)));
    partitions
}

/// librdkafka's pause and resume return success when they cannot change a
/// partition. They set the error on that partition's list element.
pub(crate) fn partition_error(tpl: &TopicPartitionList) -> KafkaResult<()> {
    tpl.elements()
        .iter()
        .try_for_each(|element| element.error())
}

fn partition_names(partitions: &[TopicPartition]) -> Vec<String> {
    partitions
        .iter()
        .map(|tp| format!("{}:{}", tp.topic, tp.partition))
        .collect()
}

impl ClientContext for RebalanceContext {
    /// Fired on a librdkafka thread every `statistics.interval.ms`; disabled
    /// when that is 0.
    fn stats(&self, stats: Statistics) {
        crate::kafka_stats::export(&stats);
    }
}

impl ConsumerContext for RebalanceContext {
    fn pre_rebalance(&self, _consumer: &BaseConsumer<Self>, rebalance: &Rebalance) {
        match rebalance {
            Rebalance::Revoke(tpl) => {
                counter!("ingestion_consumer_rebalances_total", "event" => "revoke").increment(1);
                let partitions = topic_partitions(tpl);
                info!(
                    partitions = partitions.len(),
                    topic_partitions = ?partition_names(&partitions),
                    "Rebalance: partitions revoked"
                );
                if let Some(hook) = self.on_revoke.get() {
                    hook(&partitions);
                }
            }
            Rebalance::Assign(_) => {}
            Rebalance::Error(err) => {
                counter!("ingestion_consumer_rebalances_total", "event" => "error").increment(1);
                warn!(error = %err, "Rebalance error");
            }
        }
    }

    fn post_rebalance(&self, consumer: &BaseConsumer<Self>, rebalance: &Rebalance) {
        if let Rebalance::Assign(tpl) = rebalance {
            counter!("ingestion_consumer_rebalances_total", "event" => "assign").increment(1);
            let partitions = topic_partitions(tpl);
            info!(
                partitions = partitions.len(),
                topic_partitions = ?partition_names(&partitions),
                "Rebalance: partitions assigned"
            );
            // librdkafka keeps a partition's pause across a revoke and a
            // reassignment, and the assign hook forgets the budget that paused it.
            if let Err(err) = consumer.resume(tpl).and_then(|()| partition_error(tpl)) {
                error!(error = %err, "Could not resume the assigned partitions");
            }
            if let Some(hook) = self.on_assign.get() {
                hook(&partitions);
            }
        }
    }

    // NOTE: `ConsumerContext::commit_callback` is deliberately not implemented.
    // librdkafka only propagates a commit result to the application when a
    // conf-level `offset_commit_cb` is registered (rust-rdkafka never does) or
    // when the commit is synchronous (a replyq is attached); manual async
    // commits silently drop their result (`rd_kafka_cgrp_propagate_commit_result`).
}

#[cfg(test)]
mod tests {
    use std::sync::{Arc, Mutex};

    use rdkafka::config::ClientConfig;
    use rdkafka::consumer::Consumer;

    use super::*;

    fn recording(seen: &Arc<Mutex<Vec<TopicPartition>>>) -> PartitionHook {
        let seen = Arc::clone(seen);
        Box::new(move |partitions| seen.lock().unwrap().extend_from_slice(partitions))
    }

    #[test]
    fn partitions_sort_by_topic_then_partition_number() {
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition("overflow", 2);
        tpl.add_partition("events", 10);
        tpl.add_partition("events", 9);

        assert_eq!(
            partition_names(&topic_partitions(&tpl)),
            vec!["events:9", "events:10", "overflow:2"]
        );
    }

    #[test]
    fn each_callback_reaches_its_hook_with_the_partitions() {
        let revoked = Arc::new(Mutex::new(Vec::new()));
        let assigned = Arc::new(Mutex::new(Vec::new()));
        let context = RebalanceContext::new();
        context.set_on_revoke(recording(&revoked));
        context.set_on_assign(recording(&assigned));
        let consumer: BaseConsumer<RebalanceContext> = ClientConfig::new()
            .set("bootstrap.servers", "127.0.0.1:1")
            .set("group.id", "test")
            .create_with_context(context)
            .expect("a client needs no broker to be built");
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition("events", 1);
        tpl.add_partition("events", 0);

        consumer
            .context()
            .pre_rebalance(&consumer, &Rebalance::Revoke(&tpl));
        consumer
            .context()
            .post_rebalance(&consumer, &Rebalance::Assign(&tpl));

        let expected = vec![
            TopicPartition::new("events", 0),
            TopicPartition::new("events", 1),
        ];
        assert_eq!(*revoked.lock().unwrap(), expected);
        assert_eq!(*assigned.lock().unwrap(), expected);
    }

    #[test]
    fn pausing_an_unassigned_partition_is_an_error() {
        let consumer: BaseConsumer = ClientConfig::new()
            .set("bootstrap.servers", "127.0.0.1:1")
            .set("group.id", "test")
            .create()
            .expect("a client needs no broker to be built");
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition("events", 0);

        assert!(consumer.pause(&tpl).is_ok());
        assert!(partition_error(&tpl).is_err());
    }
}
