//! The Kafka side of the consumer loop, configured as `consumer-v1.ts` configures node-rdkafka:
//! the same defaults, `KAFKA_CONSUMER_*` overrides, offsets stored by the loop and committed by
//! librdkafka's auto commit.

use std::time::Duration;

use async_trait::async_trait;
use ingestion_framework::KafkaMessage;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::message::{BorrowedMessage, Headers, Message};
use rdkafka::{ClientConfig, Offset, TopicPartitionList};

use super::consumer_loop::{BatchSource, OffsetsToStore};

pub fn consumer_client_config(
    group_id: &str,
    overrides: &[(String, String)],
    client_rack: Option<&str>,
    test_env: bool,
) -> ClientConfig {
    let mut config = ClientConfig::new();
    let host = super::kafka_outputs::hostname();
    for (k, v) in [
        ("client.id", host.as_str()),
        ("security.protocol", "plaintext"),
        ("metadata.broker.list", "kafka:9092"),
        ("log_level", "4"),
        ("session.timeout.ms", "30000"),
        ("max.poll.interval.ms", "300000"),
        ("max.partition.fetch.bytes", "1048576"),
        ("fetch.error.backoff.ms", "100"),
        ("fetch.message.max.bytes", "10485760"),
        ("fetch.wait.max.ms", "50"),
        ("queued.min.messages", "100000"),
        ("queued.max.messages.kbytes", "102400"),
        ("metadata.max.age.ms", "30000"),
        ("socket.timeout.ms", "30000"),
        ("enable.partition.eof", "true"),
        // Node sets this in both consumer versions, so a new group starts at the oldest offset.
        ("auto.offset.reset", "earliest"),
    ] {
        config.set(k, v);
    }
    if let Some(rack) = client_rack {
        config.set("client.rack", rack);
    }
    for (k, v) in overrides {
        config.set(k, v);
    }
    config
        .set("group.id", group_id)
        .set(
            "partition.assignment.strategy",
            if test_env {
                "roundrobin"
            } else {
                "cooperative-sticky"
            },
        )
        .set("enable.auto.offset.store", "false")
        .set("enable.auto.commit", "true");
    strip_classic_protocol_config(&mut config);
    config
}

/// `stripClassicProtocolConfig`: librdkafka rejects these classic-protocol keys when
/// `group.protocol=consumer` (KIP-848), so they are removed after every other key is set.
pub fn strip_classic_protocol_config(config: &mut ClientConfig) {
    if config.get("group.protocol") != Some("consumer") {
        return;
    }
    for key in [
        "session.timeout.ms",
        "heartbeat.interval.ms",
        "partition.assignment.strategy",
        "group.protocol.type",
    ] {
        config.remove(key);
    }
}

pub fn to_kafka_message(m: &BorrowedMessage<'_>) -> KafkaMessage {
    let headers = m
        .headers()
        .map(|hs| {
            hs.iter()
                .map(|h| (h.key.to_string(), h.value.map(<[u8]>::to_vec)))
                .collect()
        })
        .unwrap_or_default();
    KafkaMessage {
        topic: m.topic().to_string(),
        partition: m.partition(),
        offset: m.offset(),
        key: m.key().map(<[u8]>::to_vec),
        value: m.payload().map(bytes::Bytes::copy_from_slice),
        headers,
        timestamp: m.timestamp().to_millis(),
    }
}

pub struct KafkaBatchSource {
    consumer: StreamConsumer,
}

impl KafkaBatchSource {
    pub fn new(consumer: StreamConsumer) -> Self {
        Self { consumer }
    }

    pub fn consumer(&self) -> &StreamConsumer {
        &self.consumer
    }
}

/// Reads up to `max` messages, as `consume(max, cb)` does with the default consume timeout.
pub async fn recv_batch(
    consumer: &StreamConsumer,
    max: usize,
    timeout: Duration,
) -> anyhow::Result<Vec<KafkaMessage>> {
    let deadline = tokio::time::Instant::now() + timeout;
    let mut out = Vec::new();
    while out.len() < max {
        match tokio::time::timeout_at(deadline, consumer.recv()).await {
            Err(_) => break,
            Ok(Ok(m)) => out.push(to_kafka_message(&m)),
            Ok(Err(KafkaError::PartitionEOF(_))) => continue,
            Ok(Err(e)) => {
                tracing::warn!(error = %e, "kafka consume error");
                if out.is_empty() {
                    return Err(e.into());
                }
                break;
            }
        }
    }
    Ok(out)
}

#[async_trait]
impl BatchSource for KafkaBatchSource {
    async fn next_batch(
        &mut self,
        max: usize,
        timeout: Duration,
    ) -> anyhow::Result<Vec<KafkaMessage>> {
        recv_batch(&self.consumer, max, timeout).await
    }

    fn store_offsets(&mut self, offsets: &OffsetsToStore) -> anyhow::Result<()> {
        let mut tpl = TopicPartitionList::new();
        for (topic, partition, offset) in offsets {
            tpl.add_partition_offset(topic, *partition, Offset::Offset(*offset))?;
        }
        // A revoked partition rejects the store, which keeps a stale offset off another owner.
        if let Err(error) = self.consumer.store_offsets(&tpl) {
            tracing::warn!(error = %error, "offset store rejected");
        }
        Ok(())
    }

    fn commit(&mut self) -> anyhow::Result<()> {
        match self.consumer.commit_consumer_state(CommitMode::Sync) {
            Ok(())
            | Err(KafkaError::ConsumerCommit(rdkafka::types::RDKafkaErrorCode::NoOffset)) => Ok(()),
            Err(e) => Err(e.into()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(overrides: &[(&str, &str)]) -> ClientConfig {
        let overrides: Vec<(String, String)> = overrides
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        consumer_client_config("g", &overrides, None, false)
    }

    #[test]
    fn consumer_config_matches_node_offset_reset_and_kip848_strip() {
        let classic = config(&[]);
        assert_eq!(classic.get("auto.offset.reset"), Some("earliest"));
        assert_eq!(
            classic.get("partition.assignment.strategy"),
            Some("cooperative-sticky")
        );
        assert_eq!(
            config(&[("auto.offset.reset", "latest")]).get("auto.offset.reset"),
            Some("latest")
        );
        let kip848 = config(&[
            ("group.protocol", "consumer"),
            ("heartbeat.interval.ms", "3000"),
        ]);
        for key in [
            "session.timeout.ms",
            "heartbeat.interval.ms",
            "partition.assignment.strategy",
        ] {
            assert_eq!(kip848.get(key), None, "{key}");
        }
        assert_eq!(kip848.get("group.id"), Some("g"));
    }
}
