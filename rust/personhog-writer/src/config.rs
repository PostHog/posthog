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

    /// Flush when a lane's buffer reaches this many entries, and cap how
    /// many rows a single flush drains: a backlogged lane empties as a
    /// sequence of batches of roughly this size (whole partitions only)
    /// instead of one giant batch. Clamped to half the per-lane capacity
    /// (`buffer_capacity / writer_lanes`) so the nonblocking size flush
    /// always fires before a lane's hard cap.
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

    /// Max concurrent upsert statements against PG, shared across all
    /// writer lanes and both the chunk and per-row paths. Keep below
    /// `pg_max_connections` so a burst of chunks queues at the semaphore
    /// (a cheap, unbounded wait) instead of timing out pool acquires.
    #[envconfig(default = "8")]
    pub upsert_concurrency: usize,

    /// Max concurrent per-row upserts when a batch falls back to the
    /// per-row path. Size against `pg_max_connections`; pgbouncer handles
    /// backpressure to PG itself.
    #[envconfig(default = "16")]
    pub row_fallback_concurrency: usize,

    /// Channel capacity between the consumer and each writer lane.
    /// Higher values allow more buffered batches but use more memory.
    #[envconfig(default = "2")]
    pub flush_channel_capacity: usize,

    /// Number of parallel writer lanes. Partitions map to lanes by
    /// `partition % writer_lanes`, and each lane flushes and commits its
    /// own partitions independently, so PG writes overlap across lanes.
    /// 1 preserves the original single-writer pipeline.
    #[envconfig(default = "1")]
    pub writer_lanes: usize,

    // ── Service ──────────────────────────────────────────────────
    #[envconfig(default = "9103")]
    pub metrics_port: u16,
}

impl Config {
    pub fn flush_interval(&self) -> Duration {
        Duration::from_millis(self.flush_interval_ms)
    }
}
