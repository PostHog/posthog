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

/// Startup metadata-ping bound for producers built without a broker
/// transaction bound — the value this call used before the bound
/// existed, kept so unrelated services' startup behavior is unchanged.
const UNBOUNDED_PING_TIMEOUT: Duration = Duration::from_secs(15);

/// The `ClientConfig` for a transactional producer: the shared
/// producer's tuning, the transactional id, and — when the caller
/// controls the broker-side bound — `transaction.timeout.ms`.
///
/// A pure function so what the fenced producer inherits is assertable.
/// It previously carried only a fixed subset of the shared tuning, so a
/// deployment that set `message.max.bytes` or batch tuning got two
/// producers behaving differently depending on which flag arm built
/// them.
///
/// Four knobs are deliberately not copied even when configured, because
/// the transactional contract pins them: transactions require
/// idempotence, and idempotence requires `acks=all`, retries above
/// zero, and at most five in-flight requests. librdkafka refuses to
/// build a producer configured against any of those, so a shared
/// override of `enable.idempotence`, `acks`, `retries`, or
/// `max.in.flight.requests.per.connection` must not reach this one.
fn transactional_client_config(
    config: &KafkaConfig,
    transactional_id: &str,
    broker_txn_timeout: Option<Duration>,
) -> Result<ClientConfig, KafkaError> {
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

    if !config.kafka_client_id.is_empty() {
        client_config.set("client.id", &config.kafka_client_id);
    }
    if let Some(v) = config.kafka_producer_batch_size {
        client_config.set("batch.size", v.to_string());
    }
    if let Some(v) = config.kafka_producer_batch_num_messages {
        client_config.set("batch.num.messages", v.to_string());
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

    Ok(client_config)
}

// TODO - it's kinda gross to leak the underlying producer context type here, makes for a really gross API. We should
// probably figure out some trait to abstract over it
pub struct TransactionalProducer<C = DefaultClientContext>
where
    C: ClientContext + 'static,
{
    inner: FutureProducer<C>,
    timeout: Duration,
}

/// A transactional producer that is connected but not yet initialized:
/// the client exists with its connections and metadata warm, and no
/// broker-side transactional state has been touched. `init_transactions`
/// is the fencing action — it bumps the transactional id's epoch and
/// cuts off every previous owner — so it belongs to the moment authority
/// is taken, not to construction. Splitting the phases lets a caller pay
/// the connection cost ahead of that moment.
pub struct ConnectedTransactionalProducer<C = DefaultClientContext>
where
    C: ClientContext + 'static,
{
    inner: FutureProducer<C>,
}

impl ConnectedTransactionalProducer<DefaultClientContext> {
    /// Create the client and ping the brokers, bounded by `timeout`,
    /// without initializing transactions — a producer whose open
    /// transactions the broker abandons after `broker_txn_timeout`,
    /// rather than after librdkafka's default minute.
    ///
    /// The broker bound is a different quantity from `timeout`, which
    /// bounds how long *this process* waits on a blocking call. It
    /// matters to everyone else: until an abandoned transaction expires,
    /// the partition's last-stable-offset does not advance and every
    /// `read_committed` consumer stalls behind it. Only a caller that
    /// also controls `message.timeout.ms` can set it, because librdkafka
    /// requires `message.timeout.ms <= transaction.timeout.ms` and
    /// refuses to build the producer at all otherwise.
    pub fn connect_bounded(
        config: &KafkaConfig,
        transactional_id: &str,
        timeout: Duration,
        broker_txn_timeout: Duration,
    ) -> Result<Self, KafkaError> {
        let inner = connect(
            config,
            transactional_id,
            timeout,
            Some(broker_txn_timeout),
            DefaultClientContext,
        )?;
        Ok(ConnectedTransactionalProducer { inner })
    }
}

impl<C: ClientContext> ConnectedTransactionalProducer<C> {
    /// Claim the transactional id: one `init_transactions` round trip,
    /// which fences every previous owner of the id.
    pub fn init(
        self,
        timeout: Duration,
    ) -> Result<TransactionalProducer<C>, (KafkaError, ConnectedTransactionalProducer<C>)> {
        match self.inner.init_transactions(timeout) {
            Ok(()) => Ok(TransactionalProducer {
                inner: self.inner,
                timeout,
            }),
            // Hand the connection back with the error: a timed-out init
            // does not invalidate the client, and the caller decides
            // whether to retry on it or discard it.
            Err(e) => Err((e, self)),
        }
    }
}

/// Create the client and ping the brokers: everything construction does
/// short of `init_transactions`.
fn connect<C: ClientContext>(
    config: &KafkaConfig,
    transactional_id: &str,
    timeout: Duration,
    broker_txn_timeout: Option<Duration>,
    context: C,
) -> Result<FutureProducer<C>, KafkaError> {
    let client_config = transactional_client_config(config, transactional_id, broker_txn_timeout)?;

    debug!("rdkafka configuration: {:?}", client_config);
    let api: FutureProducer<C> = client_config.create_with_context(context)?;

    // "Ping" the Kafka brokers by requesting metadata. On the
    // broker-bounded (partition-acquisition) path the ping is bounded
    // by the caller's timeout — an unbounded stall there holds a warm
    // slot and delays a handoff. Everywhere else the historical fixed
    // bound is kept, so services that never opted into broker bounds
    // keep their startup behavior.
    let ping_timeout = if broker_txn_timeout.is_some() {
        timeout
    } else {
        UNBOUNDED_PING_TIMEOUT
    };
    match api.client().fetch_metadata(None, ping_timeout) {
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
        Self::build(config, transactional_id, timeout, None, context)
    }

    fn build(
        config: &KafkaConfig,
        transactional_id: &str,
        timeout: Duration,
        broker_txn_timeout: Option<Duration>,
        context: C,
    ) -> Result<Self, KafkaError> {
        let api = connect(
            config,
            transactional_id,
            timeout,
            broker_txn_timeout,
            context,
        )?;
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
        let Err(err) = ConnectedTransactionalProducer::connect_bounded(
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
            ..KafkaConfig::default()
        };
        let client_config = transactional_client_config(&config, "test-txn-id", None)
            .expect("an unbounded config always builds");
        assert_eq!(
            client_config.get("transaction.timeout.ms"),
            None,
            "no broker bound was requested, so none may be set"
        );
        assert_eq!(client_config.get("message.timeout.ms"), Some("20000"));
    }

    /// The fenced producer must carry the shared producer's tuning, not a
    /// fixed subset of it: a deployment that raises `message.max.bytes`
    /// or sets batch or metadata-refresh tuning would otherwise get two
    /// producers behaving differently depending on which flag arm built
    /// them — most consequentially the message ceiling, since the leader
    /// admits person properties within a whisker of librdkafka's default.
    #[test]
    fn the_fenced_producer_inherits_the_shared_tuning() {
        let config = KafkaConfig {
            kafka_client_id: "leader-changelog".to_string(),
            kafka_producer_batch_size: Some(524_288),
            kafka_producer_batch_num_messages: Some(1_000),
            kafka_producer_topic_metadata_refresh_interval_ms: Some(30_000),
            kafka_producer_message_max_bytes: Some(2_097_152),
            kafka_producer_sticky_partitioning_linger_ms: Some(25),
            kafka_producer_partitioner: Some("murmur2_random".to_string()),
            ..KafkaConfig::default()
        };
        let client_config = transactional_client_config(&config, "test-txn-id", None)
            .expect("a compatible config builds");
        for (key, value) in [
            ("client.id", "leader-changelog"),
            ("batch.size", "524288"),
            ("batch.num.messages", "1000"),
            ("topic.metadata.refresh.interval.ms", "30000"),
            ("message.max.bytes", "2097152"),
            ("sticky.partitioning.linger.ms", "25"),
            ("partitioner", "murmur2_random"),
        ] {
            assert_eq!(
                client_config.get(key),
                Some(value),
                "the fenced producer dropped the shared `{key}` tuning"
            );
        }
    }

    /// The four knobs the transactional contract pins must not be copied
    /// even when the shared config sets them: transactions require
    /// idempotence, and idempotence requires acks=all, retries above
    /// zero, and at most five in-flight requests — librdkafka refuses to
    /// build a producer configured against any of those.
    #[test]
    fn the_transactional_contract_pins_its_knobs() {
        let config = KafkaConfig {
            kafka_producer_enable_idempotence: Some(false),
            kafka_producer_acks: Some("1".to_string()),
            kafka_producer_retries: Some(0),
            kafka_producer_max_in_flight_requests_per_connection: Some(50),
            ..KafkaConfig::default()
        };
        let client_config = transactional_client_config(&config, "test-txn-id", None)
            .expect("pinned knobs are dropped, not refused");
        for key in [
            "enable.idempotence",
            "acks",
            "retries",
            "max.in.flight.requests.per.connection",
        ] {
            assert_eq!(
                client_config.get(key),
                None,
                "`{key}` is pinned by the transactional contract and must not be copied"
            );
        }
    }
}
