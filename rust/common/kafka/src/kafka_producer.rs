use std::io::Write;
use std::sync::Arc;

use crate::config::KafkaConfig;
use common_liveness::SyncLivenessReporter;
use lz4::EncoderBuilder;
use rdkafka::error::KafkaError;
use rdkafka::producer::{
    DeliveryResult, FutureProducer, FutureRecord, Producer, ProducerContext, ThreadedProducer,
};
use rdkafka::{ClientConfig, ClientContext};
use serde::Serialize;
use serde_json::error::Error as SerdeError;
use thiserror::Error;
use tracing::{debug, error, info, warn};

const KAFKA_LZ4_COMPRESS_TOTAL: &str = "common_kafka_lz4_compress_total";
const KAFKA_LZ4_COMPRESS_UNCOMPRESSED_BYTES: &str = "common_kafka_lz4_compress_uncompressed_bytes";
const KAFKA_LZ4_COMPRESS_COMPRESSED_BYTES: &str = "common_kafka_lz4_compress_compressed_bytes";

/// Envelope-level encoding applied to the serialized message value before it is
/// produced, independent of the broker-level `compression.codec`. `Lz4` emits
/// the LZ4 *frame* format, whose magic bytes let `SingleTopicConsumer`
/// decompress transparently — so encoded and plain messages can coexist on a
/// topic during rollout. Use `Lz4` only for topics consumed by
/// `SingleTopicConsumer`, never for ones read by a ClickHouse Kafka engine
/// table, which expects raw rows.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum EnvelopeEncoding {
    #[default]
    None,
    Lz4,
}

impl std::str::FromStr for EnvelopeEncoding {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_ref() {
            "none" => Ok(EnvelopeEncoding::None),
            "lz4" => Ok(EnvelopeEncoding::Lz4),
            _ => Err(format!("Unknown EnvelopeEncoding: {s}")),
        }
    }
}

pub struct KafkaContext {
    liveness: Arc<dyn SyncLivenessReporter>,
}

impl KafkaContext {
    pub fn new(liveness: impl SyncLivenessReporter + Clone + 'static) -> Self {
        Self {
            liveness: Arc::new(liveness),
        }
    }
}

impl From<health::HealthHandle> for KafkaContext {
    fn from(value: health::HealthHandle) -> Self {
        Self::new(value)
    }
}

impl rdkafka::ClientContext for KafkaContext {
    fn stats(&self, _: rdkafka::Statistics) {
        // Signal liveness, as the main rdkafka loop is running and calling us
        self.liveness.report_healthy();

        // TODO: Take stats recording pieces that we want from `capture-rs`.
    }
}

/// Build the shared rdkafka `ClientConfig` from our `KafkaConfig`. Both the
/// `FutureProducer` and `ThreadedProducer` builders go through this, so the two
/// producer styles always apply identical connection and tuning settings.
fn build_client_config(config: &KafkaConfig) -> ClientConfig {
    let mut client_config = ClientConfig::new();
    client_config
        .set("bootstrap.servers", &config.kafka_hosts)
        .set("statistics.interval.ms", "10000")
        .set("linger.ms", config.kafka_producer_linger_ms.to_string())
        .set(
            "message.timeout.ms",
            config.kafka_message_timeout_ms.to_string(),
        )
        .set(
            "compression.codec",
            config.kafka_compression_codec.to_owned(),
        )
        .set(
            "queue.buffering.max.kbytes",
            (config.kafka_producer_queue_mib * 1024).to_string(),
        )
        .set(
            "queue.buffering.max.messages",
            config.kafka_producer_queue_messages.to_string(),
        );

    // `client.id` identifies this producer to the broker (shows up in broker
    // metrics/logs). Only set when non-empty so existing callers keep
    // librdkafka's default identity.
    if !config.kafka_client_id.is_empty() {
        client_config.set("client.id", &config.kafka_client_id);
    }

    // WarpStream producer tuning — only set when explicitly configured, so existing services
    // that don't opt in keep their previous librdkafka defaults.
    if let Some(v) = config.kafka_producer_batch_size {
        client_config.set("batch.size", v.to_string());
    }
    if let Some(v) = config.kafka_producer_batch_num_messages {
        client_config.set("batch.num.messages", v.to_string());
    }
    if let Some(v) = config.kafka_producer_enable_idempotence {
        client_config.set("enable.idempotence", v.to_string());
    }
    if let Some(v) = config.kafka_producer_max_in_flight_requests_per_connection {
        client_config.set("max.in.flight.requests.per.connection", v.to_string());
    }
    if let Some(v) = config.kafka_producer_topic_metadata_refresh_interval_ms {
        client_config.set("topic.metadata.refresh.interval.ms", v.to_string());
    }
    if let Some(v) = config.kafka_producer_message_max_bytes {
        client_config.set("message.max.bytes", v.to_string());
    }
    if let Some(v) = config.kafka_producer_sticky_partitioning_linger_ms {
        client_config.set("sticky.partitioning.linger.ms", v.to_string());
    }
    if let Some(ref v) = config.kafka_producer_partitioner {
        client_config.set("partitioner", v);
    }
    if let Some(ref v) = config.kafka_producer_acks {
        client_config.set("acks", v);
    }
    if let Some(v) = config.kafka_producer_retries {
        client_config.set("retries", v.to_string());
    }

    if config.kafka_tls {
        client_config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    };

    client_config
}

