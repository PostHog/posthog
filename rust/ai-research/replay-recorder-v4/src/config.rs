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

    /// The Redis the event ingestion restrictions are read from, as capture and the replay lanes read them.
    pub event_restrictions_redis_url: String,

    #[envconfig(
        from = "AI_RESEARCH_V4_EVENT_RESTRICTIONS_REFRESH_SECS",
        default = "30"
    )]
    pub event_restrictions_refresh_secs: u64,

    /// The session recording Redis. v4's new-session rate limiter keeps its seen and blocked sessions there, under its
    /// own keys.
    #[envconfig(from = "AI_RESEARCH_V4_REDIS_URL")]
    pub redis_url: String,

    /// The new-session rate limiter's bucket per team, as in the main lane: this many new sessions at once, and this
    /// many more each second, scaled by the sample. See [`Config::new_session_bucket`].
    #[envconfig(from = "AI_RESEARCH_V4_NEW_SESSION_BUCKET_CAPACITY", default = "3000")]
    pub new_session_bucket_capacity: f64,

    #[envconfig(
        from = "AI_RESEARCH_V4_NEW_SESSION_BUCKET_REPLENISH_RATE",
        default = "300"
    )]
    pub new_session_bucket_replenish_rate: f64,

    /// Off, the limiter only counts the sessions it would block.
    #[envconfig(from = "AI_RESEARCH_V4_NEW_SESSION_BLOCKING_ENABLED", default = "true")]
    pub new_session_blocking_enabled: bool,

    /// How often the team list refreshes. Consent changes take effect within this time, as in v3.
    #[envconfig(from = "AI_RESEARCH_V4_TEAM_REFRESH_SECS", default = "300")]
    pub team_refresh_secs: u64,

    /// A flush every this many milliseconds. The lane is not latency-sensitive, so long flushes keep objects few.
    #[envconfig(from = "AI_RESEARCH_V4_FLUSH_INTERVAL_MS", default = "60000")]
    pub flush_interval_ms: u64,

    /// A flush once the buffered messages reach this many bytes.
    #[envconfig(from = "AI_RESEARCH_V4_FLUSH_MAX_BYTES", default = "67108864")]
    pub flush_max_bytes: usize,

    /// How many sessions of a flush are decoded, inspected and sealed at once. 0 is one per CPU.
    #[envconfig(from = "AI_RESEARCH_V4_FLUSH_CONCURRENCY", default = "0")]
    pub flush_concurrency: usize,

    /// A session's inspector is dropped after this long without a message, so memory follows live sessions.
    #[envconfig(from = "AI_RESEARCH_V4_SESSION_IDLE_SECS", default = "3600")]
    pub session_idle_secs: u64,

    /// Off, the recorder reads, admits and inspects, and stores nothing: no keys, no objects.
    #[envconfig(from = "AI_RESEARCH_V4_WRITE_ENABLED", default = "false")]
    pub write_enabled: bool,

    /// Resource names come from the deployment, as the v3 mirror's do.
    #[envconfig(from = "AI_RESEARCH_V4_KEY_TABLE", default = "")]
    pub key_table: String,

    #[envconfig(from = "AI_RESEARCH_V4_KMS_KEY_ARN", default = "")]
    pub kms_key_arn: String,

    #[envconfig(from = "AI_RESEARCH_V4_RRWEB_BUCKET", default = "")]
    pub rrweb_bucket: String,

    #[envconfig(from = "AI_RESEARCH_V4_IMAGES_BUCKET", default = "")]
    pub images_bucket: String,

    /// Where remote image URLs go for the v4 image fetcher.
    #[envconfig(
        from = "AI_RESEARCH_V4_IMAGE_FETCH_TOPIC",
        default = "ai_research_v4_image_fetch"
    )]
    pub image_fetch_topic: String,

    /// A fetch job not delivered in this time fails its flush.
    #[envconfig(
        from = "AI_RESEARCH_V4_IMAGE_FETCH_DELIVERY_TIMEOUT_MS",
        default = "20000"
    )]
    pub image_fetch_delivery_timeout_ms: u32,

    #[envconfig(default = "9104")]
    pub metrics_port: u16,
}

/// The slowest refill of a scaled new-session bucket: one session each 100 seconds.
const MIN_NEW_SESSION_REPLENISH_RATE: f64 = 0.01;

impl Config {
    /// The bucket v4 runs, as `(capacity, replenish rate per second)`. v4 sees only its sample of the sessions, so both
    /// scale by the sample, and a flood trips v4 at about the rate that trips the main lane.
    pub fn new_session_bucket(&self) -> (f64, f64) {
        let share = self.sample_percentage / 100.0;
        let scaled = |value: f64, floor: f64| {
            if value > 0.0 {
                (value * share).max(floor)
            } else {
                value
            }
        };
        (
            scaled(self.new_session_bucket_capacity, 1.0),
            scaled(
                self.new_session_bucket_replenish_rate,
                MIN_NEW_SESSION_REPLENISH_RATE,
            ),
        )
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    fn config(vars: &[(&str, &str)]) -> Config {
        let mut env: HashMap<String, String> = HashMap::from([
            (
                "DATABASE_URL".to_owned(),
                "postgres://localhost/posthog".to_owned(),
            ),
            (
                "EVENT_RESTRICTIONS_REDIS_URL".to_owned(),
                "redis://localhost:6379/".to_owned(),
            ),
            (
                "AI_RESEARCH_V4_REDIS_URL".to_owned(),
                "redis://localhost:6379/".to_owned(),
            ),
        ]);
        env.extend(vars.iter().map(|(k, v)| ((*k).to_owned(), (*v).to_owned())));
        Config::init_from_hashmap(&env).unwrap()
    }

    #[test]
    fn scales_the_new_session_bucket_by_the_sample() {
        let bucket = |sample: &str, capacity: &str, rate: &str| {
            config(&[
                ("AI_RESEARCH_V4_SAMPLE_PERCENTAGE", sample),
                ("AI_RESEARCH_V4_NEW_SESSION_BUCKET_CAPACITY", capacity),
                ("AI_RESEARCH_V4_NEW_SESSION_BUCKET_REPLENISH_RATE", rate),
            ])
            .new_session_bucket()
        };
        assert_eq!(bucket("100", "3000", "300"), (3000.0, 300.0));
        assert_eq!(bucket("10", "3000", "300"), (300.0, 30.0));
        assert_eq!(
            bucket("0.01", "3000", "30"),
            (1.0, MIN_NEW_SESSION_REPLENISH_RATE)
        );
        assert_eq!(bucket("10", "0", "0"), (0.0, 0.0));
    }
}
