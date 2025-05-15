use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;
use std::{net::SocketAddr, str::FromStr};

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:3001")]
    pub address: SocketAddr,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub read_database_url: String,

    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    #[envconfig(default = "redis://localhost:6379/")]
    pub external_link_redis_url: String,

    #[envconfig(default = "redis://localhost:6379/")]
    pub internal_link_redis_url: String,

    #[envconfig(default = "86400")] // 1 day
    pub redis_internal_ttl_seconds: u64,

    #[envconfig(default = "phog.gg")]
    pub default_domain_for_public_store: String,

    #[envconfig(default = "false")]
    pub enable_metrics: bool,

    #[envconfig(default = "clickhouse_events_json")]
    pub events_topic: String,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,
}

impl Default for Config {
    fn default() -> Self {
        Config::init_from_env().expect("Failed to load config from env or defaults")
    }
}

impl Config {
    pub fn default_for_test() -> Self {
        Config {
            address: SocketAddr::from_str("127.0.0.1:0").unwrap(),
            read_database_url: "postgres://posthog:posthog@localhost:5432/test_posthog".to_string(),
            max_pg_connections: 10,
            external_link_redis_url: "redis://localhost:6379/".to_string(),
            internal_link_redis_url: "redis://localhost:6379/".to_string(),
            redis_internal_ttl_seconds: 86400,
            events_topic: "clickhouse_events_json".to_string(),
            kafka: KafkaConfig {
                kafka_producer_linger_ms: 0,
                kafka_producer_queue_mib: 50,
                kafka_message_timeout_ms: 5000,
                kafka_compression_codec: "none".to_string(),
                kafka_hosts: "kafka:9092".to_string(),
                kafka_tls: false,
                kafka_producer_queue_messages: 1000,
            },
            default_domain_for_public_store: "phog.gg".to_string(),
            enable_metrics: false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::SocketAddr;
    use std::str::FromStr;

    #[test]
    fn test_default_config() {
        let config = Config::init_from_env().unwrap();
        assert_eq!(
            config.address,
            SocketAddr::from_str("127.0.0.1:3001").unwrap()
        );
        assert_eq!(
            config.read_database_url,
            "postgres://posthog:posthog@localhost:5432/posthog"
        );
        assert_eq!(config.external_link_redis_url, "redis://localhost:6379/");
        assert_eq!(config.internal_link_redis_url, "redis://localhost:6379/");
        assert_eq!(config.max_pg_connections, 10);
        assert_eq!(config.redis_internal_ttl_seconds, 86400);
        assert_eq!(config.default_domain_for_public_store, "phog.gg");
        assert!(!config.enable_metrics);
    }
}