/// Ping the Kafka brokers by fetching metadata, so a broker that's unreachable
/// at startup surfaces as an error here rather than silently later.
fn ping_brokers<C, P>(producer: &P) -> Result<(), KafkaError>
where
    C: ProducerContext,
    P: Producer<C>,
{
    match producer
        .client()
        .fetch_metadata(None, std::time::Duration::from_secs(15))
    {
        Ok(metadata) => {
            info!(
                "Successfully connected to Kafka brokers. Found {} topics.",
                metadata.topics().len()
            );
            Ok(())
        }
        Err(error) => {
            error!("Failed to fetch metadata from Kafka brokers: {:?}", error);
            Err(error)
        }
    }
}

pub async fn create_kafka_producer<L>(
    config: &KafkaConfig,
    liveness: L,
) -> Result<FutureProducer<KafkaContext>, KafkaError>
where
    L: SyncLivenessReporter + Clone + 'static,
{
    let client_config = build_client_config(config);
    debug!("rdkafka configuration: {:?}", client_config);
    let api: FutureProducer<KafkaContext> =
        client_config.create_with_context(KafkaContext::new(liveness))?;

    ping_brokers(&api)?;

    Ok(api)
}

/// A producer context that reports liveness (like [`KafkaContext`]) and, for
/// each produced message, invokes a caller-supplied closure with the delivery
/// report. This lets a caller observe delivery outcomes — e.g. emit
/// metrics — from rdkafka's own poll thread, with no per-message task and
/// without baking caller-specific logic into the shared context.
///
/// `K` is the per-message opaque payload the caller attaches via
/// [`rdkafka::producer::BaseRecord::delivery_opaque`]; it is handed back to the
/// closure on delivery so labels/context travel with the message.
/// Shared delivery-report callback for [`ThreadedKafkaContext`]: invoked once
/// per message with the delivery result and the per-message opaque `K`.
type DeliveryCallback<K> = Arc<dyn Fn(&DeliveryResult, K) + Send + Sync>;

pub struct ThreadedKafkaContext<K: Send + Sync + 'static> {
    liveness: Arc<dyn SyncLivenessReporter>,
    on_delivery: DeliveryCallback<K>,
}

impl<K: Send + Sync + 'static> ThreadedKafkaContext<K> {
    pub fn new(
        liveness: impl SyncLivenessReporter + Clone + 'static,
        on_delivery: impl Fn(&DeliveryResult, K) + Send + Sync + 'static,
    ) -> Self {
        Self {
            liveness: Arc::new(liveness),
            on_delivery: Arc::new(on_delivery),
        }
    }
}

