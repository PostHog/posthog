use std::time::Duration;

use rdkafka::{
    error::KafkaError,
    producer::{FutureProducer, Producer},
    ClientConfig,
};
use serde::Serialize;
use tracing::{debug, error, info};

use crate::{
    config::KafkaConfig,
    kafka_producer::{send_keyed_iter_to_kafka, KafkaProduceError},
};

pub struct TransactionalProducer {
    inner: FutureProducer,
    timeout: Duration,
}

// TODO - right now, these don't hook into the liveness reporting we use elsewhere, because
// I needed them to be droppable, and theres no good way to make our liveness reporting be able
// to handle that.
impl TransactionalProducer {
    pub fn from_config(
        config: &KafkaConfig,
        transactional_id: &str,
        timeout: Duration,
    ) -> Result<Self, KafkaError> {
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
            )
            .set("transactional.id", transactional_id);

        if config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        };

        debug!("rdkafka configuration: {:?}", client_config);
        let api: FutureProducer = client_config.create()?;

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

        api.init_transactions(timeout)?;

        Ok(TransactionalProducer {
            inner: api,
            timeout,
        })
    }

    pub fn begin(self) -> Result<KafkaTransaction, KafkaError> {
        self.inner.begin_transaction()?;
        Ok(KafkaTransaction { producer: self })
    }

    pub fn set_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    // Expose the inner at the producer level, but not at the transaction level -
    // during a transaction, we want strong control over the operations done, but outside
    // of the transaction, we want to be able to do things like fetch metadata
    pub fn inner(&self) -> &FutureProducer {
        &self.inner
    }
}

// Transactions are either read-write or write-only
pub struct KafkaTransaction {
    producer: TransactionalProducer,
}

// TODO - support for read offset commit association, which turns out to be a little tricky
impl KafkaTransaction {
    pub async fn send_keyed_iter_to_kafka<D>(
        &self,
        topic: &str,
        key_extractor: impl Fn(&D) -> Option<String>,
        iter: impl IntoIterator<Item = D>,
    ) -> Result<(), KafkaProduceError>
    where
        D: Serialize,
    {
        send_keyed_iter_to_kafka(&self.producer.inner, topic, key_extractor, iter).await
    }

    pub async fn send_iter_to_kafka<D>(
        &self,
        topic: &str,
        iter: impl IntoIterator<Item = D>,
    ) -> Result<(), KafkaProduceError>
    where
        D: Serialize,
    {
        send_keyed_iter_to_kafka(&self.producer.inner, topic, |_| None, iter).await
    }

    pub fn commit(self) -> Result<TransactionalProducer, KafkaError> {
        self.producer
            .inner
            .commit_transaction(self.producer.timeout)?;
        Ok(self.producer)
    }

    pub fn abort(self) -> Result<TransactionalProducer, KafkaError> {
        self.producer
            .inner
            .abort_transaction(self.producer.timeout)?;
        Ok(self.producer)
    }
}
