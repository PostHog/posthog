use std::collections::HashMap;
use std::time::Duration;

use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::KafkaContext;
use metrics::counter;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::BorrowedMessage;
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use rdkafka::{ClientConfig, TopicPartitionList};
use tracing::warn;

use crate::store::IngestionWarning;

// ── Consumer ────────────────────────────────────────────────────

/// Wraps a Kafka StreamConsumer with its topic, providing a clean
/// interface for receiving messages and committing offsets.
pub struct PersonConsumer {
    consumer: StreamConsumer,
    topic: String,
}

impl PersonConsumer {
    pub fn from_config(
        kafka: &KafkaConfig,
        consumer_group: &str,
        offset_reset: &str,
        topic: String,
    ) -> Result<Self, rdkafka::error::KafkaError> {
        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &kafka.kafka_hosts)
            .set("group.id", consumer_group)
            .set("auto.offset.reset", offset_reset)
            .set("enable.auto.commit", "false")
            .set("enable.auto.offset.store", "false")
            // Cooperative-sticky: during scale events, only partitions that need
            // to move are revoked. Non-moving partitions keep being consumed.
            .set("partition.assignment.strategy", "cooperative-sticky");

        // Static group membership: the broker holds partition assignments for
        // session.timeout.ms after a pod disappears, so quick restarts
        // (deploys, OOM kills) don't trigger a rebalance at all.
        // Requires stable pod names (StatefulSet) so the same ID reconnects.
        if !kafka.kafka_client_id.is_empty() {
            client_config
                .set("client.id", &kafka.kafka_client_id)
                .set("group.instance.id", &kafka.kafka_client_id);
        }

        if kafka.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }

        if !kafka.kafka_client_rack.is_empty() {
            client_config.set("client.rack", &kafka.kafka_client_rack);
        }

        let consumer: StreamConsumer = client_config.create()?;
        consumer.subscribe(&[&topic])?;
        Ok(Self { consumer, topic })
    }

    /// Create from a raw `ClientConfig`. Useful in tests where you control
    /// the config directly (e.g., mock clusters).
    pub fn new(config: &ClientConfig, topic: String) -> Result<Self, rdkafka::error::KafkaError> {
        let consumer: StreamConsumer = config.create()?;
        consumer.subscribe(&[&topic])?;
        Ok(Self { consumer, topic })
    }

    pub async fn recv(&self) -> Result<BorrowedMessage<'_>, rdkafka::error::KafkaError> {
        self.consumer.recv().await
    }

    pub fn commit_offsets(
        &self,
        offsets: &HashMap<i32, i64>,
    ) -> Result<(), rdkafka::error::KafkaError> {
        if offsets.is_empty() {
            return Ok(());
        }

        let mut tpl = TopicPartitionList::new();
        for (partition, offset) in offsets {
            tpl.add_partition_offset(&self.topic, *partition, rdkafka::Offset::Offset(offset + 1))?;
        }

        self.consumer.commit(&tpl, CommitMode::Async)?;
        Ok(())
    }

    pub fn topic(&self) -> &str {
        &self.topic
    }
}

// ── Warnings producer ───────────────────────────────────────────

/// Produces ingestion warnings to Kafka so users see property size
/// violations in-product.
pub struct WarningsProducer {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl WarningsProducer {
    pub fn new(producer: FutureProducer<KafkaContext>, topic: String) -> Self {
        Self { producer, topic }
    }

    /// Enqueue an ingestion warning into rdkafka's internal buffer.
    /// Fire-and-forget: rdkafka handles retries and delivery in the
    /// background. Call `flush()` on shutdown to drain pending messages.
    pub fn emit(&self, warning: &IngestionWarning) {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();

        let details = serde_json::json!({
            "personId": warning.person_id.to_string(),
            "teamId": warning.team_id,
            "message": warning.message,
        });

        let payload = serde_json::json!({
            "team_id": warning.team_id,
            "type": "person_properties_size_violation",
            "source": "personhog-writer",
            "details": details.to_string(),
            "timestamp": now.to_string(),
        });

        let payload_bytes = serde_json::to_vec(&payload).unwrap_or_default();
        let key = warning.team_id.to_string();
        let record = FutureRecord::to(&self.topic)
            .payload(&payload_bytes)
            .key(&key);

        match self.producer.send_result(record) {
            Ok(_future) => {
                counter!("personhog_writer_ingestion_warnings_emitted_total").increment(1);
            }
            Err((e, _)) => {
                warn!(error = %e, "failed to enqueue ingestion warning");
            }
        }
    }

    /// Flush any buffered messages, waiting up to the given timeout for
    /// delivery. Called during graceful shutdown.
    pub fn flush(&self, timeout: Duration) {
        self.producer.flush(timeout).ok();
    }
}
