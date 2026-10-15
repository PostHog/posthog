use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "session_recording_snapshot_item_events")]
    pub kafka_topic: String,

    #[envconfig(default = "ai-research-v4-recorder")]
    pub kafka_consumer_group: String,

    /// A new group starts at the head of the topic: v4 records sessions from when it starts, not the backlog.
    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    /// The share of sessions v4 records, from 0 to 100. See `replay_core_v4::gate`.
    #[envconfig(from = "AI_RESEARCH_V4_SAMPLE_PERCENTAGE", default = "0")]
    pub sample_percentage: f64,

    /// The Postgres database the team list is read from. A read replica is enough.
    pub database_url: String,

    /// How often the team list refreshes. Consent changes take effect within this time, as in v3.
    #[envconfig(from = "AI_RESEARCH_V4_TEAM_REFRESH_SECS", default = "300")]
    pub team_refresh_secs: u64,

    #[envconfig(default = "9104")]
    pub metrics_port: u16,
}
