//! Per-partition Kafka pause/resume for the events consumer, so a full worker channel surfaces as lag
//! on that partition alone. Trait-based for broker-free tests; the prod impl [`ConsumerPauser`] warns
//! and skips on error — a missed pause only grows the holdover, a missed resume only defers a drain.

use std::sync::Arc;

use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::TopicPartitionList;
use tracing::warn;

use crate::partitions::rebalance::CohortConsumerContext;

/// Pause/resume Kafka fetching for specific partitions of the events topic.
pub trait PartitionPauser: Send + Sync {
    fn pause(&self, partitions: &[i32]);
    fn resume(&self, partitions: &[i32]);
}

/// Production [`PartitionPauser`]: drives `pause`/`resume` on the events `StreamConsumer`.
pub struct ConsumerPauser {
    consumer: Arc<StreamConsumer<CohortConsumerContext>>,
    topic: String,
}

impl ConsumerPauser {
    pub fn new(consumer: Arc<StreamConsumer<CohortConsumerContext>>, topic: String) -> Self {
        Self { consumer, topic }
    }

    fn tpl(&self, partitions: &[i32]) -> TopicPartitionList {
        let mut tpl = TopicPartitionList::new();
        for &partition in partitions {
            tpl.add_partition(&self.topic, partition);
        }
        tpl
    }
}

impl PartitionPauser for ConsumerPauser {
    fn pause(&self, partitions: &[i32]) {
        if partitions.is_empty() {
            return;
        }
        if let Err(err) = self.consumer.pause(&self.tpl(partitions)) {
            warn!(
                topic = %self.topic,
                ?partitions,
                error = %err,
                "failed to pause partitions; the holdover grows until the next attempt",
            );
        }
    }

    fn resume(&self, partitions: &[i32]) {
        if partitions.is_empty() {
            return;
        }
        if let Err(err) = self.consumer.resume(&self.tpl(partitions)) {
            warn!(
                topic = %self.topic,
                ?partitions,
                error = %err,
                "failed to resume partitions; surfaces as lag until the next attempt",
            );
        }
    }
}
