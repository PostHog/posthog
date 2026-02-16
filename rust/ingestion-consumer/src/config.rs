use envconfig::Envconfig;

pub use common_kafka::config::KafkaConfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(from = "KAFKA_TOPIC", default = "events_plugin_ingestion")]
    pub kafka_topic: String,

    #[envconfig(from = "KAFKA_GROUP_ID", default = "ingestion-consumer-rust")]
    pub kafka_group_id: String,

    #[envconfig(
        from = "INGESTION_API_ADDRESSES",
        default = "http://localhost:3400,http://localhost:3401,http://localhost:3402,http://localhost:3403"
    )]
    pub ingestion_api_addresses: String,

    #[envconfig(from = "BATCH_SIZE", default = "500")]
    pub batch_size: usize,

    #[envconfig(from = "BATCH_TIMEOUT_MS", default = "500")]
    pub batch_timeout_ms: u64,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub bind_host: String,

    #[envconfig(from = "BIND_PORT", default = "3310")]
    pub bind_port: u16,

    #[envconfig(from = "HTTP_TIMEOUT_MS", default = "30000")]
    pub http_timeout_ms: u64,

    #[envconfig(from = "MAX_RETRIES", default = "5")]
    pub max_retries: u32,
}

impl Config {
    pub fn target_addresses(&self) -> Vec<String> {
        self.ingestion_api_addresses
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_target_addresses_parsing() {
        let config = Config {
            kafka: KafkaConfig::init_from_env().unwrap(),
            kafka_topic: "test".to_string(),
            kafka_group_id: "test".to_string(),
            ingestion_api_addresses:
                "http://localhost:3400, http://localhost:3401,http://localhost:3402".to_string(),
            batch_size: 500,
            batch_timeout_ms: 500,
            bind_host: "::".to_string(),
            bind_port: 3310,
            http_timeout_ms: 30000,
            max_retries: 5,
        };

        let addrs = config.target_addresses();
        assert_eq!(addrs.len(), 3);
        assert_eq!(addrs[0], "http://localhost:3400");
        assert_eq!(addrs[1], "http://localhost:3401");
        assert_eq!(addrs[2], "http://localhost:3402");
    }

    #[test]
    fn test_empty_addresses() {
        let config = Config {
            kafka: KafkaConfig::init_from_env().unwrap(),
            kafka_topic: "test".to_string(),
            kafka_group_id: "test".to_string(),
            ingestion_api_addresses: "".to_string(),
            batch_size: 500,
            batch_timeout_ms: 500,
            bind_host: "::".to_string(),
            bind_port: 3310,
            http_timeout_ms: 30000,
            max_retries: 5,
        };

        let addrs = config.target_addresses();
        assert!(addrs.is_empty());
    }
}
