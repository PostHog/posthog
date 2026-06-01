use std::{
    borrow::Cow,
    fmt,
    io::Read,
    sync::{Arc, Weak},
};

use lz4::Decoder;
use rdkafka::{
    consumer::{CommitMode, Consumer, ConsumerGroupMetadata, StreamConsumer},
    error::KafkaError,
    ClientConfig, Message,
};
use serde::de::DeserializeOwned;
use std::time::Duration;
use tracing::warn;

use crate::config::{ConsumerConfig, KafkaConfig};

const LZ4_FRAME_MAGIC: &[u8; 4] = &[0x04, 0x22, 0x4d, 0x18];
const MAX_DECOMPRESSED_KAFKA_PAYLOAD_BYTES: usize = 64 * 1024 * 1024;

#[derive(Clone)]
pub struct SingleTopicConsumer {
    inner: Arc<Inner>,
}

struct Inner {
    consumer: StreamConsumer,
    topic: String,
}

#[derive(Debug, thiserror::Error)]
pub enum RecvErr {
    #[error("Kafka error: {0}")]
    Kafka(#[from] KafkaError),
    #[error("Serde error: {0}")]
    Serde(#[from] serde_json::Error),
    #[error("Received empty payload")]
    Empty,
}

#[derive(Debug, thiserror::Error)]
pub enum OffsetErr {
    #[error("Kafka error: {0}")]
    Kafka(#[from] KafkaError),
    #[error("Consumer gone")]
    Gone,
}

impl SingleTopicConsumer {
    pub fn new(
        common_config: KafkaConfig,
        consumer_config: ConsumerConfig,
    ) -> Result<Self, KafkaError> {
        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &common_config.kafka_hosts)
            .set("statistics.interval.ms", "10000")
            .set("group.id", consumer_config.kafka_consumer_group)
            .set(
                "auto.offset.reset",
                &consumer_config.kafka_consumer_offset_reset,
            );

        if !common_config.kafka_client_rack.is_empty() {
            client_config.set("client.rack", &common_config.kafka_client_rack);
        }

        if !common_config.kafka_client_id.is_empty() {
            client_config.set("client.id", &common_config.kafka_client_id);
        }

        // IMPORTANT: this means *by default* all consumers are
        // responsible for storing their own offsets, regardless
        // of whether automatic offset commit is enabled or disabled!
        client_config.set("enable.auto.offset.store", "false");

        if common_config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        };

        if consumer_config.kafka_consumer_auto_commit {
            client_config.set("enable.auto.commit", "true").set(
                "auto.commit.interval.ms",
                consumer_config
                    .kafka_consumer_auto_commit_interval_ms
                    .to_string(),
            );
        }

        if let Some(v) = consumer_config.kafka_consumer_fetch_wait_max_ms {
            client_config.set("fetch.wait.max.ms", v.to_string());
        }
        if let Some(v) = consumer_config.kafka_consumer_fetch_min_bytes {
            client_config.set("fetch.min.bytes", v.to_string());
        }
        if let Some(v) = consumer_config.kafka_consumer_fetch_max_bytes {
            client_config.set("fetch.max.bytes", v.to_string());
        }
        if let Some(v) = consumer_config.kafka_consumer_max_partition_fetch_bytes {
            client_config.set("max.partition.fetch.bytes", v.to_string());
        }

        if let Some(ref id) = consumer_config.kafka_consumer_group_instance_id {
            client_config.set("group.instance.id", id);
        }
        if let Some(ref strategy) = consumer_config.kafka_consumer_partition_strategy {
            client_config.set("partition.assignment.strategy", strategy);
        }
        if let Some(ref v) = consumer_config.kafka_consumer_socket_send_buffer_bytes {
            client_config.set("socket.send.buffer.bytes", v);
        }
        if let Some(ref v) = consumer_config.kafka_consumer_socket_receive_buffer_bytes {
            client_config.set("socket.receive.buffer.bytes", v);
        }
        if let Some(v) = consumer_config.kafka_consumer_metadata_refresh_interval_ms {
            client_config.set("topic.metadata.refresh.interval.ms", v.to_string());
        }

        let consumer: StreamConsumer = client_config.create()?;
        consumer.subscribe(&[consumer_config.kafka_consumer_topic.as_str()])?;

        let inner = Inner {
            consumer,
            topic: consumer_config.kafka_consumer_topic,
        };
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    pub async fn json_recv<T>(&self) -> Result<(T, Offset), RecvErr>
    where
        T: DeserializeOwned,
    {
        let message = self.inner.consumer.recv().await?;

        let offset = Offset {
            handle: Arc::downgrade(&self.inner),
            partition: message.partition(),
            offset: message.offset(),
            topic: self.inner.topic.clone(),
        };

        let Some(payload) = message.payload() else {
            // We auto-store poison pills, panicking on failure
            offset.store().unwrap();
            return Err(RecvErr::Empty);
        };

        let payload = match deserialize_json_payload(payload) {
            Ok(p) => p,
            Err(e) => {
                // We auto-store poison pills, panicking on failure
                offset.store().unwrap();
                return Err(RecvErr::Serde(e));
            }
        };

        Ok((payload, offset))
    }

    pub async fn json_recv_batch<T>(
        &self,
        max: usize,
        timeout: Duration,
    ) -> Vec<Result<(T, Offset), RecvErr>>
    where
        T: DeserializeOwned,
    {
        let mut results = Vec::with_capacity(max);

        tokio::select! {
            _ = tokio::time::sleep(timeout) => {},
            _ = async {
                while results.len() < max {
                    let result = self.json_recv::<T>().await;
                    let was_err = result.is_err();
                    results.push(result);
                    if was_err {
                        break; // Early exit on error, since it might indicate a kafka error or somethingz
                    }
                }
            } => {}
        }

        results
    }

    pub fn metadata(&self) -> ConsumerGroupMetadata {
        self.inner
            .consumer
            .group_metadata()
            .expect("It is impossible to construct a stream consumer without a group id")
    }

    pub fn commit(&self) -> Result<(), KafkaError> {
        self.inner.consumer.commit_consumer_state(CommitMode::Sync)
    }
}

fn deserialize_json_payload<T>(payload: &[u8]) -> Result<T, serde_json::Error>
where
    T: DeserializeOwned,
{
    let payload = maybe_decompress_lz4_payload(payload);
    serde_json::from_slice(&payload)
}

fn maybe_decompress_lz4_payload(payload: &[u8]) -> Cow<'_, [u8]> {
    if !payload.starts_with(LZ4_FRAME_MAGIC) {
        return Cow::Borrowed(payload);
    }

    match decompress_lz4_payload(payload, MAX_DECOMPRESSED_KAFKA_PAYLOAD_BYTES) {
        Ok(decompressed) => Cow::Owned(decompressed),
        Err(error) => {
            warn!("Failed to decompress LZ4 Kafka payload: {error}");
            Cow::Borrowed(payload)
        }
    }
}

fn decompress_lz4_payload(payload: &[u8], limit: usize) -> Result<Vec<u8>, std::io::Error> {
    let decoder = Decoder::new(payload)?;
    let mut decompressed = Vec::new();
    decoder
        .take((limit as u64).saturating_add(1))
        .read_to_end(&mut decompressed)?;

    if decompressed.len() > limit {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!(
                "decompressed payload exceeded limit ({} > {} bytes)",
                decompressed.len(),
                limit
            ),
        ));
    }

    Ok(decompressed)
}

