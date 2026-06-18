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

    #[envconfig(default = "20")]
    pub pg_max_connections: u32,

    /// Target table for person upserts. Set to "posthog_person" for
    /// production cutover, "personhog_person_tmp" for validation.
    #[envconfig(default = "personhog_person_tmp")]
    pub pg_target_table: String,

    // ── Flush tuning ─────────────────────────────────────────────
    /// How often to flush the buffer to Postgres, in milliseconds. Longer
    /// windows trade latency for better dedup on hot persons.
    #[envconfig(default = "30000")]
    pub flush_interval_ms: u64,

    /// Flush when the buffer reaches this many entries. Sized to produce
    /// multi-chunk batches that exercise the parallel chunk path.
    #[envconfig(default = "10000")]
    pub flush_buffer_size: usize,

    /// Hard cap on buffer entries. When full, stop consuming from
    /// Kafka until a flush completes (backpressure). ~10× flush_buffer_size
    /// worth of headroom for bursts.
    #[envconfig(default = "100000")]
    pub buffer_capacity: usize,

    /// Max rows per INSERT statement. Chunks larger than this are
    /// executed as parallel statements.
    #[envconfig(default = "5000")]
    pub upsert_batch_size: usize,

    /// Max concurrent per-row upserts when a batch falls back to the
    /// per-row path. Size against `pg_max_connections`; pgbouncer handles
    /// backpressure to PG itself.
    #[envconfig(default = "16")]
    pub row_fallback_concurrency: usize,

    /// Raw-bytes threshold for the properties field above which a person
    /// is trimmed preflight (before the batch upsert). Matches the PG
    /// `check_properties_size` constraint; trimmed persons rejoin the
    /// main batch so a single oversized row can't torpedo the whole write.
    #[envconfig(default = "655360")]
    pub properties_size_threshold: usize,

    /// Target raw-bytes size to trim oversized properties down to. Should
    /// be comfortably below `properties_size_threshold` so the trim result
    /// definitely fits the PG constraint even if JSONB encoding inflates
    /// the stored size relative to the raw JSON we trimmed.
    #[envconfig(default = "524288")]
    pub properties_trim_target: usize,

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