impl<K: Send + Sync + 'static> ClientContext for ThreadedKafkaContext<K> {
    fn stats(&self, _: rdkafka::Statistics) {
        // Signal liveness, as the rdkafka poll thread is running and calling us.
        self.liveness.report_healthy();
    }
}

impl<K: Send + Sync + 'static> ProducerContext for ThreadedKafkaContext<K> {
    type DeliveryOpaque = Box<K>;

    fn delivery(&self, delivery_result: &DeliveryResult, delivery_opaque: Self::DeliveryOpaque) {
        (self.on_delivery)(delivery_result, *delivery_opaque);
    }
}

/// Create a [`ThreadedProducer`] that reports liveness and calls `on_delivery`
/// with each message's delivery report (see [`ThreadedKafkaContext`]). The
/// producer runs its own poll thread, so no manual polling is needed. This is
/// the opt-in path for fire-and-forget producers that want delivery
/// observability without a per-message task; existing `FutureProducer` callers
/// are unaffected.
pub async fn create_threaded_kafka_producer<K, L, F>(
    config: &KafkaConfig,
    liveness: L,
    on_delivery: F,
) -> Result<ThreadedProducer<ThreadedKafkaContext<K>>, KafkaError>
where
    K: Send + Sync + 'static,
    L: SyncLivenessReporter + Clone + 'static,
    F: Fn(&DeliveryResult, K) + Send + Sync + 'static,
{
    let client_config = build_client_config(config);
    debug!("rdkafka configuration (threaded): {:?}", client_config);
    let producer: ThreadedProducer<ThreadedKafkaContext<K>> =
        client_config.create_with_context(ThreadedKafkaContext::new(liveness, on_delivery))?;

    ping_brokers(&producer)?;

    Ok(producer)
}

#[derive(Error, Debug)]
pub enum KafkaProduceError {
    #[error("failed to serialize: {error}")]
    SerializationError { error: SerdeError },
    #[error("failed to produce to kafka: {error}")]
    KafkaProduceError { error: KafkaError },
    #[error("failed to produce to kafka (timeout)")]
    KafkaProduceCanceled,
}

pub async fn send_iter_to_kafka<T, C: ClientContext>(
    kafka_producer: &FutureProducer<C>,
    topic: &str,
    iter: impl IntoIterator<Item = T>,
) -> Vec<Result<(), KafkaProduceError>>
where
    T: Serialize,
{
    send_keyed_iter_to_kafka(kafka_producer, topic, |_| None, iter).await
}

pub async fn send_keyed_iter_to_kafka<T, C: ClientContext>(
    kafka_producer: &FutureProducer<C>,
    topic: &str,
    key_extractor: impl Fn(&T) -> Option<String>,
    iter: impl IntoIterator<Item = T>,
) -> Vec<Result<(), KafkaProduceError>>
where
    T: Serialize,
{
    send_keyed_iter_to_kafka_with_headers(kafka_producer, topic, key_extractor, |_| None, iter)
        .await
}

/// Like `send_keyed_iter_to_kafka`, but applies the given envelope encoding to
/// each serialized payload before producing. With `EnvelopeEncoding::Lz4` the
/// frame magic bytes let `SingleTopicConsumer` decompress transparently, so
/// encoded and plain messages can coexist on a topic during rollout.
pub async fn send_keyed_iter_to_kafka_with_encoding<T, C: ClientContext>(
    kafka_producer: &FutureProducer<C>,
    topic: &str,
    key_extractor: impl Fn(&T) -> Option<String>,
    encoding: EnvelopeEncoding,
    iter: impl IntoIterator<Item = T>,
) -> Vec<Result<(), KafkaProduceError>>
where
    T: Serialize,
{
    send_keyed_iter_to_kafka_inner(
        kafka_producer,
        topic,
        key_extractor,
        |_| None,
        iter,
        encoding,
    )
    .await
}