pub struct Offset {
    handle: Weak<Inner>,
    pub(crate) topic: String,
    pub(crate) partition: i32,
    pub(crate) offset: i64,
}

impl Offset {
    pub fn store(self) -> Result<(), OffsetErr> {
        let inner = self.handle.upgrade().ok_or(OffsetErr::Gone)?;
        inner
            .consumer
            .store_offset(&self.topic, self.partition, self.offset)?;
        Ok(())
    }

    pub fn get_value(&self) -> i64 {
        self.offset
    }

    pub fn partition(&self) -> i32 {
        self.partition
    }

    pub fn topic(&self) -> &str {
        &self.topic
    }
}

impl fmt::Debug for Offset {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(
            f,
            "{{ partition: {}, offset: {} }}",
            self.partition, self.offset
        )
    }
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use lz4::EncoderBuilder;
    use serde_json::{json, Value};

    use super::{decompress_lz4_payload, deserialize_json_payload};

    #[test]
    fn deserializes_plain_json_payload() {
        let payload = br#"{"event":"$pageview","team_id":1}"#;

        let parsed: Value = deserialize_json_payload(payload).unwrap();

        assert_eq!(parsed["event"], "$pageview");
        assert_eq!(parsed["team_id"], 1);
    }

    #[test]
    fn deserializes_lz4_json_payload() {
        let original = br#"{"event":"$pageview","team_id":1}"#;
        let payload = lz4_payload(original);

        let parsed: Value = deserialize_json_payload(&payload).unwrap();

        assert_eq!(parsed["event"], "$pageview");
        assert_eq!(parsed["team_id"], 1);
    }

    #[test]
    fn invalid_lz4_payload_falls_back_to_json_error() {
        let payload = [0x04, 0x22, 0x4d, 0x18, b'n', b'o', b'p', b'e'];

        assert!(deserialize_json_payload::<Value>(&payload).is_err());
    }

    #[test]
    fn oversized_lz4_payload_is_rejected() {
        let payload = lz4_payload(&json!({"large": "x".repeat(256)}).to_string().into_bytes());

        assert!(decompress_lz4_payload(&payload, 16).is_err());
    }

    fn lz4_payload(value: &[u8]) -> Vec<u8> {
        let mut encoder = EncoderBuilder::new().build(Vec::new()).unwrap();
        encoder.write_all(value).unwrap();
        let (compressed, result) = encoder.finish();
        result.unwrap();
        compressed
    }
}
