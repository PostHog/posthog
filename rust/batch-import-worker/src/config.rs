use crate::job::backoff::BackoffPolicy;
use envconfig::Envconfig;

// Re-export KafkaConfig for testing
pub use common_kafka::config::KafkaConfig;

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

    // Exponential backoff defaults
    #[envconfig(from = "BACKOFF_INITIAL_SECONDS", default = "60")]
    pub backoff_initial_seconds: u64,

    #[envconfig(from = "BACKOFF_MAX_SECONDS", default = "3600")]
    pub backoff_max_seconds: u64,

    #[envconfig(from = "BACKOFF_MULTIPLIER", default = "2.0")]
    pub backoff_multiplier: f64,

    // 0 means unlimited retries
    #[envconfig(from = "BACKOFF_MAX_ATTEMPTS", default = "0")]
    pub backoff_max_attempts: u32,

    // In-memory cache configuration
    #[envconfig(from = "IDENTIFY_MEMORY_CACHE_CAPACITY", default = "1000000")]
    pub identify_memory_cache_capacity: u64,
    #[envconfig(from = "IDENTIFY_MEMORY_CACHE_TTL_SECONDS", default = "3600")]
    pub identify_memory_cache_ttl_seconds: u64,

    // Group cache configuration
    #[envconfig(from = "GROUP_MEMORY_CACHE_CAPACITY", default = "1000000")]
    pub group_memory_cache_capacity: u64,
    #[envconfig(from = "GROUP_MEMORY_CACHE_TTL_SECONDS", default = "3600")]
    pub group_memory_cache_ttl_seconds: u64,
}

impl Config {
    pub fn resolve_kafka_topic(&self, logical_topic: &str) -> Result<String, anyhow::Error> {
        match logical_topic {
            "main" => Ok(self.kafka_topic_main.clone()),
            "historical" => Ok(self.kafka_topic_historical.clone()),
            "overflow" => Ok(self.kafka_topic_overflow.clone()),
            _ => Err(anyhow::Error::msg(format!(
                "Unknown kafka topic: {logical_topic}"
            ))),
        }
    }

    pub fn backoff_policy(&self) -> BackoffPolicy {
        BackoffPolicy::new(
            std::time::Duration::from_secs(self.backoff_initial_seconds),
            self.backoff_multiplier,
            std::time::Duration::from_secs(self.backoff_max_seconds),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_resolve_kafka_topic_main() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("main").unwrap();
        assert_eq!(result, "events_plugin_ingestion");
    }

    #[test]
    fn test_resolve_kafka_topic_historical() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("historical").unwrap();
        assert_eq!(result, "events_plugin_ingestion_historical");
    }

    #[test]
    fn test_resolve_kafka_topic_overflow() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("overflow").unwrap();
        assert_eq!(result, "events_plugin_ingestion_overflow");
    }

    #[test]
    fn test_resolve_kafka_topic_unknown() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("unknown");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Unknown kafka topic: unknown"));
    }

    #[test]
    fn test_resolve_kafka_topic_empty() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Unknown kafka topic:"));
    }

    #[test]
    fn test_resolve_kafka_topic_case_sensitive() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("MAIN");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Unknown kafka topic: MAIN"));
    }

    #[test]
    fn test_backoff_policy_defaults() {
        let config = Config::init_from_env().unwrap();
        let p = config.backoff_policy();
        assert_eq!(p.initial_delay.as_secs(), 60);
        assert_eq!(p.max_delay.as_secs(), 3600);
        assert!((p.multiplier - 2.0).abs() < f64::EPSILON);
    }
}