pub async fn send_keyed_iter_to_kafka_with_headers<T, C: ClientContext>(
    kafka_producer: &FutureProducer<C>,
    topic: &str,
    key_extractor: impl Fn(&T) -> Option<String>,
    headers_extractor: impl Fn(&T) -> Option<rdkafka::message::OwnedHeaders>,
    iter: impl IntoIterator<Item = T>,
) -> Vec<Result<(), KafkaProduceError>>
where
    T: Serialize,
{
    send_keyed_iter_to_kafka_inner(
        kafka_producer,
        topic,
        key_extractor,
        headers_extractor,
        iter,
        EnvelopeEncoding::None,
    )
    .await
}

pub async fn send_keyed_payloads_to_kafka_with_encoding<C: ClientContext>(
    kafka_producer: &FutureProducer<C>,
    topic: &str,
    encoding: EnvelopeEncoding,
    iter: impl IntoIterator<Item = (Option<String>, Vec<u8>)>,
) -> Vec<Result<(), KafkaProduceError>> {
    send_prepared_payloads_inner(
        kafka_producer,
        topic,
        iter.into_iter()
            .map(|(key, payload)| (key, None, Ok(payload))),
        encoding,
    )
    .await
}

async fn send_keyed_iter_to_kafka_inner<T, C: ClientContext>(
    kafka_producer: &FutureProducer<C>,
    topic: &str,
    key_extractor: impl Fn(&T) -> Option<String>,
    headers_extractor: impl Fn(&T) -> Option<rdkafka::message::OwnedHeaders>,
    iter: impl IntoIterator<Item = T>,
    encoding: EnvelopeEncoding,
) -> Vec<Result<(), KafkaProduceError>>
where
    T: Serialize,
{
    let prepared = iter.into_iter().map(move |item| {
        let key = key_extractor(&item);
        let headers = headers_extractor(&item);
        let payload = serde_json::to_vec(&item)
            .map_err(|e| KafkaProduceError::SerializationError { error: e });
        (key, headers, payload)
    });
    send_prepared_payloads_inner(kafka_producer, topic, prepared, encoding).await
}

async fn send_prepared_payloads_inner<C: ClientContext>(
    kafka_producer: &FutureProducer<C>,
    topic: &str,
    iter: impl IntoIterator<
        Item = (
            Option<String>,
            Option<rdkafka::message::OwnedHeaders>,
            Result<Vec<u8>, KafkaProduceError>,
        ),
    >,
    encoding: EnvelopeEncoding,
) -> Vec<Result<(), KafkaProduceError>> {
    let mut results = Vec::new();
    let mut handles = Vec::new();

    for (index, (key, headers, payload)) in iter.into_iter().enumerate() {
        let json = match payload {
            Ok(p) => p,
            Err(e) => {
                results.push((index, Err(e)));
                continue;
            }
        };

        // On compression failure we fall back to the raw JSON: the consumer
        // handles both, so failing open keeps the topic flowing.
        let payload = match encoding {
            EnvelopeEncoding::None => json,
            EnvelopeEncoding::Lz4 => maybe_compress_lz4_frame(json, topic),
        };

        let record = FutureRecord {
            topic,
            key: key.as_deref(),
            payload: Some(&payload),
            timestamp: None,
            partition: None,
            headers,
        };

        let future_handle = match kafka_producer.send_result(record) {
            Ok(f) => f,
            Err((e, _)) => {
                results.push((
                    index,
                    Err(KafkaProduceError::KafkaProduceError { error: e }),
                ));
                continue;
            }
        };

        handles.push((index, future_handle));
    }

    for handle in handles {
        let (index, future_handle) = handle;
        match future_handle.await {
            Ok(Ok(_)) => results.push((index, Ok(()))),
            Ok(Err((e, _))) => results.push((
                index,
                Err(KafkaProduceError::KafkaProduceError { error: e }),
            )),
            Err(_) => results.push((index, Err(KafkaProduceError::KafkaProduceCanceled))),
        }
    }

    // Sort to return in passed-in order
    results.sort_by_key(|e| e.0);

    results.into_iter().map(|(_, r)| r).collect()
}

