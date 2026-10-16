use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "session_recording_snapshot_item_events")]
    pub kafka_topic: String,

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

    /// How often the team list refreshes. Consent changes take effect within this time, as in v3.
    #[envconfig(default = "300")]
    pub team_refresh_secs: u64,

    /// A flush every this many milliseconds. The lane is not latency-sensitive, so long flushes keep objects few.
    #[envconfig(default = "60000")]
    pub flush_interval_ms: u64,

    /// A flush once the buffered messages reach this many bytes.
    #[envconfig(default = "67108864")]
    pub flush_max_bytes: usize,

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

    #[envconfig(default = "9104")]
    pub metrics_port: u16,
}
