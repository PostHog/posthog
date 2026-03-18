use std::{collections::HashMap, time::Duration};

use rdkafka::{
    client::DefaultClientContext,
    consumer::ConsumerGroupMetadata,
    error::KafkaError,
    producer::{FutureProducer, Producer},
    ClientConfig, ClientContext, TopicPartitionList,
};
use serde::Serialize;
use tracing::{debug, error, info};

use crate::{
    config::KafkaConfig,
    kafka_consumer::Offset,
    kafka_producer::{
        send_keyed_iter_to_kafka, send_keyed_iter_to_kafka_with_headers, KafkaProduceError,
    },
};

// TODO - it's kinda gross to leak the underlying producer context type here, makes for a really gross API. We should
// probably figure out some trait to abstract over it
pub struct TransactionalProducer<C = DefaultClientContext>
where
    C: ClientContext + 'static,
{
    inner: FutureProducer<C>,
    timeout: Duration,
}

impl TransactionalProducer<DefaultClientContext> {
    // Create a transactional producer, with a default context
    pub fn from_config(
        config: &KafkaConfig,
        transactional_id: &str,
        timeout: Duration,
    ) -> Result<Self, KafkaError> {
        Self::with_context(config, transactional_id, timeout, DefaultClientContext)
    }
}

impl<C: ClientContext> TransactionalProducer<C> {
    pub fn with_context(
        config: &KafkaConfig,
        transactional_id: &str,
        timeout: Duration,
        context: C,
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
        let api: FutureProducer<C> = client_config.create_with_context(context)?;

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

    pub fn begin(&mut self) -> Result<KafkaTransaction<'_, C>, KafkaError> {
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
    pub fn inner(&self) -> &FutureProducer<C> {
        &self.inner
    }
}

pub struct KafkaTransaction<'a, C = DefaultClientContext>
where
    C: ClientContext + 'static,
{
    // NOTE: kafka requires any producer have only a single transaction running at any time. We
    // enforce this by having transactions mutably borrow the initiating producer, although this
    // is not strictly necessary by the rdkafka interface itself
    producer: &'a mut TransactionalProducer<C>,
}

// TODO - most of these are blocking, and we should wrap them in spawn_blocking and expose
// a purely async interface
impl<'a, C: ClientContext> KafkaTransaction<'a, C> {
    pub async fn send_keyed_iter_to_kafka<D>(
        &self,
        topic: &str,
        key_extractor: impl Fn(&D) -> Option<String>,
        iter: impl IntoIterator<Item = D>,
    ) -> Vec<Result<(), KafkaProduceError>>
    where
        D: Serialize,
    {
        send_keyed_iter_to_kafka(&self.producer.inner, topic, key_extractor, iter).await
    }

    pub async fn send_keyed_iter_to_kafka_with_headers<D>(
        &self,
        topic: &str,
        key_extractor: impl Fn(&D) -> Option<String>,
        headers_extractor: impl Fn(&D) -> Option<rdkafka::message::OwnedHeaders>,
        iter: impl IntoIterator<Item = D>,
    ) -> Vec<Result<(), KafkaProduceError>>
    where
        D: Serialize,
    {
        send_keyed_iter_to_kafka_with_headers(
            &self.producer.inner,
            topic,
            key_extractor,
            headers_extractor,
            iter,
        )
        .await
    }

    pub async fn send_iter_to_kafka<D>(
        &self,
        topic: &str,
        iter: impl IntoIterator<Item = D>,
    ) -> Vec<Result<(), KafkaProduceError>>
    where
        D: Serialize,
    {
        send_keyed_iter_to_kafka(&self.producer.inner, topic, |_| None, iter).await
    }

    pub fn associate_offsets(
        &self,
        offsets: Vec<Offset>,
        metadata: &ConsumerGroupMetadata,
    ) -> Result<(), KafkaError> {
        let tpl = to_topic_partition_list(offsets)?;
        self.producer
            .inner
            .send_offsets_to_transaction(&tpl, metadata, self.producer.timeout)
    }

    pub fn commit(self) -> Result<(), KafkaError> {
        self.producer
            .inner
            .commit_transaction(self.producer.timeout)?;
        Ok(())
    }

    pub fn abort(self) -> Result<(), KafkaError> {
        self.producer
            .inner
            .abort_transaction(self.producer.timeout)?;
        Ok(())
    }
}

fn to_topic_partition_list(offsets: Vec<Offset>) -> Result<TopicPartitionList, KafkaError> {
    let mut topic_map = HashMap::new();
    for offset in offsets.into_iter() {
        let key = (offset.topic, offset.partition);
        let stored = topic_map.entry(key).or_insert(offset.offset);
        if *stored < offset.offset {
            *stored = offset.offset
        }
    }

    let topic_map = topic_map
        .into_iter()
        // Docs say: "The offsets should be the next message your application will consume,
        // i.e., one greater than the the last processed message’s offset for each partition."
        // Link: https://docs.rs/rdkafka/latest/rdkafka/producer/trait.Producer.html#tymethod.send_offsets_to_transaction.
        // Since this is only used for associating offsets with a transaction, we know that each
        // offset should be the next message to be consumed, i.e. the high watermark + 1.
        .map(|(k, v)| (k, rdkafka::Offset::from_raw(v + 1)))
        .collect();

    TopicPartitionList::from_topic_map(&topic_map)
}
