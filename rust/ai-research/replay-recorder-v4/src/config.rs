use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "session_recording_snapshot_item_events")]
    pub kafka_topic: String,

    /// Capture sends replay-limited and force-overflow sessions here. Empty turns it off.
    #[envconfig(default = "session_recording_snapshot_item_overflow")]
    pub kafka_overflow_topic: String,

    /// The main replay lane's overflow mode. With `redirect`, that lane moves force-overflow messages of the main topic
    /// to the overflow topic, so v4 records them there and not twice.
    #[envconfig(from = "INGESTION_OVERFLOW_MODE", default = "disabled")]
    pub ingestion_overflow_mode: String,

    #[envconfig(default = "session-replay-recorder-v4")]
    pub kafka_consumer_group: String,

    /// A new group starts at the head of the topic: v4 records sessions from when it starts, not the backlog.
    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    /// The share of sessions v4 records, from 0 to 100. See `replay_core_v4::gate`.
    #[envconfig(from = "SESSION_RECORDING_ML_V4_SAMPLE_PERCENTAGE", default = "0")]
    pub sample_percentage: f64,

    /// The Postgres database the team list is read from. A read replica is enough.
    pub database_url: String,

    /// The Redis the event ingestion restrictions are read from, as capture and the replay lanes read them.
    pub event_restrictions_redis_url: String,

    #[envconfig(default = "30")]
    pub event_restrictions_refresh_secs: u64,

    /// The session recording Redis, where the replay lanes keep the sessions their rate limiter blocked.
    pub session_recording_redis_url: String,

    /// How often the team list refreshes. Consent changes take effect within this time, as in v3.
    #[envconfig(default = "300")]
    pub team_refresh_secs: u64,

    /// A flush every this many milliseconds. The lane is not latency-sensitive, so long flushes keep objects few.
    #[envconfig(default = "60000")]
    pub flush_interval_ms: u64,

    /// A flush once the buffered messages reach this many bytes.
    #[envconfig(default = "67108864")]
    pub flush_max_bytes: usize,

    /// How many sessions of a flush are decoded, inspected and sealed at once. 0 is one per CPU.
    #[envconfig(default = "0")]
    pub flush_concurrency: usize,

    /// A session's inspector is dropped after this long without a message, so memory follows live sessions.
    #[envconfig(default = "3600")]
    pub session_idle_secs: u64,

    /// Off, the recorder reads, admits and inspects, and stores nothing: no keys, no objects.
    #[envconfig(from = "SESSION_RECORDING_ML_V4_WRITE_ENABLED", default = "false")]
    pub write_enabled: bool,

    /// Resource names come from the deployment, as the v3 mirror's do.
    #[envconfig(from = "AI_RESEARCH_REPLAY_V4_KEY_TABLE", default = "")]
    pub key_table: String,

    #[envconfig(from = "AI_RESEARCH_REPLAY_V4_KMS_KEY_ARN", default = "")]
    pub kms_key_arn: String,

    #[envconfig(from = "AI_RESEARCH_REPLAY_V4_RRWEB_BUCKET", default = "")]
    pub rrweb_bucket: String,

    #[envconfig(from = "AI_RESEARCH_REPLAY_V4_IMAGES_BUCKET", default = "")]
    pub images_bucket: String,

    /// Where remote image URLs go for the v4 image fetcher.
    #[envconfig(default = "session_replay_image_fetch_v4")]
    pub image_fetch_topic: String,

    /// A fetch job not delivered in this time fails its flush.
    #[envconfig(default = "20000")]
    pub image_fetch_delivery_timeout_ms: u32,

    #[envconfig(default = "9104")]
    pub metrics_port: u16,
}
