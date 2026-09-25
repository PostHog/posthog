//! Named Kafka producers, declared in code and instantiated once.
//!
//! A [`ProducerName`] is a connection slot, not a fixed cluster: charts wire
//! each slot to a cluster per deployment, the same model as Node.js
//! ingestion's `KafkaProducerRegistry`. A slot's settings are read from
//! `KAFKA_<SLOT>_PRODUCER_<RDKAFKA_KEY>` variables, and every output that
//! publishes through a slot shares its one producer.

use std::collections::HashMap;
use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;

use envconfig::Envconfig;
use rdkafka::producer::{FutureProducer, Producer};
use rdkafka::util::Timeout;
use rdkafka::ClientConfig;
use tracing::log::{debug, info};

use crate::sinks::kafka::KafkaContext;
use crate::sinks::producer::RdKafkaProducer;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ProducerName {
    /// The cluster the ingestion pipelines consume capture's topics from.
    Ingestion,
}

impl ProducerName {
    pub const ALL: [ProducerName; 1] = [ProducerName::Ingestion];

    pub fn as_str(&self) -> &'static str {
        match self {
            ProducerName::Ingestion => "INGESTION",
        }
    }

    // Slot names are single words, so no prefix is a prefix of another.
    fn env_prefix(&self) -> String {
        format!("KAFKA_{}_PRODUCER_", self.as_str())
    }
}

impl FromStr for ProducerName {
    type Err = anyhow::Error;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::ALL
            .into_iter()
            .find(|name| name.as_str() == s)
            .ok_or_else(|| {
                let known: Vec<&str> = Self::ALL.iter().map(|name| name.as_str()).collect();
                anyhow::anyhow!("unknown producer {s:?}, expected one of {known:?}")
            })
    }
}

/// One producer's connection and tuning. Each field maps to the rdkafka key of
/// the same name.
#[derive(Envconfig, Clone, Debug)]
pub struct ProducerConfig {
    // `kafka:9092` is the broker in local dev and hobby. A deployment that
    // forgets to wire the slot fails its liveness check instead of producing
    // somewhere unexpected.
    #[envconfig(default = "kafka:9092")]
    pub metadata_broker_list: String,
    #[envconfig(default = "")]
    pub security_protocol: String,
    #[envconfig(default = "")]
    pub enable_ssl_certificate_verification: String,
    #[envconfig(default = "")]
    pub client_id: String,
    #[envconfig(default = "none")]
    pub compression_codec: String,
    #[envconfig(default = "20")]
    pub linger_ms: u32,
    #[envconfig(default = "1000000")]
    pub batch_size: u32,
    #[envconfig(default = "10000")]
    pub batch_num_messages: u32,
    #[envconfig(default = "100000")]
    pub queue_buffering_max_messages: u32,
    #[envconfig(default = "409600")]
    pub queue_buffering_max_kbytes: u32,
    #[envconfig(default = "1000000")]
    pub message_max_bytes: u32,
    #[envconfig(default = "20000")]
    pub message_timeout_ms: u32,
    #[envconfig(default = "10")]
    pub sticky_partitioning_linger_ms: u32,
    #[envconfig(default = "20000")]
    pub topic_metadata_refresh_interval_ms: u32,
    #[envconfig(default = "60000")]
    pub metadata_max_age_ms: u32,
    /// `message.send.max.retries`, named `RETRIES` as in Node.js ingestion.
    #[envconfig(default = "2")]
    pub retries: u32,
    #[envconfig(default = "1000000")]
    pub max_in_flight_requests_per_connection: u32,
    #[envconfig(default = "false")]
    pub enable_idempotence: bool,
    #[envconfig(default = "all")]
    pub acks: String,
    #[envconfig(default = "murmur2_random")]
    pub partitioner: String,
    #[envconfig(default = "60000")]
    pub socket_timeout_ms: u32,
    #[envconfig(default = "")]
    pub broker_address_family: String,
    #[envconfig(default = "true")]
    pub log_connection_close: bool,
    #[envconfig(default = "1000")]
    pub retry_backoff_max_ms: u32,
    #[envconfig(default = "0")]
    pub socket_send_buffer_bytes: u32,
    #[envconfig(default = "0")]
    pub socket_receive_buffer_bytes: u32,
}

