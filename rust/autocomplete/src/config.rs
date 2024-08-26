use envconfig::Envconfig;
use rdkafka::ClientConfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "10")]
    pub max_concurrent_transactions: usize,

    #[envconfig(default = "10000")]
    pub max_batch_size: usize,

    // If a worker recieves a batch smaller than this, it will simply not commit the offset and
    // sleep for a while, since DB ops/event scales inversely to batch size
    #[envconfig(default = "1000")]
    pub min_batch_size: usize,

    #[envconfig(default = "100")]
    pub next_event_wait_timeout_ms: u64,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3301")]
    pub port: u16,
}

#[derive(Envconfig, Clone)]
pub struct KafkaConfig {
    #[envconfig(default = "kafka:9092")]
    pub kafka_hosts: String,
    #[envconfig(default = "clickhouse_events_json")]
    pub event_topic: String,
    #[envconfig(default = "false")]
    pub kafka_tls: bool,
    #[envconfig(default = "false")]
    pub verify_ssl_certificate: bool,
    #[envconfig(default = "autocomplete-rs")]
    pub consumer_group: String,
}

impl From<&KafkaConfig> for ClientConfig {
    fn from(config: &KafkaConfig) -> Self {
        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &config.kafka_hosts)
            .set("statistics.interval.ms", "10000")
            .set("group.id", config.consumer_group.clone());

        if config.kafka_tls {
            client_config.set("security.protocol", "ssl").set(
                "enable.ssl.certificate.verification",
                config.verify_ssl_certificate.to_string(),
            );
        };
        client_config
    }
}
