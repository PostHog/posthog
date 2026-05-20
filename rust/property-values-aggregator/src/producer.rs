use std::time::Duration;

use anyhow::{anyhow, Result};
use common_kafka::kafka_producer::KafkaContext;
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};

use crate::types::{OutputMessage, TupleKey};

/// Wrapper around a Kafka producer that serializes accumulated tuple counts
/// to JSON and produces them to the output topic. Fire-and-forget per record;
/// `flush` blocks until rdkafka's in-flight queue is empty.
pub struct AggregatedProducer {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl AggregatedProducer {
    pub fn new(producer: FutureProducer<KafkaContext>, topic: String) -> Self {
        Self { producer, topic }
    }

    /// Enqueue one aggregated tuple into rdkafka's internal buffer.
    /// rdkafka handles batching, retries, and delivery in the background.
    pub fn emit(&self, tuple: &TupleKey, count: u64) -> Result<()> {
        let payload = OutputMessage {
            team_id: tuple.team_id,
            property_type: tuple.property_type.as_str(),
            property_key: &tuple.property_key,
            property_value: &tuple.property_value,
            property_count: count,
        };

        let payload_bytes = serde_json::to_vec(&payload)?;
        let key = tuple.team_id.to_string();
        let record = FutureRecord::to(&self.topic)
            .payload(&payload_bytes)
            .key(&key);

        self.producer
            .send_result(record)
            .map_err(|(e, _)| anyhow!("failed to enqueue record: {e}"))?;
        Ok(())
    }

    /// Block until all in-flight records have been acknowledged by the broker.
    /// Called after each flush window so we know the output is durable before
    /// committing input offsets.
    pub async fn flush(&self, timeout: Duration) -> Result<()> {
        let producer = self.producer.clone();
        // rdkafka's flush is sync; run it on a blocking task so we don't stall the runtime.
        tokio::task::spawn_blocking(move || producer.flush(timeout))
            .await
            .map_err(|e| anyhow!("flush join error: {e}"))?
            .map_err(|e| anyhow!("kafka flush error: {e}"))?;
        Ok(())
    }
}
