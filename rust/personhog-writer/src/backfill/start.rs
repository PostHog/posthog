//! The backfill group starts at the writer group's committed offsets: everything below them is in
//! Postgres, so a later snapshot holds it, and the backfill writers read the rest.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use rdkafka::consumer::{BaseConsumer, CommitMode, Consumer};
use rdkafka::error::KafkaError;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};

const TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Debug, thiserror::Error)]
pub enum StartError {
    #[error("the backfill group must not be the writer group {0}")]
    WriterGroup(String),
    #[error("the backfill group already has commits on partitions {0:?}; it has started")]
    Started(Vec<i32>),
    #[error("the writer group has no commit on partitions {0:?}")]
    WriterMissing(Vec<i32>),
    #[error(transparent)]
    Kafka(#[from] KafkaError),
}

/// A group's committed offsets on the changelog; partitions without a commit are absent.
pub fn committed_offsets(
    base: &ClientConfig,
    group: &str,
    topic: &str,
    partitions: u32,
) -> Result<HashMap<i32, i64>, KafkaError> {
    let consumer: BaseConsumer = base
        .clone()
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .create()?;
    let mut tpl = TopicPartitionList::new();
    for partition in 0..partitions as i32 {
        tpl.add_partition(topic, partition);
    }
    Ok(consumer
        .committed_offsets(tpl, TIMEOUT)?
        .elements()
        .iter()
        .filter_map(|e| match e.offset() {
            Offset::Offset(offset) => Some((e.partition(), offset)),
            _ => None,
        })
        .collect())
}

pub fn missing(offsets: &HashMap<i32, i64>, partitions: u32) -> Vec<i32> {
    (0..partitions as i32)
        .filter(|partition| !offsets.contains_key(partition))
        .collect()
}

/// Commits the writer group's offsets for the backfill group, which must have none yet. Blocking.
pub fn copy_writer_offsets(
    base: &ClientConfig,
    writer_group: &str,
    backfill_group: &str,
    topic: &str,
    partitions: u32,
) -> Result<HashMap<i32, i64>, StartError> {
    if backfill_group == writer_group {
        return Err(StartError::WriterGroup(writer_group.to_string()));
    }
    let started = committed_offsets(base, backfill_group, topic, partitions)?;
    if !started.is_empty() {
        let mut partitions: Vec<i32> = started.into_keys().collect();
        partitions.sort_unstable();
        return Err(StartError::Started(partitions));
    }
    let writer = committed_offsets(base, writer_group, topic, partitions)?;
    let absent = missing(&writer, partitions);
    if !absent.is_empty() {
        return Err(StartError::WriterMissing(absent));
    }
    let consumer: BaseConsumer = base
        .clone()
        .set("group.id", backfill_group)
        .set("enable.auto.commit", "false")
        .create()?;
    let mut tpl = TopicPartitionList::new();
    for (&partition, &offset) in &writer {
        tpl.add_partition_offset(topic, partition, Offset::Offset(offset))?;
    }
    consumer.assign(&tpl)?;
    // The first commits fail until the client finds the group's coordinator.
    let deadline = Instant::now() + TIMEOUT;
    loop {
        match consumer.commit(&tpl, CommitMode::Sync) {
            Ok(()) => return Ok(writer),
            Err(_) if Instant::now() < deadline => {
                consumer.poll(Duration::from_millis(100));
            }
            Err(e) => return Err(e.into()),
        }
    }
}
