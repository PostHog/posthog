use std::collections::HashMap;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::client::DefaultClientContext;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::error::KafkaError;
use rdkafka::message::Message;
use rdkafka::types::RDKafkaErrorCode;
use rdkafka::{Offset, TopicPartitionList};

pub fn base_config(kafka_hosts: &str) -> ClientConfig {
    let mut cfg = ClientConfig::new();
    cfg.set("bootstrap.servers", kafka_hosts);
    cfg
}

/// Whether `group` has committed on any partition of `topic`.
pub async fn group_has_committed_offsets(
    kafka_hosts: &str,
    group: &str,
    topic: &str,
) -> Result<bool> {
    let (base, group, topic) = (
        base_config(kafka_hosts),
        group.to_string(),
        topic.to_string(),
    );
    tokio::task::spawn_blocking(move || -> Result<bool> {
        let timeout = Duration::from_secs(5);
        let consumer: BaseConsumer = base
            .clone()
            .set("group.id", &group)
            .set("enable.auto.commit", "false")
            .create()?;
        let metadata = consumer.fetch_metadata(Some(&topic), timeout)?;
        let partitions = metadata
            .topics()
            .iter()
            .find(|t| t.name() == topic)
            .map_or(0, |t| t.partitions().len());
        let mut tpl = TopicPartitionList::new();
        for partition in 0..partitions {
            tpl.add_partition(&topic, partition as i32);
        }
        let committed = consumer.committed_offsets(tpl, timeout)?;
        Ok(committed
            .elements()
            .iter()
            .any(|e| matches!(e.offset(), Offset::Offset(_))))
    })
    .await
    .context("offsets task panicked")?
    .context("fetching committed offsets")
}

fn admin_client(kafka_hosts: &str) -> Result<AdminClient<DefaultClientContext>> {
    ClientConfig::new()
        .set("bootstrap.servers", kafka_hosts)
        .create()
        .context("creating kafka admin client")
}

/// Create a per-run topic with exactly `partitions` partitions. For the
/// changelog the count must match `config/changelog` in etcd — a mismatch
/// is a silent mis-shard — so an existing topic with a different count is
/// an error rather than something to adopt.
pub async fn create_topic(kafka_hosts: &str, topic: &str, partitions: u32) -> Result<()> {
    let admin = admin_client(kafka_hosts)?;
    let options = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));

    let new_topic = NewTopic::new(topic, partitions as i32, TopicReplication::Fixed(1));
    let results = admin
        .create_topics([&new_topic], &options)
        .await
        .context("creating topic")?;

    for result in results {
        match result {
            Ok(_) => {}
            Err((name, RDKafkaErrorCode::TopicAlreadyExists)) => {
                bail!(
                    "topic {name} already exists — a previous run may not have torn down; \
                     delete it or pass a different --topic"
                );
            }
            Err((name, code)) => bail!("failed to create topic {name}: {code}"),
        }
    }

    tracing::info!(topic, partitions, "created topic");
    Ok(())
}

/// Create every topic or none: a topic left behind by a failed bring-up
/// counts against the broker's partition budget until someone notices.
pub async fn create_topics(kafka_hosts: &str, topics: &[(&str, u32)]) -> Result<()> {
    for (index, (topic, partitions)) in topics.iter().enumerate() {
        if let Err(e) = create_topic(kafka_hosts, topic, *partitions).await {
            for (created, _) in &topics[..index] {
                if let Err(cleanup) = delete_topic(kafka_hosts, created).await {
                    tracing::warn!(topic = created, error = %cleanup, "failed to clean up topic");
                }
            }
            return Err(e);
        }
    }
    Ok(())
}

pub async fn delete_topic(kafka_hosts: &str, topic: &str) -> Result<()> {
    let admin = admin_client(kafka_hosts)?;
    let options = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));

    let results = admin
        .delete_topics(&[topic], &options)
        .await
        .context("deleting topic")?;

    for result in results {
        match result {
            Ok(_) | Err((_, RDKafkaErrorCode::UnknownTopicOrPartition)) => {}
            Err((name, code)) => bail!("failed to delete topic {name}: {code}"),
        }
    }

    tracing::info!(topic, "deleted topic");
    Ok(())
}

pub struct KafkaRecord {
    pub key: Option<Vec<u8>>,
    pub payload: Vec<u8>,
}

/// Every record on `topic`, from the beginning of each partition up to the
/// high watermark captured when the read starts, so a producer still
/// writing cannot make the read run on. Nothing is committed, so no
/// consumer group state is left behind. The deadline only bounds a
/// partition that stops delivering.
pub async fn read_to_end(
    kafka_hosts: &str,
    topic: &str,
    deadline: Duration,
) -> Result<Vec<KafkaRecord>> {
    let kafka_hosts = kafka_hosts.to_string();
    let topic = topic.to_string();
    tokio::task::spawn_blocking(move || read_to_end_blocking(&kafka_hosts, &topic, deadline))
        .await
        .context("kafka read task panicked")?
}

fn read_to_end_blocking(
    kafka_hosts: &str,
    topic: &str,
    deadline: Duration,
) -> Result<Vec<KafkaRecord>> {
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", kafka_hosts)
        .set("group.id", "personhog-test-harness-reader")
        .set("enable.auto.commit", "false")
        .set("enable.partition.eof", "true")
        .set("auto.offset.reset", "earliest")
        .create()
        .context("creating kafka reader")?;

    let metadata = consumer
        .fetch_metadata(Some(topic), Duration::from_secs(10))
        .context("fetching topic metadata")?;
    let partitions: Vec<i32> = metadata
        .topics()
        .iter()
        .find(|t| t.name() == topic)
        .map(|t| t.partitions().iter().map(|p| p.id()).collect())
        .with_context(|| format!("topic {topic} has no metadata"))?;

    let mut remaining: HashMap<i32, i64> = HashMap::new();
    let mut assignment = TopicPartitionList::new();
    for partition in partitions {
        let (low, high) = consumer
            .fetch_watermarks(topic, partition, Duration::from_secs(10))
            .with_context(|| format!("fetching watermarks of {topic}/{partition}"))?;
        if high > low {
            remaining.insert(partition, high);
            assignment.add_partition_offset(topic, partition, Offset::Beginning)?;
        }
    }
    if remaining.is_empty() {
        return Ok(Vec::new());
    }
    consumer
        .assign(&assignment)
        .context("assigning partitions")?;

    let start = Instant::now();
    let mut records = Vec::new();
    while !remaining.is_empty() {
        if start.elapsed() > deadline {
            bail!(
                "reading {topic} did not reach the high watermark within {deadline:?}; \
                 partitions left: {:?}",
                remaining
            );
        }
        match consumer.poll(Duration::from_millis(200)) {
            None => {}
            Some(Err(KafkaError::PartitionEOF(partition))) => {
                remaining.remove(&partition);
            }
            Some(Err(e)) => bail!("reading {topic}: {e}"),
            Some(Ok(message)) => {
                let partition = message.partition();
                let Some(high) = remaining.get(&partition).copied() else {
                    continue;
                };
                if message.offset() >= high {
                    remaining.remove(&partition);
                    continue;
                }
                records.push(KafkaRecord {
                    key: message.key().map(<[u8]>::to_vec),
                    payload: message.payload().unwrap_or_default().to_vec(),
                });
                if message.offset() + 1 >= high {
                    remaining.remove(&partition);
                }
            }
        }
    }
    Ok(records)
}
