use std::hash::Hasher;
use std::time::Duration;

use async_trait::async_trait;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{
    create_kafka_producer, send_keyed_payloads_to_kafka_with_encoding, EnvelopeEncoding,
    KafkaContext, KafkaProduceError,
};
use rdkafka::error::KafkaError;
use rdkafka::producer::FutureProducer;
use siphasher::sip::SipHasher13;
use thiserror::Error;
use tracing::warn;

use crate::types::{PropertyType, TupleKey};
use crate::wire;

#[derive(serde::Serialize)]
pub(crate) struct Outgoing<'a> {
    pub team_id: i64,
    pub property_type: PropertyType,
    pub property_key: &'a str,
    pub property_value: &'a str,
    pub property_count: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum WireFormat {
    #[default]
    Json,
    Binary,
}

impl std::str::FromStr for WireFormat {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_ref() {
            "json" => Ok(WireFormat::Json),
            "binary" => Ok(WireFormat::Binary),
            _ => Err(format!("Unknown WireFormat: {s}")),
        }
    }
}

#[derive(Debug, Error)]
pub enum ProduceError {
    #[error("kafka produce timed out after {0:?}")]
    Timeout(Duration),
    #[error("{failed}/{total} records failed delivery")]
    PartialFailure { failed: usize, total: usize },
}

/// Produce the aggregated tuples to the output topic. At-least-once: each
/// produce stands on its own and the caller stores the input consumer offsets
/// only after this returns Ok. On failure the caller does not advance the
/// stored offsets, so the next pod resumes from before these inputs and
/// re-produces them; duplicates are absorbed by the storage table's existing
/// aggregation semantics.
#[async_trait]
pub trait Producer: Send {
    async fn produce(&self, items: Vec<(TupleKey, u64)>) -> Result<(), ProduceError>;
}

pub struct AggregatedProducer {
    inner: FutureProducer<KafkaContext>,
    output_topic: String,
    produce_timeout: Duration,
    // Envelope encoding for the produced payloads. Only `Lz4`-safe for the
    // intermediate topic, which the merger consumes; the output topic is read
    // by ClickHouse and must stay `None`.
    encoding: EnvelopeEncoding,
    format: WireFormat,
}

impl AggregatedProducer {
    pub async fn new<L>(
        kafka_config: &KafkaConfig,
        liveness: L,
        output_topic: String,
        produce_timeout: Duration,
        encoding: EnvelopeEncoding,
        format: WireFormat,
    ) -> Result<Self, KafkaError>
    where
        L: common_liveness::SyncLivenessReporter + Clone + 'static,
    {
        let inner = create_kafka_producer(kafka_config, liveness).await?;
        Ok(Self {
            inner,
            output_topic,
            produce_timeout,
            encoding,
            format,
        })
    }
}

/// Fixed-width partition key: a stable hash of the tuple. The same
/// (team, type, key, value) tuple from any pod always lands on the same
/// partition, so the merger can merge the per-pod duplicates that the
/// events/groups workers emit across replicas. Hashing instead of embedding
/// the full tuple keeps the key off the wire-bytes bill; collisions only
/// co-locate unrelated tuples on a partition, which is harmless.
pub(crate) fn partition_key(m: &Outgoing) -> String {
    let mut hasher = SipHasher13::new_with_keys(0, 0);
    hasher.write(m.team_id.to_string().as_bytes());
    hasher.write(b":");
    hasher.write(m.property_type.as_kafka_key_segment().as_bytes());
    hasher.write(b":");
    hasher.write(m.property_key.as_bytes());
    hasher.write(b":");
    hasher.write(m.property_value.as_bytes());
    format!("{:016x}", hasher.finish())
}

#[async_trait]
impl Producer for AggregatedProducer {
    async fn produce(&self, items: Vec<(TupleKey, u64)>) -> Result<(), ProduceError> {
        if items.is_empty() {
            return Ok(());
        }
        let total = items.len();

        let format = self.format;
        let payloads: Vec<(Option<String>, Vec<u8>)> = items
            .iter()
            .map(|(tuple, count)| {
                let message = Outgoing {
                    team_id: tuple.team_id,
                    property_type: tuple.property_type,
                    property_key: &tuple.property_key,
                    property_value: &tuple.property_value,
                    property_count: *count,
                };
                let key = Some(partition_key(&message));
                let payload = match format {
                    WireFormat::Json => {
                        serde_json::to_vec(&message).expect("Outgoing serialization is infallible")
                    }
                    WireFormat::Binary => wire::encode(
                        message.team_id,
                        message.property_type,
                        message.property_key,
                        message.property_value,
                        message.property_count,
                    ),
                };
                (key, payload)
            })
            .collect();

        let send_fut = send_keyed_payloads_to_kafka_with_encoding(
            &self.inner,
            &self.output_topic,
            self.encoding,
            payloads,
        );

        let results = match tokio::time::timeout(self.produce_timeout, send_fut).await {
            Ok(r) => r,
            Err(_) => {
                warn!("kafka produce timed out after {:?}", self.produce_timeout);
                return Err(ProduceError::Timeout(self.produce_timeout));
            }
        };

        let failed = results
            .iter()
            .filter(|r| matches!(r, Err(KafkaProduceError::KafkaProduceError { .. })))
            .count();
        if failed > 0 {
            return Err(ProduceError::PartialFailure { failed, total });
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn outgoing<'a>(value: &'a str) -> Outgoing<'a> {
        Outgoing {
            team_id: 2,
            property_type: PropertyType::Event,
            property_key: "$current_url",
            property_value: value,
            property_count: 1,
        }
    }

    #[test]
    fn partition_key_is_stable_and_tuple_specific() {
        let a = partition_key(&outgoing("https://posthog.com/a"));
        let b = partition_key(&outgoing("https://posthog.com/a"));
        let c = partition_key(&outgoing("https://posthog.com/b"));
        assert_eq!(a, b);
        assert_ne!(a, c);
        assert_eq!(a.len(), 16);
    }
}
