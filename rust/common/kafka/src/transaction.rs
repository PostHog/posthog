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

    /// A producer whose open transactions the broker abandons after
    /// `broker_txn_timeout`, rather than after librdkafka's default
    /// minute.
    ///
    /// This is a different quantity from `timeout`, which bounds how long
    /// *this process* waits on a blocking transactional call. The broker
    /// bound matters to everyone else: until an abandoned transaction
    /// expires, the partition's last-stable-offset does not advance and
    /// every `read_committed` consumer stalls behind it.
    ///
    /// Only a caller that also controls `message.timeout.ms` can set it,
    /// because librdkafka requires `message.timeout.ms <=
    /// transaction.timeout.ms` and refuses to build the producer at all
    /// otherwise — which is why this is opt-in rather than derived from
    /// the operation timeout.
    pub fn from_config_bounded(
        config: &KafkaConfig,
        transactional_id: &str,
        timeout: Duration,
        broker_txn_timeout: Duration,
    ) -> Result<Self, KafkaError> {
        Self::build(
            config,
            transactional_id,
            timeout,
            Some(broker_txn_timeout),
            DefaultClientContext,
        )
    }
}

impl<C: ClientContext> TransactionalProducer<C> {
    pub fn with_context(
        config: &KafkaConfig,
        transactional_id: &str,
        timeout: Duration,
        context: C,
    ) -> Result<Self, KafkaError> {
        Self::build(config, transactional_id, timeout, None, context)
    }

    fn build(
        config: &KafkaConfig,
        transactional_id: &str,
        timeout: Duration,
        broker_txn_timeout: Option<Duration>,
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

        if let Some(broker_txn_timeout) = broker_txn_timeout {
            let message_timeout_ms = u128::from(config.kafka_message_timeout_ms);
            if message_timeout_ms > broker_txn_timeout.as_millis() {
                // librdkafka reports this as a bare string from
                // `rd_kafka_new`; say which two knobs disagree instead.
                return Err(KafkaError::ClientCreation(format!(
                    "message.timeout.ms ({message_timeout_ms}) exceeds the requested \
                     transaction.timeout.ms ({}) for transactional id {transactional_id}",
                    broker_txn_timeout.as_millis(),
                )));
            }
            client_config.set(
                "transaction.timeout.ms",
                broker_txn_timeout.as_millis().to_string(),
            );
        }

        if config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        };

        debug!("rdkafka configuration: {:?}", client_config);
        let api: FutureProducer<C> = client_config.create_with_context(context)?;

        // "Ping" the Kafka brokers by requesting metadata, bounded by
        // the caller's timeout: this runs on the partition-acquisition
        // path, where an unbounded stall holds a warm slot and delays a
        // handoff.
        match api.client().fetch_metadata(None, timeout) {
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

#[cfg(test)]
mod tests {
    use super::*;

    /// librdkafka refuses to build a transactional producer whose
    /// `message.timeout.ms` exceeds its `transaction.timeout.ms`, and the
    /// two are set from different places: the message timeout comes from
    /// the shared `KafkaConfig`, the transaction timeout from whoever asks
    /// for a bounded producer. A caller that sets only the latter gets a
    /// producer that cannot be constructed at all — which is a startup
    /// crash loop, not a degraded mode.
    ///
    /// `Duration::from_secs(10)` against the default 20s message timeout
    /// is the combination that shape belongs to; the bounded constructor
    /// has to reject it by name rather than let librdkafka reject it by
    /// string.
    #[test]
    fn a_broker_bound_under_the_message_timeout_is_refused_by_name() {
        let config = KafkaConfig {
            kafka_message_timeout_ms: 20_000,
            ..KafkaConfig::default()
        };
        let Err(err) = TransactionalProducer::from_config_bounded(
            &config,
            "test-txn-id",
            Duration::from_secs(10),
            Duration::from_secs(10),
        ) else {
            panic!("a broker bound below the message timeout must not build a producer");
        };
        // Deliberately asserting on the values, not the knob names:
        // librdkafka's own rejection string names both knobs too, so a
        // name-only assertion would pass just as well with this check
        // removed and the failure left to the C library.
        let message = err.to_string();
        assert!(
            message.contains("20000") && message.contains("10000"),
            "the error should report the two timeouts that disagree, got: {message}"
        );
    }

    /// The unbounded constructors must not set `transaction.timeout.ms` at
    /// all, so a caller whose message timeout exceeds its operation
    /// timeout keeps librdkafka's default rather than inheriting a bound
    /// it never asked for.
    #[test]
    fn an_unbounded_producer_does_not_inherit_the_operation_timeout() {
        let config = KafkaConfig {
            kafka_message_timeout_ms: 20_000,
            kafka_hosts: "127.0.0.1:9".to_string(),
            ..KafkaConfig::default()
        };
        // No broker is listening, so this fails at the metadata ping —
        // but it must get that far, i.e. past client construction.
        let Err(err) =
            TransactionalProducer::from_config(&config, "test-txn-id", Duration::from_secs(1))
        else {
            panic!("no broker is listening on this port");
        };
        assert!(
            !err.to_string().contains("must be set"),
            "the producer was rejected at construction rather than reaching the broker: {err}"
        );
    }
}
