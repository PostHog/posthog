use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

/// WarpStream's recommended librdkafka producer settings.
/// <https://docs.warpstream.com/warpstream/kafka/configure-kafka-client/tuning-for-performance>
const BATCH_SIZE: u32 = 16_000_000;
const BATCH_NUM_MESSAGES: u32 = 100_000;
/// librdkafka caps a produce request at this, so it has to exceed `BATCH_SIZE`.
const MESSAGE_MAX_BYTES: u32 = 64_000_000;
const MAX_IN_FLIGHT_PER_CONNECTION: u32 = 1_000_000;
const METADATA_REFRESH_INTERVAL_MS: u32 = 60_000;

const _: () = assert!(MESSAGE_MAX_BYTES > BATCH_SIZE);

#[derive(Envconfig, Clone)]
pub struct Config {
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
    // Overridable so a test environment can use the suffixed topic its Kafka engine table reads.
    #[envconfig(
        from = "USAGE_INGESTION_TOPIC",
        default = "clickhouse_billing_usage_records"
    )]
    pub topic: String,
}

impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if self.max_batch_size == 0 || self.max_batch_size > 5_000 {
            return Err("USAGE_INGESTION_MAX_BATCH_SIZE must be between 1 and 5000".to_string());
        }
        Ok(())
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
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> Config {
        Config {
            grpc_address: "0.0.0.0:7143".to_string(),
            metrics_address: "0.0.0.0:7144".to_string(),
            database_url: "postgres://localhost/test".to_string(),
            kafka_hosts: "localhost:9092".to_string(),
            kafka_tls: false,
            kafka_compression_codec: "lz4".to_string(),
            kafka_producer_linger_ms: 100,
            max_batch_size: 500,
            topic: "clickhouse_billing_usage_records".to_string(),
        }
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
}
