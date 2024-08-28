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

    // Update sets are batches into at least min_batch_size (unless we haven't sent a batch in more than a few seconds)
    #[envconfig(default = "10")]
    pub max_concurrent_transactions: usize,

    // We issue writes (UPSERTS) to postgres in batches of this size.
    // Total concurrent DB ops is max_concurrent_transactions * update_batch_size
    #[envconfig(default = "1000")]
    pub update_batch_size: usize,

    // We issue updates in batches of update_batch_size, or when we haven't
    // received a new update in this many seconds
    #[envconfig(default = "300")]
    pub max_issue_period: u64,

    // Propdefs spawns N workers to pull events from kafka,
    // marshal, and convert ot updates. The number of
    // concurrent update batches sent to postgres is controlled
    // by max_concurrent_transactions
    #[envconfig(default = "10")]
    pub worker_loop_count: usize,

    // We maintain an internal cache, to avoid sending the same UPSERT multiple times. This is it's size.
    #[envconfig(default = "100000")]
    pub cache_capacity: usize,

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
