use std::collections::HashMap;

use rdkafka::consumer::{CommitMode, Consumer, ConsumerContext, StreamConsumer};
use rdkafka::{ClientConfig, TopicPartitionList};

/// Build a StreamConsumer subscribed to the given topic.
pub fn build_consumer(
    config: &ClientConfig,
    topic: &str,
) -> Result<StreamConsumer, rdkafka::error::KafkaError> {
    let consumer: StreamConsumer = config.create()?;
    consumer.subscribe(&[topic])?;
    Ok(consumer)
}

/// Commit the max offset for each partition.
pub fn commit_offsets<C: ConsumerContext>(
    consumer: &StreamConsumer<C>,
    topic: &str,
    offsets: &HashMap<i32, i64>,
) -> Result<(), rdkafka::error::KafkaError> {
    if offsets.is_empty() {
        return Ok(());
    }

    let mut tpl = TopicPartitionList::new();
    for (partition, offset) in offsets {
        // Kafka convention: committed offset = next offset to read
        tpl.add_partition_offset(topic, *partition, rdkafka::Offset::Offset(offset + 1))?;
    }

    consumer.commit(&tpl, CommitMode::Async)?;
    Ok(())
}