impl ProducerConfig {
    pub fn load(name: ProducerName, env: &HashMap<String, String>) -> anyhow::Result<Self> {
        let prefix = name.env_prefix();
        let slot_env: HashMap<String, String> = env
            .iter()
            .filter_map(|(k, v)| {
                k.strip_prefix(&prefix)
                    .map(|key| (key.to_string(), v.clone()))
            })
            .collect();
        Self::init_from_hashmap(&slot_env)
            .map_err(|e| anyhow::anyhow!("producer {}: {e}", name.as_str()))
    }

    fn client_config(&self) -> ClientConfig {
        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &self.metadata_broker_list)
            .set("statistics.interval.ms", "10000")
            .set("partitioner", &self.partitioner)
            .set("metadata.max.age.ms", self.metadata_max_age_ms.to_string())
            .set(
                "topic.metadata.refresh.interval.ms",
                self.topic_metadata_refresh_interval_ms.to_string(),
            )
            .set("message.send.max.retries", self.retries.to_string())
            .set("linger.ms", self.linger_ms.to_string())
            .set("message.max.bytes", self.message_max_bytes.to_string())
            .set("message.timeout.ms", self.message_timeout_ms.to_string())
            .set("socket.timeout.ms", self.socket_timeout_ms.to_string())
            .set("compression.codec", &self.compression_codec)
            .set(
                "queue.buffering.max.kbytes",
                self.queue_buffering_max_kbytes.to_string(),
            )
            .set("acks", &self.acks)
            .set("batch.num.messages", self.batch_num_messages.to_string())
            .set("batch.size", self.batch_size.to_string())
            .set(
                "max.in.flight.requests.per.connection",
                self.max_in_flight_requests_per_connection.to_string(),
            )
            .set(
                "sticky.partitioning.linger.ms",
                self.sticky_partitioning_linger_ms.to_string(),
            )
            .set("enable.idempotence", self.enable_idempotence.to_string())
            .set(
                "log.connection.close",
                self.log_connection_close.to_string(),
            )
            .set(
                "queue.buffering.max.messages",
                self.queue_buffering_max_messages.to_string(),
            )
            .set(
                "retry.backoff.max.ms",
                self.retry_backoff_max_ms.to_string(),
            )
            .set(
                "socket.send.buffer.bytes",
                self.socket_send_buffer_bytes.to_string(),
            )
            .set(
                "socket.receive.buffer.bytes",
                self.socket_receive_buffer_bytes.to_string(),
            );

        for (key, value) in [
            ("broker.address.family", &self.broker_address_family),
            ("client.id", &self.client_id),
            ("security.protocol", &self.security_protocol),
            (
                "enable.ssl.certificate.verification",
                &self.enable_ssl_certificate_verification,
            ),
        ] {
            if !value.is_empty() {
                client_config.set(key, value);
            }
        }

        client_config
    }
}

pub type ProducerHandle = Arc<RdKafkaProducer<KafkaContext>>;

/// Every declared producer, each instantiated once.
pub struct ProducerRegistry {
    producers: HashMap<ProducerName, ProducerHandle>,
}

impl ProducerRegistry {
    pub fn build(
        configs: &HashMap<ProducerName, ProducerConfig>,
        mut liveness: HashMap<ProducerName, lifecycle::Handle>,
    ) -> anyhow::Result<Self> {
        let mut producers = HashMap::new();
        for name in ProducerName::ALL {
            let config = configs
                .get(&name)
                .ok_or_else(|| anyhow::anyhow!("no config for producer {}", name.as_str()))?;
            let producer = create_producer(name, config, liveness.remove(&name))?;
            producers.insert(name, producer);
        }
        Ok(Self { producers })
    }

    pub fn get(&self, name: ProducerName) -> ProducerHandle {
        Arc::clone(&self.producers[&name])
    }
}

pub fn load_all(
    env: &HashMap<String, String>,
) -> anyhow::Result<HashMap<ProducerName, ProducerConfig>> {
    ProducerName::ALL
        .into_iter()
        .map(|name| Ok((name, ProducerConfig::load(name, env)?)))
        .collect()
}

