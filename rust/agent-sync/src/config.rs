use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "8080")]
    pub port: u16,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(from = "KAFKA_TOPIC", default = "agent_events")]
    pub kafka_topic: String,

    #[envconfig(from = "KAFKA_CONSUMER_GROUP", default = "agent-sync")]
    pub kafka_consumer_group: String,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(from = "MAX_PG_CONNECTIONS", default = "4")]
    pub max_pg_connections: u32,

    #[envconfig(from = "CLICKHOUSE_HOST", default = "localhost")]
    pub clickhouse_host: String,

    #[envconfig(from = "CLICKHOUSE_HTTP_PORT", default = "8123")]
    pub clickhouse_http_port: u16,

    #[envconfig(from = "CLICKHOUSE_DATABASE", default = "default")]
    pub clickhouse_database: String,

    #[envconfig(from = "CLICKHOUSE_USER", default = "default")]
    pub clickhouse_user: String,

    #[envconfig(from = "CLICKHOUSE_PASSWORD", default = "")]
    pub clickhouse_password: String,

    #[envconfig(from = "AUTH_CACHE_TTL_SECS", default = "300")]
    pub auth_cache_ttl_secs: u64,

    #[envconfig(from = "AUTH_CACHE_MAX_SIZE", default = "10000")]
    pub auth_cache_max_size: usize,

    #[envconfig(from = "SSE_KEEPALIVE_SECS", default = "30")]
    pub sse_keepalive_secs: u64,

    #[envconfig(from = "MAX_LOGS_LIMIT", default = "10000")]
    pub max_logs_limit: u32,
}

impl Config {
    pub fn bind(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}

#[cfg(test)]
impl Default for Config {
    fn default() -> Self {
        use envconfig::Envconfig;
        Self {
            continuous_profiling: ContinuousProfilingConfig::default(),
            host: "::".to_string(),
            port: 8080,
            kafka: KafkaConfig::init_from_env().unwrap_or_else(|_| {
                std::env::set_var("KAFKA_HOSTS", "localhost:9092");
                KafkaConfig::init_from_env().unwrap()
            }),
            kafka_topic: "agent_events".to_string(),
            kafka_consumer_group: "agent-sync".to_string(),
            database_url: "postgres://posthog:posthog@localhost:5432/posthog".to_string(),
            max_pg_connections: 4,
            clickhouse_host: "localhost".to_string(),
            clickhouse_http_port: 8123,
            clickhouse_database: "default".to_string(),
            clickhouse_user: "default".to_string(),
            clickhouse_password: "".to_string(),
            auth_cache_ttl_secs: 300,
            auth_cache_max_size: 10000,
            sse_keepalive_secs: 30,
            max_logs_limit: 10000,
        }
    }
}
