use std::{
    borrow::Cow,
    fmt,
    io::Read,
    sync::{Arc, Weak},
    time::{Duration, Instant},
};

use lz4::Decoder;
use rdkafka::{
    consumer::{CommitMode, Consumer, ConsumerGroupMetadata, StreamConsumer},
    error::KafkaError,
    ClientConfig, Message, TopicPartitionList,
};
use serde::de::DeserializeOwned;
use tracing::warn;

use crate::config::{ConsumerConfig, KafkaConfig};

pub(crate) const LZ4_FRAME_MAGIC: &[u8; 4] = &[0x04, 0x22, 0x4d, 0x18];
const MAX_DECOMPRESSED_KAFKA_PAYLOAD_BYTES: usize = 64 * 1024 * 1024;
const KAFKA_LZ4_PAYLOADS_TOTAL: &str = "common_kafka_lz4_payloads_total";
const KAFKA_LZ4_COMPRESSED_BYTES: &str = "common_kafka_lz4_compressed_bytes";
const KAFKA_LZ4_DECOMPRESSED_BYTES: &str = "common_kafka_lz4_decompressed_bytes";
const KAFKA_LZ4_DECOMPRESSION_SECONDS: &str = "common_kafka_lz4_decompression_seconds";

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

        client_config.set(
            "enable.auto.commit",
            consumer_config.kafka_consumer_auto_commit.to_string(),
        );
        if consumer_config.kafka_consumer_auto_commit {
            client_config.set(
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
        self.recv_with(|payload| serde_json::from_slice(payload))
            .await
    }

    pub async fn recv_with<T, D>(&self, decode: D) -> Result<(T, Offset), RecvErr>
    where
        D: Fn(&[u8]) -> Result<T, serde_json::Error>,
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

        let payload = maybe_decompress_lz4_payload(payload, &self.inner.topic);
        let payload = match decode(&payload) {
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

    /// Synchronously commit explicit next-offsets for this consumer's topic, bypassing stored
    /// offsets. Each pair is `(partition, next_offset)` where `next_offset` is the offset
    /// consumption should resume from (last fully processed + 1), per Kafka commit semantics.
    pub fn commit_partition_offsets(&self, offsets: &[(i32, i64)]) -> Result<(), KafkaError> {
        let mut tpl = TopicPartitionList::with_capacity(offsets.len());
        for &(partition, next_offset) in offsets {
            tpl.add_partition_offset(
                &self.inner.topic,
                partition,
                rdkafka::Offset::Offset(next_offset),
            )?;
        }
        self.inner.consumer.commit(&tpl, CommitMode::Sync)
    }

    /// Currently assigned partitions of this consumer's topic (local call, no broker round-trip).
    pub fn assigned_partitions(&self) -> Result<Vec<i32>, KafkaError> {
        Ok(self
            .inner
            .consumer
            .assignment()?
            .elements_for_topic(&self.inner.topic)
            .iter()
            .map(|elem| elem.partition())
            .collect())
    }
}

fn maybe_decompress_lz4_payload<'a>(payload: &'a [u8], topic: &str) -> Cow<'a, [u8]> {
    if !payload.starts_with(LZ4_FRAME_MAGIC) {
        return Cow::Borrowed(payload);
    }

    record_lz4_payload(topic, "attempt", "detected");
    metrics::histogram!(KAFKA_LZ4_COMPRESSED_BYTES, "topic" => topic.to_string())
        .record(payload.len() as f64);

    let start = Instant::now();
    let decompression_result =
        decompress_lz4_payload(payload, MAX_DECOMPRESSED_KAFKA_PAYLOAD_BYTES);

    match decompression_result {
        Ok(decompressed) => {
            metrics::histogram!(
                KAFKA_LZ4_DECOMPRESSION_SECONDS,
                "topic" => topic.to_string(),
                "result" => "success",
                "reason" => "ok",
            )
            .record(start.elapsed().as_secs_f64());
            record_lz4_payload(topic, "success", "ok");
            metrics::histogram!(KAFKA_LZ4_DECOMPRESSED_BYTES, "topic" => topic.to_string())
                .record(decompressed.len() as f64);
            Cow::Owned(decompressed)
        }
        Err(error) => {
            metrics::histogram!(
                KAFKA_LZ4_DECOMPRESSION_SECONDS,
                "topic" => topic.to_string(),
                "result" => "failure",
                "reason" => error.reason(),
            )
            .record(start.elapsed().as_secs_f64());
            record_lz4_payload(topic, "failure", error.reason());
            warn!(
                error = %error,
                reason = error.reason(),
                compressed_bytes = payload.len(),
                "Failed to decompress LZ4 Kafka payload"
            );
            Cow::Borrowed(payload)
        }
    }
}

fn record_lz4_payload(topic: &str, result: &str, reason: &str) {
    metrics::counter!(
        KAFKA_LZ4_PAYLOADS_TOTAL,
        "topic" => topic.to_string(),
        "result" => result.to_string(),
        "reason" => reason.to_string(),
    )
    .increment(1);
}