/// LZ4-frame-compress `payload`, falling back to the original bytes if the
/// encoder errors (extremely unlikely with an in-memory writer). The frame
/// magic bytes are what the consumer keys off to decompress transparently.
fn maybe_compress_lz4_frame(payload: Vec<u8>, topic: &str) -> Vec<u8> {
    match compress_lz4_frame(&payload) {
        Ok(compressed) => {
            metrics::counter!(
                KAFKA_LZ4_COMPRESS_TOTAL,
                "topic" => topic.to_string(),
                "result" => "success",
            )
            .increment(1);
            metrics::histogram!(KAFKA_LZ4_COMPRESS_UNCOMPRESSED_BYTES, "topic" => topic.to_string())
                .record(payload.len() as f64);
            metrics::histogram!(KAFKA_LZ4_COMPRESS_COMPRESSED_BYTES, "topic" => topic.to_string())
                .record(compressed.len() as f64);
            compressed
        }
        Err(e) => {
            metrics::counter!(
                KAFKA_LZ4_COMPRESS_TOTAL,
                "topic" => topic.to_string(),
                "result" => "failure",
            )
            .increment(1);
            warn!(error = %e, topic, "failed to LZ4-compress Kafka payload, producing raw JSON");
            payload
        }
    }
}

fn compress_lz4_frame(payload: &[u8]) -> std::io::Result<Vec<u8>> {
    let mut encoder = EncoderBuilder::new().build(Vec::with_capacity(payload.len()))?;
    encoder.write_all(payload)?;
    let (compressed, result) = encoder.finish();
    result?;
    Ok(compressed)
}

#[cfg(test)]
mod tests {
    use std::io::Read;

    use lz4::Decoder;

    use super::{
        build_client_config, compress_lz4_frame, maybe_compress_lz4_frame, EnvelopeEncoding,
    };
    use crate::config::KafkaConfig;
    use crate::kafka_consumer::LZ4_FRAME_MAGIC;

    #[test]
    fn client_id_is_set_only_when_non_empty() {
        // Empty client_id (every existing caller today) must leave the key
        // unset so librdkafka keeps its default identity — the behavior-neutral
        // guarantee the shared helper makes.
        let config = KafkaConfig {
            kafka_client_id: String::new(),
            ..Default::default()
        };
        assert_eq!(build_client_config(&config).get("client.id"), None);

        let config = KafkaConfig {
            kafka_client_id: "capture-ingestion-warnings".to_string(),
            ..Default::default()
        };
        assert_eq!(
            build_client_config(&config).get("client.id"),
            Some("capture-ingestion-warnings")
        );
    }

    #[test]
    fn lz4_frame_starts_with_magic_and_round_trips() {
        let original = br#"{"team_id":1,"property_key":"$browser","property_value":"Chrome"}"#;

        let compressed = compress_lz4_frame(original).unwrap();

        assert!(
            compressed.starts_with(LZ4_FRAME_MAGIC),
            "compressed payload must carry the LZ4 frame magic so the consumer detects it"
        );

        let mut decoder = Decoder::new(compressed.as_slice()).unwrap();
        let mut decompressed = Vec::new();
        decoder.read_to_end(&mut decompressed).unwrap();
        assert_eq!(decompressed, original);
    }

    #[test]
    fn maybe_compress_round_trips_for_lz4() {
        let original = br#"{"team_id":42,"property_value":"x"}"#.to_vec();

        let payload = maybe_compress_lz4_frame(original.clone(), "test-topic");

        let mut decoder = Decoder::new(payload.as_slice()).unwrap();
        let mut decompressed = Vec::new();
        decoder.read_to_end(&mut decompressed).unwrap();
        assert_eq!(decompressed, original);
    }

    #[test]
    fn envelope_encoding_parses_from_str() {
        assert_eq!(
            "none".parse::<EnvelopeEncoding>(),
            Ok(EnvelopeEncoding::None)
        );
        assert_eq!("LZ4".parse::<EnvelopeEncoding>(), Ok(EnvelopeEncoding::Lz4));
        assert!(" lz4 ".parse::<EnvelopeEncoding>().is_ok());
        assert!("gzip".parse::<EnvelopeEncoding>().is_err());
    }
}
