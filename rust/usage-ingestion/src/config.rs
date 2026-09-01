use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

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
    // These records are small JSON objects that repeat their keys, so they compress well, and
    // WarpStream bills on what it stores. `KafkaConfig` defaults this to "none", and the service
    // builds that struct in code rather than from the environment, so the default has to be set
    // here or nothing an operator does turns compression on.
    //
    // Only "none", "gzip", "snappy" and "lz4" work. "zstd" needs the rdkafka `zstd` feature,
    // which the workspace does not enable, so librdkafka refuses it when it builds the producer.
    #[envconfig(from = "KAFKA_COMPRESSION_CODEC", default = "lz4")]
    pub kafka_compression_codec: String,
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

    /// `KafkaConfig` defaults every field this does not name, so a setting dropped from here
    /// silently reverts to that default rather than failing. Compression already regressed
    /// that way once, unnoticed until WarpStream reported uncompressed produce requests.
    pub fn kafka_config(&self) -> KafkaConfig {
        KafkaConfig {
            kafka_hosts: self.kafka_hosts.clone(),
            kafka_tls: self.kafka_tls,
            kafka_client_id: "usage-ingestion".to_string(),
            kafka_compression_codec: self.kafka_compression_codec.clone(),
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
            max_batch_size: 500,
            topic: "clickhouse_billing_usage_records".to_string(),
        }
    }

    #[test]
    fn the_producer_compresses_what_it_sends() {
        // Uncompressed, WarpStream stores and bills the full JSON of every record.
        assert_eq!(config().kafka_config().kafka_compression_codec, "lz4");
    }

    #[test]
    fn an_operator_can_turn_compression_off_without_a_release() {
        let config = Config {
            kafka_compression_codec: "none".to_string(),
            ..config()
        };

        assert_eq!(config.kafka_config().kafka_compression_codec, "none");
    }
}
