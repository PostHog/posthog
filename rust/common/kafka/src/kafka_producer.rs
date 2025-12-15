use crate::config::KafkaConfig;

use health::HealthHandle;
use rdkafka::error::KafkaError;
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use rdkafka::{ClientConfig, ClientContext};
use serde::Serialize;
use serde_json::error::Error as SerdeError;
use thiserror::Error;
use tracing::{debug, error, info};

pub struct KafkaContext {
    liveness: HealthHandle,
}

impl From<HealthHandle> for KafkaContext {
    fn from(value: HealthHandle) -> Self {
        KafkaContext { liveness: value }
    }
}

impl rdkafka::ClientContext for KafkaContext {
    fn stats(&self, _: rdkafka::Statistics) {
        // Signal liveness, as the main rdkafka loop is running and calling us
        self.liveness.report_healthy_blocking();

        // TODO: Take stats recording pieces that we want from `capture-rs`.
    }
}

pub async fn create_kafka_producer(
    config: &KafkaConfig,
    liveness: HealthHandle,
) -> Result<FutureProducer<KafkaContext>, KafkaError> {
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

    if config.kafka_tls {
        client_config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    };

    debug!("rdkafka configuration: {:?}", client_config);
    let api: FutureProducer<KafkaContext> = client_config.create_with_context(liveness.into())?;

    // "Ping" the Kafka brokers by requesting metadata
    match api
        .client()
        .fetch_metadata(None, std::time::Duration::from_secs(15))
    {
        Ok(metadata) => {
            info!(
                "Successfully connected to Kafka brokers. Found {} topics.",
                metadata.topics().len()
            );
        }
        Err(error) => {
            error!("Failed to fetch metadata from Kafka brokers: {:?}", error);
            return Err(error);
        }
    }

    Ok(api)
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
    let mut results = Vec::new();
    let mut handles = Vec::new();

    for (index, item) in iter.into_iter().enumerate() {
        let key = key_extractor(&item);
        let headers = headers_extractor(&item);
        let payload = match serde_json::to_string(&item)
            .map_err(|e| KafkaProduceError::SerializationError { error: e })
        {
            Ok(p) => p,
            Err(e) => {
                results.push((index, Err(e)));
                continue;
            }
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
