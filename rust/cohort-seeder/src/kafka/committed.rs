//! Reads the seed consumer group's committed offsets — the *liveness* signal for the completion
//! protocol. A run's reconcile control records were produced to the seed topic; the processor has
//! drained them only once the seed group commits past each produced offset. This asks that group,
//! never our own: the consumer is built with the target group id and both auto-commit and
//! auto-offset-store disabled, so querying it can never mutate the processor's durable progress. It
//! never subscribes or consumes. Mirrors `personhog-leader`'s warming offset query exactly.

use std::time::Duration;

use common_kafka::config::KafkaConfig;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};

use crate::domain::{CommittedOffset, SeedGroupCommits, SeedPartition, SeedPartitionCountError};

/// Queries one consumer group's committed offsets for the seed topic's partitions. Cheap to
/// construct and clone: it holds only configuration, building a short-lived consumer per query.
#[derive(Clone)]
pub struct SeedGroupOffsetReader {
    kafka: KafkaConfig,
    group_id: String,
    topic: String,
    partition_count: u32,
    timeout: Duration,
}

impl SeedGroupOffsetReader {
    pub fn new(
        kafka: KafkaConfig,
        group_id: String,
        topic: String,
        partition_count: u32,
        timeout: Duration,
    ) -> Self {
        Self {
            kafka,
            group_id,
            topic,
            partition_count,
            timeout,
        }
    }

    /// Fetch the seed group's committed offset for every seed partition in one OffsetFetch round-trip.
    /// A partition the group has never committed is absent from the result — the domain reads that as
    /// "not yet caught up". The synchronous `committed_offsets` RPC runs on the blocking pool so a slow
    /// broker cannot stall the runtime.
    pub async fn committed(&self) -> Result<SeedGroupCommits, SeedGroupOffsetError> {
        let partitions = SeedPartition::all(self.partition_count)?.collect::<Vec<_>>();
        let kafka = self.kafka.clone();
        let group_id = self.group_id.clone();
        let topic = self.topic.clone();
        let timeout = self.timeout;
        tokio::task::spawn_blocking(move || {
            let consumer =
                make_offset_consumer(&kafka, &group_id).map_err(SeedGroupOffsetError::Consumer)?;
            let mut tpl = TopicPartitionList::new();
            for partition in &partitions {
                tpl.add_partition(&topic, i32::from(partition.as_u16()));
            }
            let committed = consumer
                .committed_offsets(tpl, timeout)
                .map_err(SeedGroupOffsetError::Fetch)?;
            Ok(build_commits(&partitions, &committed, &topic))
        })
        .await
        .map_err(SeedGroupOffsetError::Join)?
    }
}

/// Keep only the partitions the group has a concrete committed offset for. `Invalid`/`Beginning`/
/// `End` sentinels and absent partitions mean no real commit, so they stay out of the map — which the
/// domain reads as lagging.
fn build_commits(
    partitions: &[SeedPartition],
    committed: &TopicPartitionList,
    topic: &str,
) -> SeedGroupCommits {
    let mut commits = SeedGroupCommits::new();
    for partition in partitions {
        if let Some(Offset::Offset(offset)) = committed
            .find_partition(topic, i32::from(partition.as_u16()))
            .map(|entry| entry.offset())
        {
            commits.insert(*partition, CommittedOffset::new(offset));
        }
    }
    commits
}

/// Build the short-lived query consumer. Auto-commit and auto-offset-store are off so instantiating it
/// with the writer's (seed processor's) group id cannot clobber that group's durable offsets.
fn make_offset_consumer(kafka: &KafkaConfig, group_id: &str) -> Result<StreamConsumer, KafkaError> {
    let mut config = ClientConfig::new();
    config
        .set("bootstrap.servers", &kafka.kafka_hosts)
        .set("group.id", group_id)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("auto.offset.reset", "error");
    if kafka.kafka_tls {
        config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    }
    if !kafka.kafka_client_rack.is_empty() {
        config.set("client.rack", &kafka.kafka_client_rack);
    }
    config.create()
}

#[derive(Debug, thiserror::Error)]
pub enum SeedGroupOffsetError {
    #[error("invalid seed partition count")]
    PartitionCount(#[from] SeedPartitionCountError),
    #[error("creating the seed-group offset query consumer")]
    Consumer(#[source] KafkaError),
    #[error("fetching the seed group's committed offsets")]
    Fetch(#[source] KafkaError),
    #[error("joining the committed-offset query task")]
    Join(#[source] tokio::task::JoinError),
}

#[cfg(test)]
mod tests {
    use super::*;

    const TOPIC: &str = "cohort_seed_events";

    #[test]
    fn only_a_concrete_committed_offset_counts_as_progress() {
        let partitions: Vec<SeedPartition> = SeedPartition::all(4).unwrap().collect();
        let mut committed = TopicPartitionList::new();
        committed
            .add_partition_offset(TOPIC, 0, Offset::Offset(42))
            .unwrap();
        committed
            .add_partition_offset(TOPIC, 1, Offset::Invalid)
            .unwrap();
        committed
            .add_partition_offset(TOPIC, 2, Offset::Beginning)
            .unwrap();
        // Partition 3 is absent from the response entirely.

        let commits = build_commits(&partitions, &committed, TOPIC);

        assert_eq!(commits.get(partitions[0]), Some(CommittedOffset::new(42)));
        for partition in &partitions[1..] {
            assert_eq!(
                commits.get(*partition),
                None,
                "a sentinel or missing offset must read as lagging, not as caught up"
            );
        }
    }
}