fn create_producer(
    name: ProducerName,
    config: &ProducerConfig,
    liveness: Option<lifecycle::Handle>,
) -> anyhow::Result<ProducerHandle> {
    info!(
        "connecting producer {} to Kafka brokers at {}...",
        name.as_str(),
        config.metadata_broker_list
    );

    let client_config = config.client_config();
    debug!("rdkafka configuration: {client_config:?}");

    let producer: FutureProducer<KafkaContext> =
        client_config.create_with_context(KafkaContext::new(liveness.clone()))?;

    // A failed ping is not an error, because other sinks may still report healthy.
    if producer
        .client()
        .fetch_metadata(
            Some("__consumer_offsets"),
            Timeout::After(Duration::new(10, 0)),
        )
        .is_ok()
    {
        if let Some(liveness) = &liveness {
            liveness.report_healthy();
        }
        info!("connected to Kafka brokers");
    };

    Ok(Arc::new(RdKafkaProducer::new(producer)))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn default_config_sets_the_legacy_rdkafka_settings() {
        let client_config = ProducerConfig::load(ProducerName::Ingestion, &HashMap::new())
            .unwrap()
            .client_config();

        let expected = [
            ("bootstrap.servers", "kafka:9092"),
            ("statistics.interval.ms", "10000"),
            ("partitioner", "murmur2_random"),
            ("metadata.max.age.ms", "60000"),
            ("topic.metadata.refresh.interval.ms", "20000"),
            ("message.send.max.retries", "2"),
            ("linger.ms", "20"),
            ("message.max.bytes", "1000000"),
            ("message.timeout.ms", "20000"),
            ("socket.timeout.ms", "60000"),
            ("compression.codec", "none"),
            ("queue.buffering.max.kbytes", "409600"),
            ("acks", "all"),
            ("batch.num.messages", "10000"),
            ("batch.size", "1000000"),
            ("max.in.flight.requests.per.connection", "1000000"),
            ("sticky.partitioning.linger.ms", "10"),
            ("enable.idempotence", "false"),
            ("log.connection.close", "true"),
            ("queue.buffering.max.messages", "100000"),
            ("retry.backoff.max.ms", "1000"),
            ("socket.send.buffer.bytes", "0"),
            ("socket.receive.buffer.bytes", "0"),
        ];
        for (key, value) in expected {
            assert_eq!(client_config.get(key), Some(value), "{key}");
        }
        for unset in [
            "broker.address.family",
            "client.id",
            "security.protocol",
            "enable.ssl.certificate.verification",
        ] {
            assert_eq!(client_config.get(unset), None, "{unset}");
        }
    }

    #[test]
    fn load_reads_only_its_slot_prefix() {
        let config = ProducerConfig::load(
            ProducerName::Ingestion,
            &env(&[
                ("KAFKA_INGESTION_PRODUCER_METADATA_BROKER_LIST", "msk:9094"),
                ("KAFKA_INGESTION_PRODUCER_SECURITY_PROTOCOL", "ssl"),
                ("KAFKA_INGESTION_PRODUCER_RETRIES", "7"),
                ("KAFKA_HOSTS", "legacy:9092"),
                ("KAFKA_PRODUCER_LINGER_MS", "99"),
            ]),
        )
        .unwrap();

        assert_eq!(config.metadata_broker_list, "msk:9094");
        assert_eq!(config.security_protocol, "ssl");
        assert_eq!(config.retries, 7);
        assert_eq!(config.linger_ms, 20);
    }

    #[test]
    fn load_rejects_an_unparseable_value() {
        let err = ProducerConfig::load(
            ProducerName::Ingestion,
            &env(&[("KAFKA_INGESTION_PRODUCER_LINGER_MS", "soon")]),
        )
        .unwrap_err();

        assert!(err.to_string().contains("INGESTION"), "{err}");
    }

    #[test]
    fn producer_name_parses_only_declared_slots() {
        assert_eq!(
            "INGESTION".parse::<ProducerName>().unwrap(),
            ProducerName::Ingestion
        );
        for unknown in ["ingestion", "WARPSTREAM", ""] {
            let err = unknown.parse::<ProducerName>().unwrap_err();
            assert!(err.to_string().contains("INGESTION"), "{err}");
        }
    }
}
