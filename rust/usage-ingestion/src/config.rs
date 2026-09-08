use std::str::FromStr;
use std::time::Duration;

use common_kafka::config::KafkaConfig;
use common_kafka_consumer::config::ConsumerConfigBuilder;
use envconfig::Envconfig;
use rdkafka::ClientConfig;

use crate::counters::CounterConfig;
use crate::kafka::KafkaBatchConfig;

/// WarpStream's recommended librdkafka producer settings.
/// <https://docs.warpstream.com/warpstream/kafka/configure-kafka-client/tuning-for-performance>
const BATCH_SIZE: u32 = 16_000_000;
const BATCH_NUM_MESSAGES: u32 = 100_000;
/// librdkafka caps a produce request at this, so it has to exceed `BATCH_SIZE`.
const MESSAGE_MAX_BYTES: u32 = 64_000_000;
const MAX_IN_FLIGHT_PER_CONNECTION: u32 = 1_000_000;
const METADATA_REFRESH_INTERVAL_MS: u32 = 60_000;

const _: () = assert!(MESSAGE_MAX_BYTES > BATCH_SIZE);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TransportMode {
    Grpc,
    Kafka,
    Both,
}

impl FromStr for TransportMode {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_lowercase().as_str() {
            "grpc" => Ok(Self::Grpc),
            "kafka" => Ok(Self::Kafka),
            "both" => Ok(Self::Both),
            other => Err(format!(
                "unknown usage ingestion transport {other:?}; expected grpc, kafka, or both"
            )),
        }
    }
}

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "USAGE_INGESTION_MODE", default = "grpc")]
    pub transport_mode: TransportMode,
    #[envconfig(from = "USAGE_INGESTION_GRPC_ADDRESS", default = "0.0.0.0:7143")]
    pub grpc_address: String,
    #[envconfig(from = "USAGE_INGESTION_METRICS_ADDRESS", default = "0.0.0.0:7144")]
    pub metrics_address: String,
    #[envconfig(from = "USAGE_INGESTION_DATABASE_URL")]
    pub database_url: String,
    #[envconfig(from = "KAFKA_HOSTS", default = "localhost:9092")]
    pub kafka_hosts: String,
    #[envconfig(from = "KAFKA_TLS", default = "false")]
    pub kafka_tls: bool,
    /// Empty uses `KAFKA_HOSTS`, which keeps the single-cluster local setup simple.
    #[envconfig(from = "USAGE_INGESTION_KAFKA_INPUT_HOSTS", default = "")]
    pub kafka_input_hosts: String,
    /// Unset follows `KAFKA_TLS`; production can override it when input and output differ.
    #[envconfig(from = "USAGE_INGESTION_KAFKA_INPUT_TLS")]
    pub kafka_input_tls: Option<bool>,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_INPUT_TOPIC",
        default = "usage_ingestion"
    )]
    pub kafka_input_topic: String,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_DEAD_LETTER_TOPIC",
        default = "usage_ingestion_dlq"
    )]
    pub kafka_dead_letter_topic: String,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_DEAD_LETTER_MESSAGE_TIMEOUT_MS",
        default = "20000"
    )]
    pub kafka_dead_letter_message_timeout_ms: u32,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_CONSUMER_GROUP",
        default = "usage-ingestion"
    )]
    pub kafka_consumer_group: String,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_CONSUMER_CLIENT_ID",
        default = "usage-ingestion-consumer"
    )]
    pub kafka_consumer_client_id: String,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_CONSUMER_TOPIC_METADATA_REFRESH_INTERVAL_MS",
        default = "60000"
    )]
    pub kafka_consumer_topic_metadata_refresh_interval_ms: u32,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_CONSUMER_FETCH_MAX_BYTES",
        default = "50242880"
    )]
    pub kafka_consumer_fetch_max_bytes: u32,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_CONSUMER_MAX_PARTITION_FETCH_BYTES",
        default = "50242880"
    )]
    pub kafka_consumer_max_partition_fetch_bytes: u32,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_CONSUMER_FETCH_WAIT_MAX_MS",
        default = "10000"
    )]
    pub kafka_consumer_fetch_wait_max_ms: u32,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_CONSUMER_SOCKET_SEND_BUFFER_BYTES",
        default = "0"
    )]
    pub kafka_consumer_socket_send_buffer_bytes: u32,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_CONSUMER_SOCKET_RECEIVE_BUFFER_BYTES",
        default = "0"
    )]
    pub kafka_consumer_socket_receive_buffer_bytes: u32,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_CONSUMER_RETRY_BACKOFF_MAX_MS",
        default = "60000"
    )]
    pub kafka_consumer_retry_backoff_max_ms: u32,
    #[envconfig(from = "USAGE_INGESTION_KAFKA_CONSUMER_BATCH_SIZE", default = "100")]
    pub kafka_consumer_batch_size: usize,
    #[envconfig(
        from = "USAGE_INGESTION_KAFKA_CONSUMER_BATCH_TIMEOUT_MS",
        default = "10"
    )]
    pub kafka_consumer_batch_timeout_ms: u64,
    #[envconfig(from = "USAGE_INGESTION_KAFKA_CONSUMER_CONCURRENCY", default = "16")]
    pub kafka_consumer_concurrency: usize,
    /// Only "none", "gzip", "snappy" and "lz4" work. "zstd" needs an rdkafka feature the
    /// workspace does not enable, so librdkafka refuses it when it builds the producer.
    #[envconfig(from = "KAFKA_COMPRESSION_CODEC", default = "lz4")]
    pub kafka_compression_codec: String,
    /// These records never fill a batch, so linger decides when a produce goes out and lands
    /// in ingest latency. Lower it if that matters more than batching.
    #[envconfig(from = "KAFKA_PRODUCER_LINGER_MS", default = "100")]
    pub kafka_producer_linger_ms: u32,
    #[envconfig(from = "USAGE_INGESTION_MAX_BATCH_SIZE", default = "500")]
    pub max_batch_size: usize,
    /// Empty keeps the Redis projection disabled, which is the safe default for existing deployments.
    #[envconfig(from = "USAGE_INGESTION_REDIS_URL", default = "")]
    pub redis_url: String,
    #[envconfig(from = "USAGE_INGESTION_REDIS_FLUSH_INTERVAL_SECONDS", default = "15")]
    pub redis_flush_interval_seconds: u64,
    #[envconfig(from = "USAGE_INGESTION_REDIS_CONNECTIONS", default = "16")]
    pub redis_connections: usize,
    #[envconfig(from = "USAGE_INGESTION_REDIS_FLUSH_CONCURRENCY", default = "16")]
    pub redis_flush_concurrency: usize,
    // Overridable so a test environment can use the suffixed topic its Kafka engine table reads.
    #[envconfig(
        from = "USAGE_INGESTION_TOPIC",
        default = "clickhouse_billing_usage_records"
    )]
    pub topic: String,
    /// Maximum age of a gRPC connection in seconds before the server sends GOAWAY.
    /// Producers reconnect transparently, which restaggers them across the pods.
    /// 0 = disabled (connections live indefinitely).
    /// Shorter than personhog's 300 because a producer holds one connection and this fleet
    /// runs near its CPU request when the load lands unevenly.
    #[envconfig(from = "USAGE_INGESTION_GRPC_MAX_CONNECTION_AGE_SECS", default = "60")]
    pub grpc_max_connection_age_secs: u64,
}

impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if self.max_batch_size == 0 || self.max_batch_size > 5_000 {
            return Err("USAGE_INGESTION_MAX_BATCH_SIZE must be between 1 and 5000".to_string());
        }
        if self.redis_flush_interval_seconds == 0 {
            return Err(
                "USAGE_INGESTION_REDIS_FLUSH_INTERVAL_SECONDS must be positive".to_string(),
            );
        }
        if self.redis_connections == 0 {
            return Err("USAGE_INGESTION_REDIS_CONNECTIONS must be positive".to_string());
        }
        if self.redis_flush_concurrency == 0 {
            return Err("USAGE_INGESTION_REDIS_FLUSH_CONCURRENCY must be positive".to_string());
        }
        if self.kafka_consumer_batch_size == 0 {
            return Err("USAGE_INGESTION_KAFKA_CONSUMER_BATCH_SIZE must be positive".to_string());
        }
        if self.kafka_consumer_batch_timeout_ms == 0 {
            return Err(
                "USAGE_INGESTION_KAFKA_CONSUMER_BATCH_TIMEOUT_MS must be positive".to_string(),
            );
        }
        if self.kafka_consumer_concurrency == 0 {
            return Err("USAGE_INGESTION_KAFKA_CONSUMER_CONCURRENCY must be positive".to_string());
        }
        if self.kafka_consumer_retry_backoff_max_ms == 0 {
            return Err(
                "USAGE_INGESTION_KAFKA_CONSUMER_RETRY_BACKOFF_MAX_MS must be positive".to_string(),
            );
        }
        if self.kafka_dead_letter_message_timeout_ms == 0 {
            return Err(
                "USAGE_INGESTION_KAFKA_DEAD_LETTER_MESSAGE_TIMEOUT_MS must be positive".to_string(),
            );
        }
        // A few seconds would make every producer spend its time reconnecting.
        if self.grpc_max_connection_age_secs > 0 && self.grpc_max_connection_age_secs < 10 {
            return Err(
                "USAGE_INGESTION_GRPC_MAX_CONNECTION_AGE_SECS must be 0 or at least 10".to_string(),
            );
        }
        Ok(())
    }

    pub fn redis_counter_config(&self) -> CounterConfig {
        CounterConfig {
            connections: self.redis_connections,
            flush_concurrency: self.redis_flush_concurrency,
        }
    }

    pub fn grpc_max_connection_age(&self) -> Option<Duration> {
        if self.grpc_max_connection_age_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.grpc_max_connection_age_secs))
        }
    }

    /// A setting dropped from here reverts to a `KafkaConfig` default instead of failing.
    pub fn kafka_config(&self) -> KafkaConfig {
        KafkaConfig {
            kafka_hosts: self.kafka_hosts.clone(),
            kafka_tls: self.kafka_tls,
            kafka_client_id: "usage-ingestion".to_string(),
            kafka_compression_codec: self.kafka_compression_codec.clone(),
            kafka_producer_linger_ms: self.kafka_producer_linger_ms,
            kafka_producer_batch_size: Some(BATCH_SIZE),
            kafka_producer_batch_num_messages: Some(BATCH_NUM_MESSAGES),
            kafka_producer_message_max_bytes: Some(MESSAGE_MAX_BYTES),
            kafka_producer_max_in_flight_requests_per_connection: Some(
                MAX_IN_FLIGHT_PER_CONNECTION,
            ),
            kafka_producer_topic_metadata_refresh_interval_ms: Some(METADATA_REFRESH_INTERVAL_MS),
            // WarpStream serves a different agent per connection, which collapses throughput
            // when librdkafka pins an idempotent producer's sequence numbers to one.
            kafka_producer_enable_idempotence: Some(false),
            // acks and the partitioner stay at librdkafka's defaults, which match WarpStream's
            // advice: acks=all keeps a billing record durable, and these records carry no key.
            ..Default::default()
        }
    }

    pub fn kafka_consumer_config(&self) -> ClientConfig {
        let hosts = if self.kafka_input_hosts.is_empty() {
            &self.kafka_hosts
        } else {
            &self.kafka_input_hosts
        };
        ConsumerConfigBuilder::for_batch_consumer(hosts, &self.kafka_consumer_group)
            .with_tls(self.kafka_input_tls.unwrap_or(self.kafka_tls))
            .with_offset_reset("earliest")
            .with_sticky_partition_assignment(None, false)
            .with_topic_metadata_refresh_interval_ms(
                self.kafka_consumer_topic_metadata_refresh_interval_ms,
            )
            .with_fetch_max_bytes(self.kafka_consumer_fetch_max_bytes)
            .with_max_partition_fetch_bytes(self.kafka_consumer_max_partition_fetch_bytes)
            .with_fetch_wait_max_ms(self.kafka_consumer_fetch_wait_max_ms)
            .set("client.id", &self.kafka_consumer_client_id)
            .set(
                "socket.send.buffer.bytes",
                &self.kafka_consumer_socket_send_buffer_bytes.to_string(),
            )
            .set(
                "socket.receive.buffer.bytes",
                &self.kafka_consumer_socket_receive_buffer_bytes.to_string(),
            )
            .set(
                "retry.backoff.max.ms",
                &self.kafka_consumer_retry_backoff_max_ms.to_string(),
            )
            .set("statistics.interval.ms", "10000")
            .set("allow.auto.create.topics", "false")
            .set(
                "message.timeout.ms",
                &self.kafka_dead_letter_message_timeout_ms.to_string(),
            )
            .build()
    }

    pub fn kafka_batch_config(&self) -> KafkaBatchConfig {
        KafkaBatchConfig {
            max_messages: self.kafka_consumer_batch_size,
            max_wait: Duration::from_millis(self.kafka_consumer_batch_timeout_ms),
            concurrency: self.kafka_consumer_concurrency,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> Config {
        Config {
            transport_mode: TransportMode::Grpc,
            grpc_address: "0.0.0.0:7143".to_string(),
            metrics_address: "0.0.0.0:7144".to_string(),
            database_url: "postgres://localhost/test".to_string(),
            kafka_hosts: "localhost:9092".to_string(),
            kafka_tls: false,
            kafka_input_hosts: String::new(),
            kafka_input_tls: None,
            kafka_input_topic: "usage_ingestion".to_string(),
            kafka_dead_letter_topic: "usage_ingestion_dlq".to_string(),
            kafka_dead_letter_message_timeout_ms: 20_000,
            kafka_consumer_group: "usage-ingestion".to_string(),
            kafka_consumer_client_id: "usage-ingestion-consumer".to_string(),
            kafka_consumer_topic_metadata_refresh_interval_ms: 60_000,
            kafka_consumer_fetch_max_bytes: 50_242_880,
            kafka_consumer_max_partition_fetch_bytes: 50_242_880,
            kafka_consumer_fetch_wait_max_ms: 10_000,
            kafka_consumer_socket_send_buffer_bytes: 0,
            kafka_consumer_socket_receive_buffer_bytes: 0,
            kafka_consumer_retry_backoff_max_ms: 60_000,
            kafka_consumer_batch_size: 100,
            kafka_consumer_batch_timeout_ms: 10,
            kafka_consumer_concurrency: 16,
            kafka_compression_codec: "lz4".to_string(),
            kafka_producer_linger_ms: 100,
            max_batch_size: 500,
            redis_url: String::new(),
            redis_flush_interval_seconds: 15,
            redis_connections: 16,
            redis_flush_concurrency: 16,
            topic: "clickhouse_billing_usage_records".to_string(),
            grpc_max_connection_age_secs: 60,
        }
    }

    #[test]
    fn both_transport_mode_parses() {
        assert_eq!("both".parse(), Ok(TransportMode::Both));
    }

    #[test]
    fn the_producer_follows_the_warpstream_recommendations() {
        let kafka = config().kafka_config();

        assert_eq!(kafka.kafka_compression_codec, "lz4");
        assert_eq!(kafka.kafka_producer_linger_ms, 100);
        assert_eq!(kafka.kafka_producer_batch_size, Some(BATCH_SIZE));
        assert_eq!(
            kafka.kafka_producer_batch_num_messages,
            Some(BATCH_NUM_MESSAGES)
        );
        assert_eq!(
            kafka.kafka_producer_message_max_bytes,
            Some(MESSAGE_MAX_BYTES)
        );
        assert_eq!(
            kafka.kafka_producer_max_in_flight_requests_per_connection,
            Some(MAX_IN_FLIGHT_PER_CONNECTION)
        );
        assert_eq!(
            kafka.kafka_producer_topic_metadata_refresh_interval_ms,
            Some(METADATA_REFRESH_INTERVAL_MS)
        );
        assert_eq!(kafka.kafka_producer_enable_idempotence, Some(false));
    }

    #[test]
    fn the_environment_overrides_compression_and_linger() {
        let config = Config {
            kafka_compression_codec: "none".to_string(),
            kafka_producer_linger_ms: 5,
            ..config()
        };

        let kafka = config.kafka_config();

        assert_eq!(kafka.kafka_compression_codec, "none");
        assert_eq!(kafka.kafka_producer_linger_ms, 5);
    }

    #[test]
    fn the_input_consumer_can_use_a_different_cluster() {
        let config = Config {
            kafka_input_hosts: "ingestion:9092".to_string(),
            kafka_input_tls: Some(true),
            ..config()
        };

        let kafka = config.kafka_consumer_config();

        assert_eq!(kafka.get("metadata.broker.list"), Some("ingestion:9092"));
        assert_eq!(kafka.get("security.protocol"), Some("ssl"));
        assert_eq!(kafka.get("enable.auto.commit"), Some("false"));
        assert_eq!(
            kafka.get("partition.assignment.strategy"),
            Some("cooperative-sticky")
        );
        assert_eq!(kafka.get("client.id"), Some("usage-ingestion-consumer"));
        assert_eq!(
            kafka.get("topic.metadata.refresh.interval.ms"),
            Some("60000")
        );
        assert_eq!(kafka.get("fetch.max.bytes"), Some("50242880"));
        assert_eq!(kafka.get("max.partition.fetch.bytes"), Some("50242880"));
        assert_eq!(kafka.get("fetch.wait.max.ms"), Some("10000"));
        assert_eq!(kafka.get("socket.send.buffer.bytes"), Some("0"));
        assert_eq!(kafka.get("socket.receive.buffer.bytes"), Some("0"));
        assert_eq!(kafka.get("retry.backoff.max.ms"), Some("60000"));
        assert_eq!(kafka.get("statistics.interval.ms"), Some("10000"));
        assert_eq!(kafka.get("allow.auto.create.topics"), Some("false"));
        assert_eq!(kafka.get("message.timeout.ms"), Some("20000"));

        let batch = config.kafka_batch_config();
        assert_eq!(batch.max_messages, 100);
        assert_eq!(batch.max_wait, Duration::from_millis(10));
        assert_eq!(batch.concurrency, 16);
    }

    #[test]
    fn configuration_requires_positive_values() {
        for (config, expected) in [
            (
                Config {
                    redis_connections: 0,
                    ..config()
                },
                "USAGE_INGESTION_REDIS_CONNECTIONS must be positive",
            ),
            (
                Config {
                    redis_flush_concurrency: 0,
                    ..config()
                },
                "USAGE_INGESTION_REDIS_FLUSH_CONCURRENCY must be positive",
            ),
            (
                Config {
                    kafka_dead_letter_message_timeout_ms: 0,
                    ..config()
                },
                "USAGE_INGESTION_KAFKA_DEAD_LETTER_MESSAGE_TIMEOUT_MS must be positive",
            ),
        ] {
            assert_eq!(config.validate(), Err(expected.to_string()));
        }
    }
}
