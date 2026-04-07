use envconfig::Envconfig;
use rdkafka::ClientConfig;

use crate::kafka_config::ConsumerConfigBuilder;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    // ---- Kafka connection ----
    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    // ---- Kafka consumer ----
    #[envconfig(default = "ingestion-consumer")]
    pub kafka_consumer_group: String,

    #[envconfig(default = "events_plugin_ingestion")]
    pub kafka_consumer_topic: String,

    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    #[envconfig(default = "10485760")] // 10MB
    pub kafka_consumer_max_partition_fetch_bytes: u32,

    #[envconfig(default = "10000")] // 10 seconds
    pub kafka_topic_metadata_refresh_interval_ms: u32,

    #[envconfig(default = "30000")] // 30 seconds
    pub kafka_metadata_max_age_ms: u32,

    #[envconfig(default = "60000")] // 60 seconds
    pub kafka_session_timeout_ms: u32,

    #[envconfig(default = "5000")] // 5 seconds
    pub kafka_heartbeat_interval_ms: u32,

    #[envconfig(default = "300000")] // 5 minutes
    pub kafka_max_poll_interval_ms: u32,

    // Fetch tuning
    #[envconfig(default = "1")]
    pub kafka_consumer_fetch_min_bytes: u32,

    #[envconfig(default = "52428800")] // 50MB
    pub kafka_consumer_fetch_max_bytes: u32,

    #[envconfig(default = "500")]
    pub kafka_consumer_fetch_wait_max_ms: u32,

    #[envconfig(default = "100000")]
    pub kafka_consumer_queued_min_messages: u32,

    #[envconfig(default = "65536")] // 64MB
    pub kafka_consumer_queued_max_messages_kbytes: u32,

    /// Pod hostname from K8s, used for sticky partition assignment
    #[envconfig(from = "HOSTNAME")]
    pub pod_hostname: Option<String>,

    // ---- Batching ----
    /// Maximum number of messages to collect before dispatching a batch
    #[envconfig(default = "500")]
    pub batch_size: usize,

    /// Maximum time to wait while collecting a batch (milliseconds)
    #[envconfig(default = "100")]
    pub batch_timeout_ms: u64,

    // ---- Worker transport ----
    /// Comma-separated list of worker HTTP URLs
    #[envconfig(default = "http://localhost:9001")]
    pub worker_addresses: String,

    /// HTTP request timeout for worker calls (milliseconds)
    #[envconfig(default = "30000")]
    pub http_timeout_ms: u64,

    /// Maximum number of retries for a failed worker call
    #[envconfig(default = "3")]
    pub max_retries: u32,

    // ---- Health/metrics server ----
    #[envconfig(default = "0.0.0.0")]
    pub bind_host: String,

    #[envconfig(default = "3301")]
    pub bind_port: u16,

    #[envconfig(default = "true")]
    pub export_prometheus: bool,
}

impl Config {
    pub fn bind_address(&self) -> String {
        format!("{}:{}", self.bind_host, self.bind_port)
    }

    pub fn worker_urls(&self) -> Vec<String> {
        self.worker_addresses
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    }

    /// Build a fully-configured rdkafka ClientConfig using the ConsumerConfigBuilder.
    pub fn build_consumer_config(&self) -> ClientConfig {
        ConsumerConfigBuilder::for_batch_consumer(&self.kafka_hosts, &self.kafka_consumer_group)
            .with_tls(self.kafka_tls)
            .with_max_partition_fetch_bytes(self.kafka_consumer_max_partition_fetch_bytes)
            .with_topic_metadata_refresh_interval_ms(self.kafka_topic_metadata_refresh_interval_ms)
            .with_metadata_max_age_ms(self.kafka_metadata_max_age_ms)
            .with_sticky_partition_assignment(self.pod_hostname.as_deref())
            .with_offset_reset(&self.kafka_consumer_offset_reset)
            .with_fetch_min_bytes(self.kafka_consumer_fetch_min_bytes)
            .with_fetch_max_bytes(self.kafka_consumer_fetch_max_bytes)
            .with_fetch_wait_max_ms(self.kafka_consumer_fetch_wait_max_ms)
            .with_queued_min_messages(self.kafka_consumer_queued_min_messages)
            .with_queued_max_messages_kbytes(self.kafka_consumer_queued_max_messages_kbytes)
            .with_max_poll_interval_ms(self.kafka_max_poll_interval_ms)
            .with_session_timeout_ms(self.kafka_session_timeout_ms)
            .with_heartbeat_interval_ms(self.kafka_heartbeat_interval_ms)
            .build()
    }
}
