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

    // We issue writes (UPSERTS) to postgres in batches of this size.
    // Total concurrent DB ops is max_concurrent_transactions * update_batch_size
    #[envconfig(default = "1000")]
    pub update_batch_size: usize,

    // We issue updates in batches of update_batch_size, or when we haven't
    // received a new update in this many seconds
    #[envconfig(default = "300")]
    pub max_issue_period: u64,

    // Propdefs spawns N workers to pull events from kafka,
    // marshal, and convert to updates. The number of
    // concurrent update batches sent to postgres is controlled
    // by max_concurrent_transactions
    #[envconfig(default = "4")]
    pub worker_loop_count: usize,

    // We maintain an internal cache, to avoid sending the same UPSERT multiple times. This is it's size.
    #[envconfig(default = "1000000")]
    pub cache_capacity: usize,

    // Each worker maintains a small local batch of updates, which it
    // flushes to the main thread (updating/filtering by the
    // cross-thread cache while it does). This is that batch size.
    #[envconfig(default = "10000")]
    pub compaction_batch_size: usize,

    // Workers send updates back to the main thread over a channel,
    // which has a depth of this many slots. If the main thread slows,
    // which usually means if postgres is slow, the workers will block
    // after filling this channel.
    #[envconfig(default = "1000")]
    pub channel_slots_per_worker: usize,

    // If an event has some ridiculous number of updates, we skip it
    #[envconfig(default = "10000")]
    pub update_count_skip_threshold: usize,

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
    #[envconfig(default = "property-definitions-rs")]
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
