//! Whether a consumer group has consumed a topic's partitions to their end.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use rdkafka::consumer::{BaseConsumer, Consumer, ConsumerContext};
use rdkafka::error::KafkaError;
use rdkafka::message::Message;
use rdkafka::types::RDKafkaErrorCode;
use rdkafka::{ClientConfig, ClientContext, Offset, TopicPartitionList};

/// A consumer context that does not log end-of-partition, which the probe polls for.
pub struct QuietEof;

impl ClientContext for QuietEof {
    fn error(&self, error: KafkaError, reason: &str) {
        if !matches!(
            error,
            KafkaError::PartitionEOF(_) | KafkaError::Global(RDKafkaErrorCode::PartitionEOF)
        ) {
            tracing::error!(%error, reason, "librdkafka");
        }
    }
}

impl ConsumerContext for QuietEof {}

fn client_config(base: &ClientConfig, group_id: &str) -> ClientConfig {
    let mut cfg = base.clone();
    cfg.set("group.id", group_id)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("auto.offset.reset", "earliest")
        .set("isolation.level", "read_committed")
        .set("enable.partition.eof", "true");
    cfg
}

/// Whether `group` has read each partition to its end; transaction markers never count.
/// A timeout or a missing topic is an error. Blocking.
pub fn partitions_drained(
    base: &ClientConfig,
    group: &str,
    topic: &str,
    timeout: Duration,
) -> Result<HashMap<u32, bool>, KafkaError> {
    let group_consumer: BaseConsumer = client_config(base, group).create()?;
    let metadata = group_consumer.fetch_metadata(Some(topic), timeout)?;
    let partitions: Vec<i32> = metadata
        .topics()
        .iter()
        .find(|t| t.name() == topic)
        .map(|t| t.partitions().iter().map(|p| p.id()).collect())
        .unwrap_or_default();
    if partitions.is_empty() {
        return Err(KafkaError::MetadataFetch(
            RDKafkaErrorCode::UnknownTopicOrPartition,
        ));
    }
    let mut tpl = TopicPartitionList::new();
    for partition in &partitions {
        tpl.add_partition(topic, *partition);
    }
    let committed = group_consumer.committed_offsets(tpl, timeout)?;

    // The probe reads under its own group so it never moves the group's offsets.
    let probe_group = format!("{group}-drain-probe");
    let probe: BaseConsumer<QuietEof> =
        client_config(base, &probe_group).create_with_context(QuietEof)?;
    let mut assignment = TopicPartitionList::new();
    for partition in &partitions {
        let start = match committed
            .find_partition(topic, *partition)
            .map(|e| e.offset())
        {
            Some(Offset::Offset(offset)) => Offset::Offset(offset),
            _ => Offset::Beginning,
        };
        assignment.add_partition_offset(topic, *partition, start)?;
    }
    probe.assign(&assignment)?;

    let mut resolved: HashMap<u32, bool> = HashMap::new();
    let deadline = Instant::now() + timeout;
    while resolved.len() < partitions.len() {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            break;
        }
        let settled = match probe.poll(remaining) {
            None => continue,
            Some(Ok(message)) => {
                resolved.insert(message.partition() as u32, false);
                message.partition()
            }
            Some(Err(KafkaError::PartitionEOF(partition))) => {
                resolved.entry(partition as u32).or_insert(true);
                partition
            }
            Some(Err(e)) => return Err(e),
        };
        // One answer per partition is all the probe needs; the rest of its records stay unread.
        let mut done = TopicPartitionList::new();
        done.add_partition(topic, settled);
        probe.pause(&done)?;
    }
    if resolved.len() < partitions.len() {
        return Err(KafkaError::MessageConsumption(
            RDKafkaErrorCode::OperationTimedOut,
        ));
    }
    Ok(resolved)
}

pub fn group_drained(
    base: &ClientConfig,
    group: &str,
    topic: &str,
    timeout: Duration,
) -> Result<bool, KafkaError> {
    let drained = partitions_drained(base, group, topic, timeout)?;
    Ok(drained.values().all(|ok| *ok))
}

#[cfg(test)]
mod tests {
    use rdkafka::consumer::CommitMode;
    use rdkafka::producer::FutureRecord;

    use super::*;

    const TOPIC: &str = "probe-topic";
    const GROUP: &str = "probe-writer";

    fn commit(bootstrap: &str, partition: i32, offset: i64) {
        let consumer: BaseConsumer = ClientConfig::new()
            .set("bootstrap.servers", bootstrap)
            .set("group.id", GROUP)
            .set("enable.auto.commit", "false")
            .create()
            .expect("group consumer");
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition_offset(TOPIC, partition, Offset::Offset(offset))
            .expect("tpl");
        consumer.assign(&tpl).expect("assign");
        consumer.commit(&tpl, CommitMode::Sync).expect("commit");
    }

    #[tokio::test]
    async fn a_partition_is_drained_only_once_the_group_committed_its_end() {
        let (cluster, producer) = crate::test::create_mock_kafka().await;
        cluster.create_topic(TOPIC, 2, 1).expect("create topic");
        for _ in 0..3 {
            producer
                .send_result(FutureRecord::<(), _>::to(TOPIC).partition(0).payload("x"))
                .expect("enqueue")
                .await
                .expect("produce canceled")
                .expect("produce failed");
        }
        let bootstrap = cluster.bootstrap_servers();
        let mut base = ClientConfig::new();
        base.set("bootstrap.servers", &bootstrap);
        let timeout = Duration::from_secs(10);
        let drained = || {
            let base = base.clone();
            move || partitions_drained(&base, GROUP, TOPIC, timeout).expect("probe")
        };

        let none = tokio::task::spawn_blocking(drained()).await.unwrap();
        assert_eq!(none, HashMap::from([(0, false), (1, true)]));

        commit(&bootstrap, 0, 1);
        let partial = tokio::task::spawn_blocking(drained()).await.unwrap();
        assert!(!partial[&0]);

        commit(&bootstrap, 0, 3);
        let base_for_group = base.clone();
        let all = tokio::task::spawn_blocking(move || {
            group_drained(&base_for_group, GROUP, TOPIC, timeout).expect("probe")
        })
        .await
        .unwrap();
        assert!(all);
    }
}