#[derive(Debug, thiserror::Error)]
enum Lz4PayloadError {
    #[error("decode error: {0}")]
    Decode(#[from] std::io::Error),
    #[error("decompressed payload exceeded limit of {limit} bytes")]
    TooLarge { limit: usize },
}

impl Lz4PayloadError {
    fn reason(&self) -> &'static str {
        match self {
            Self::Decode(_) => "decode_error",
            Self::TooLarge { .. } => "too_large",
        }
    }
}

fn decompress_lz4_payload(payload: &[u8], limit: usize) -> Result<Vec<u8>, Lz4PayloadError> {
    let decoder = Decoder::new(payload)?;
    let mut decompressed = Vec::with_capacity(payload.len().saturating_mul(4).min(limit));
    decoder
        .take((limit as u64).saturating_add(1))
        .read_to_end(&mut decompressed)?;

    if decompressed.len() > limit {
        return Err(Lz4PayloadError::TooLarge { limit });
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
    use std::time::Duration;

    use envconfig::Envconfig;
    use lz4::EncoderBuilder;
    use rdkafka::consumer::Consumer;
    use rdkafka::producer::FutureRecord;
    use serde_json::{json, Value};

    use super::SingleTopicConsumer;
    use super::{decompress_lz4_payload, maybe_decompress_lz4_payload, Lz4PayloadError};
    use crate::config::ConsumerConfig;

    fn decode_json_payload(payload: &[u8], topic: &str) -> Result<Value, serde_json::Error> {
        let payload = maybe_decompress_lz4_payload(payload, topic);
        serde_json::from_slice(&payload)
    }

    #[test]
    fn deserializes_plain_json_payload() {
        let payload = br#"{"event":"$pageview","team_id":1}"#;

        let parsed: Value = decode_json_payload(payload, "test-topic").unwrap();

        assert_eq!(parsed["event"], "$pageview");
        assert_eq!(parsed["team_id"], 1);
    }

    #[test]
    fn deserializes_lz4_json_payload() {
        let original = br#"{"event":"$pageview","team_id":1}"#;
        let payload = lz4_payload(original);

        let parsed: Value = decode_json_payload(&payload, "test-topic").unwrap();

        assert_eq!(parsed["event"], "$pageview");
        assert_eq!(parsed["team_id"], 1);
    }

    #[test]
    fn invalid_lz4_payload_falls_back_to_json_error() {
        let payload = [0x04, 0x22, 0x4d, 0x18, b'n', b'o', b'p', b'e'];

        assert!(decode_json_payload(&payload, "test-topic").is_err());
    }

    #[test]
    fn oversized_lz4_payload_is_rejected() {
        let payload = lz4_payload(&json!({"large": "x".repeat(256)}).to_string().into_bytes());

        assert!(matches!(
            decompress_lz4_payload(&payload, 16),
            Err(Lz4PayloadError::TooLarge { .. })
        ));
    }

    fn lz4_payload(value: &[u8]) -> Vec<u8> {
        let mut encoder = EncoderBuilder::new().build(Vec::new()).unwrap();
        encoder.write_all(value).unwrap();
        let (compressed, result) = encoder.finish();
        result.unwrap();
        compressed
    }

    #[tokio::test]
    async fn commits_explicit_partition_offsets_and_reports_assignment() {
        const TOPIC: &str = "explicit-commit-topic";
        let (cluster, producer) = crate::test::create_mock_kafka().await;
        cluster.create_topic(TOPIC, 1, 1).expect("create topic");

        let mut kafka_config = crate::config::KafkaConfig::init_from_env().unwrap();
        kafka_config.kafka_hosts = cluster.bootstrap_servers();
        let consumer_config = ConsumerConfig {
            kafka_consumer_group: "explicit-commit-group".to_string(),
            kafka_consumer_topic: TOPIC.to_string(),
            kafka_consumer_offset_reset: "earliest".to_string(),
            kafka_consumer_auto_commit: false,
            kafka_consumer_auto_commit_interval_ms: 5000,
            kafka_consumer_fetch_wait_max_ms: None,
            kafka_consumer_fetch_min_bytes: None,
            kafka_consumer_fetch_max_bytes: None,
            kafka_consumer_max_partition_fetch_bytes: None,
            kafka_consumer_group_instance_id: None,
            kafka_consumer_partition_strategy: None,
            kafka_consumer_socket_send_buffer_bytes: None,
            kafka_consumer_socket_receive_buffer_bytes: None,
            kafka_consumer_metadata_refresh_interval_ms: None,
        };
        let consumer = SingleTopicConsumer::new(kafka_config, consumer_config).unwrap();

        producer
            .send_result(FutureRecord::to(TOPIC).key("k").payload(r#"{"a":1}"#))
            .expect("enqueue")
            .await
            .expect("produce canceled")
            .expect("produce failed");

        let (_, offset) = consumer.json_recv::<Value>().await.expect("recv");
        assert_eq!((offset.partition(), offset.get_value()), (0, 0));

        assert_eq!(consumer.assigned_partitions().unwrap(), vec![0]);
        consumer
            .commit_partition_offsets(&[(0, 1)])
            .expect("explicit commit");

        let committed = consumer
            .inner
            .consumer
            .committed(Duration::from_secs(5))
            .expect("fetch committed");
        let elems = committed.elements_for_topic(TOPIC);
        assert_eq!(elems.len(), 1);
        assert_eq!(elems[0].offset(), rdkafka::Offset::Offset(1));
    }
}
