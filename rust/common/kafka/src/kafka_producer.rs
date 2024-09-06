use crate::config::KafkaConfig;

use futures::future::join_all;
use health::HealthHandle;
use rdkafka::error::{KafkaError, KafkaResult};
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use rdkafka::ClientConfig;
use serde::Serialize;
use serde_json::error::Error as SerdeError;
use thiserror::Error;
use tracing::{debug, error, info};

pub struct KafkaContext {
    liveness: HealthHandle,
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
        );

    if config.kafka_tls {
        client_config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    };

    debug!("rdkafka configuration: {:?}", client_config);
    let api: FutureProducer<KafkaContext> =
        client_config.create_with_context(KafkaContext { liveness })?;

    // "Ping" the Kafka brokers by requesting metadata
    match api
        .client()
        .fetch_metadata(None, std::time::Duration::from_secs(2))
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

pub async fn send_iter_to_kafka<T>(
    kafka_producer: &FutureProducer<KafkaContext>,
    topic: &str,
    iter: impl IntoIterator<Item = T>,
) -> Result<(), KafkaProduceError>
where
    T: Serialize,
{
    let mut payloads = Vec::new();

    for i in iter {
        let payload = serde_json::to_string(&i)
            .map_err(|e| KafkaProduceError::SerializationError { error: e })?;
        payloads.push(payload);
    }

    if payloads.is_empty() {
        return Ok(());
    }

    let mut delivery_futures = Vec::new();

    for payload in payloads {
        match kafka_producer.send_result(FutureRecord {
            topic,
            payload: Some(&payload),
            partition: None,
            key: None::<&str>,
            timestamp: None,
            headers: None,
        }) {
            Ok(future) => delivery_futures.push(future),
            Err((error, _)) => return Err(KafkaProduceError::KafkaProduceError { error }),
        }
    }

    for result in join_all(delivery_futures).await {
        match result {
            Ok(Ok(_)) => {}
            Ok(Err((error, _))) => return Err(KafkaProduceError::KafkaProduceError { error }),
            Err(_) => {
                // Cancelled due to timeout while retrying
                return Err(KafkaProduceError::KafkaProduceCanceled);
            }
        }
    }

    Ok(())
}
