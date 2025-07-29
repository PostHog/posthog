use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    // ~100MB
    #[envconfig(default = "100000000")]
    pub chunk_size: usize,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3301")]
    pub port: u16,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    // Rust service connect directly to postgres, not via pgbouncer, so we keep this low
    #[envconfig(default = "4")]
    pub max_pg_connections: u32,

    // Same test key as the plugin server
    #[envconfig(default = "00beef0000beef0000beef0000beef00")]
    pub encryption_keys: String, // comma separated list of fernet keys

    #[envconfig(from = "KAFKA_TOPIC_MAIN", default = "events_plugin_ingestion")]
    pub kafka_topic_main: String,

    #[envconfig(
        from = "KAFKA_TOPIC_HISTORICAL",
        default = "events_plugin_ingestion_historical"
    )]
    pub kafka_topic_historical: String,

    #[envconfig(
        from = "KAFKA_TOPIC_OVERFLOW",
        default = "events_plugin_ingestion_overflow"
    )]
    pub kafka_topic_overflow: String,
}

impl Config {
    pub fn resolve_kafka_topic(&self, logical_topic: &str) -> Result<String, anyhow::Error> {
        match logical_topic {
            "main" => Ok(self.kafka_topic_main.clone()),
            "historical" => Ok(self.kafka_topic_historical.clone()),
            "overflow" => Ok(self.kafka_topic_overflow.clone()),
            _ => Err(anyhow::Error::msg(format!(
                "Unknown kafka topic: {}",
                logical_topic
            ))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_config() -> Config {
        Config {
            chunk_size: 100000000,
            host: "::".to_string(),
            port: 3301,
            kafka: KafkaConfig {
                kafka_producer_linger_ms: 20,
                kafka_producer_queue_mib: 400,
                kafka_producer_queue_messages: 10000,
                kafka_message_timeout_ms: 10000,
                kafka_compression_codec: "none".to_string(),
                kafka_tls: false,
                kafka_hosts: "localhost:9092".to_string(),
            },
            database_url: "postgres://test".to_string(),
            max_pg_connections: 4,
            encryption_keys: "test_key".to_string(),
            kafka_topic_main: "test_main_topic".to_string(),
            kafka_topic_historical: "test_historical_topic".to_string(),
            kafka_topic_overflow: "test_overflow_topic".to_string(),
        }
    }

    #[test]
    fn test_resolve_kafka_topic_main() {
        let config = create_test_config();
        let result = config.resolve_kafka_topic("main").unwrap();
        assert_eq!(result, "test_main_topic");
    }

    #[test]
    fn test_resolve_kafka_topic_historical() {
        let config = create_test_config();
        let result = config.resolve_kafka_topic("historical").unwrap();
        assert_eq!(result, "test_historical_topic");
    }

    #[test]
    fn test_resolve_kafka_topic_overflow() {
        let config = create_test_config();
        let result = config.resolve_kafka_topic("overflow").unwrap();
        assert_eq!(result, "test_overflow_topic");
    }

    #[test]
    fn test_resolve_kafka_topic_unknown() {
        let config = create_test_config();
        let result = config.resolve_kafka_topic("unknown");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Unknown kafka topic: unknown"));
    }

    #[test]
    fn test_resolve_kafka_topic_empty() {
        let config = create_test_config();
        let result = config.resolve_kafka_topic("");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Unknown kafka topic:"));
    }

    #[test]
    fn test_resolve_kafka_topic_case_sensitive() {
        let config = create_test_config();
        let result = config.resolve_kafka_topic("MAIN");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Unknown kafka topic: MAIN"));
    }
}
