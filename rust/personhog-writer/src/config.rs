use std::time::Duration;

use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    // ── Kafka ────────────────────────────────────────────────────
    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "personhog_updates")]
    pub kafka_topic: String,

    #[envconfig(default = "personhog-writer")]
    pub kafka_consumer_group: String,

    #[envconfig(default = "earliest")]
    pub kafka_consumer_offset_reset: String,

    // ── Postgres ─────────────────────────────────────────────────
    pub database_url: String,

    #[envconfig(default = "10")]
    pub pg_max_connections: u32,

    /// Target table for person upserts. Set to "posthog_person" for
    /// production cutover, "personhog_person_tmp" for validation.
    #[envconfig(default = "personhog_person_tmp")]
    pub pg_target_table: String,

    // ── Flush tuning ─────────────────────────────────────────────
    /// How often to flush the buffer to Postgres, in milliseconds.
    #[envconfig(default = "5000")]
    pub flush_interval_ms: u64,

    /// Flush when the buffer reaches this many entries.
    #[envconfig(default = "1000")]
    pub flush_buffer_size: usize,

    /// Hard cap on buffer entries. When full, stop consuming from
    /// Kafka until a flush completes (backpressure).
    #[envconfig(default = "50000")]
    pub buffer_capacity: usize,

    /// Max rows per INSERT statement.
    #[envconfig(default = "500")]
    pub upsert_batch_size: usize,

    /// Channel capacity between consumer and writer tasks.
    /// Higher values allow more buffered batches but use more memory.
    #[envconfig(default = "8")]
    pub flush_channel_capacity: usize,

    // ── Ingestion warnings ────────────────────────────────────────
    #[envconfig(default = "client_iwarnings_ingestion")]
    pub kafka_ingestion_warnings_topic: String,

    // ── Service ──────────────────────────────────────────────────
    #[envconfig(default = "9103")]
    pub metrics_port: u16,
}

impl Config {
    pub fn flush_interval(&self) -> Duration {
        Duration::from_millis(self.flush_interval_ms)
    }
}
