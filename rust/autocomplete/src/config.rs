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

    #[envconfig(default = "1000")]
    pub max_batch_size: usize,

    #[envconfig(default = "100")]
    pub next_event_wait_timeout_ms: u64,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3301")]
    pub port: u16,
}

#[derive(Envconfig, Clone)]
pub struct KafkaConfig {
    #[envconfig(default = "20")]
    pub kafka_producer_linger_ms: u32, // Maximum time between producer batches during low traffic
    #[envconfig(default = "400")]
    pub kafka_producer_queue_mib: u32, // Size of the in-memory producer queue in mebibytes
    #[envconfig(default = "20000")]
    pub kafka_message_timeout_ms: u32, // Time before we stop retrying producing a message: 20 seconds
    #[envconfig(default = "none")]
    pub kafka_compression_codec: String, // none, gzip, snappy, lz4, zstd
    #[envconfig(default = "kafka:9092")]
    pub kafka_hosts: String,
    #[envconfig(default = "clickhouse_events_json")]
    pub event_topic: String,
    #[envconfig(default = "false")]
    pub kafka_tls: bool,
    #[envconfig(default = "false")]
    pub verify_ssl_certificate: bool,
    #[envconfig(default = "autocomplete-rs")]
    pub consumer_group: String
}


impl From<&KafkaConfig> for ClientConfig {
    fn from(config: &KafkaConfig) -> Self {
        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &config.kafka_hosts)
            .set("statistics.interval.ms", "10000")
            .set("group.id", config.consumer_group.clone())
            .set("enable.auto.offset.store", "false"); // We store on a per-message basis anyway right now, but this is for later if we decide to work in batches

        if config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", config.verify_ssl_certificate.to_string());
        };
        client_config
    }
}