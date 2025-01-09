use envconfig::Envconfig;
use futures::future::join_all;
use health::HealthHandle;
use rdkafka::{
    consumer::{Consumer, StreamConsumer},
    error::KafkaError,
    producer::{FutureProducer, FutureRecord, Producer},
    ClientConfig, Message,
};
use serde::{de::DeserializeOwned, Serialize};
use serde_json::error::Error as SerdeError;
use std::{
    sync::{Arc, Weak},
    time::Duration,
};
use thiserror::Error;
use tracing::{debug, error, info};

/// This module is a straightforward copy-past of common-kafka, due to the issue described in cymbals Cargo.toml
/// It should be deleted ASAP, pending https://github.com/fede1024/rust-rdkafka/issues/638 being resolved

#[derive(Envconfig, Clone)]
pub struct KafkaConfig {
    #[envconfig(default = "20")]
    pub kafka_producer_linger_ms: u32, // Maximum time between producer batches during low traffic

    #[envconfig(default = "400")]
    pub kafka_producer_queue_mib: u32, // Size of the in-memory producer queue in mebibytes

    #[envconfig(default = "20000")]
    pub kafka_message_timeout_ms: u32, // Time before we stop retrying producing a message: 20 seconds

    #[envconfig(default = "none")]
    pub kafka_compression_codec: String, // none, gzip, snappy, lz4, zstd

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,
}

#[derive(Envconfig, Clone)]
pub struct ConsumerConfig {
    pub kafka_consumer_group: String,
    pub kafka_consumer_topic: String,

    // We default to "earliest" for this, but if you're bringing up a new service, you probably want "latest"
    #[envconfig(default = "earliest")]
    pub kafka_consumer_offset_reset: String, // earliest, latest
}

impl ConsumerConfig {
    /// Because the consumer config is application specific, we
    /// can't set good defaults in the derive macro, so we expose a way
    /// for users to set them here before init'ing their main config struct
    pub fn set_defaults(consumer_group: &str, consumer_topic: &str) {
        if std::env::var("KAFKA_CONSUMER_GROUP").is_err() {
            std::env::set_var("KAFKA_CONSUMER_GROUP", consumer_group);
        };
        if std::env::var("KAFKA_CONSUMER_TOPIC").is_err() {
            std::env::set_var("KAFKA_CONSUMER_TOPIC", consumer_topic);
        };
    }
}

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

        client_config.set("enable.auto.offset.store", "false");

        if common_config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        };

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
        };

        let Some(payload) = message.payload() else {
            // We auto-store poison pills, panicking on failure
            offset.store().unwrap();
            return Err(RecvErr::Empty);
        };

        let payload = match serde_json::from_slice(payload) {
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
                        break; // Early exit on error, since it might indicate a kafka error or something
                    }
                }
            } => {}
        }

        results
    }
}

pub struct Offset {
    handle: Weak<Inner>,
    partition: i32,
    offset: i64,
}

impl Offset {
    pub fn store(self) -> Result<(), OffsetErr> {
        let inner = self.handle.upgrade().ok_or(OffsetErr::Gone)?;
        inner
            .consumer
            .store_offset(&inner.topic, self.partition, self.offset)?;
        Ok(())
    }
}

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

pub async fn send_iter_to_kafka<T>(
    kafka_producer: &FutureProducer<KafkaContext>,
    topic: &str,
    iter: impl IntoIterator<Item = T>,
) -> Result<(), KafkaProduceError>
where
    T: Serialize,
{
    send_keyed_iter_to_kafka(kafka_producer, topic, |_| None, iter).await
}

pub async fn send_keyed_iter_to_kafka<T>(
    kafka_producer: &FutureProducer<KafkaContext>,
    topic: &str,
    key_extractor: impl Fn(&T) -> Option<String>,
    iter: impl IntoIterator<Item = T>,
) -> Result<(), KafkaProduceError>
where
    T: Serialize,
{
    let mut payloads = Vec::new();

    for i in iter {
        let key = key_extractor(&i);
        let payload = serde_json::to_string(&i)
            .map_err(|e| KafkaProduceError::SerializationError { error: e })?;
        payloads.push((key, payload));
    }

    if payloads.is_empty() {
        return Ok(());
    }

    let mut delivery_futures = Vec::new();

    for (key, payload) in payloads {
        match kafka_producer.send_result(FutureRecord {
            topic,
            payload: Some(&payload),
            partition: None,
            key: key.as_deref(),
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
