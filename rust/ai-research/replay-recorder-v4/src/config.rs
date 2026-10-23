use std::time::Duration;

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

    /// v4's own Redis. The new-session rate limiter keeps its seen and blocked sessions there.
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

    /// A flush attempt that takes longer fails. The consumer does not poll Kafka during a flush, so all attempts
    /// together stay under the poll interval and the group keeps the partitions while they run.
    #[envconfig(from = "AI_RESEARCH_V4_FLUSH_TIMEOUT_SECS", default = "60")]
    pub flush_timeout_secs: u64,

    /// How often a failed flush is tried again in-process before the recorder exits.
    #[envconfig(from = "AI_RESEARCH_V4_FLUSH_RETRIES", default = "3")]
    pub flush_retries: u32,

    /// On shutdown the buffer is flushed if that takes at most this long. Otherwise nothing is committed.
    #[envconfig(from = "AI_RESEARCH_V4_SHUTDOWN_FLUSH_SECS", default = "20")]
    pub shutdown_flush_secs: u64,

    /// A session's inspector is dropped after this long without a message, so memory follows live sessions.
    #[envconfig(from = "AI_RESEARCH_V4_SESSION_IDLE_SECS", default = "3600")]
    pub session_idle_secs: u64,

    /// The inspector state all sessions keep between flushes. Past it the sessions seen least recently lose their DOM
    /// state. It only stops runaway growth, such as many huge pages at once, so keep it well above normal use.
    #[envconfig(
        from = "AI_RESEARCH_V4_SESSION_STATE_MAX_BYTES",
        default = "4294967296"
    )]
    pub session_state_max_bytes: usize,

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

    /// Where the block and image index rows go for the Parquet sink.
    #[envconfig(from = "AI_RESEARCH_V4_INDEX_TOPIC", default = "ai_research_v4_index")]
    pub index_topic: String,

    /// A fetch job not delivered in this time fails its flush. It is well under the flush timeout.
    #[envconfig(
        from = "AI_RESEARCH_V4_IMAGE_FETCH_DELIVERY_TIMEOUT_MS",
        default = "20000"
    )]
    pub image_fetch_delivery_timeout_ms: u32,

    /// An index row not delivered in this time is lost and counted. The flush does not wait for it, so it can be long
    /// enough to ride out a broker slowdown.
    #[envconfig(from = "AI_RESEARCH_V4_INDEX_DELIVERY_TIMEOUT_MS", default = "300000")]
    pub index_delivery_timeout_ms: u32,

    #[envconfig(default = "9104")]
    pub metrics_port: u16,
}

/// The consumer's `max.poll.interval.ms`.
pub const MAX_POLL_INTERVAL: Duration = Duration::from_secs(300);

/// A whole flush, from the first decode to the commit, ends within this time, so it never outlives the poll interval.
pub const FLUSH_DEADLINE: Duration = Duration::from_secs(MAX_POLL_INTERVAL.as_secs() - 10);

/// The slowest refill of a scaled new-session bucket: one session each 100 seconds.
const MIN_NEW_SESSION_REPLENISH_RATE: f64 = 0.01;

/// The pause before retry `attempt` of a failed flush.
pub fn retry_backoff(attempt: u32) -> Duration {
    Duration::from_secs(1 << attempt.min(5))
}

impl Config {
    /// The longest a flush can store for, over all its attempts.
    pub fn flush_budget(&self) -> Duration {
        let attempts = Duration::from_secs(self.flush_timeout_secs) * (self.flush_retries + 1);
        attempts
            + (1..=self.flush_retries)
                .map(retry_backoff)
                .sum::<Duration>()
    }

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

    /// Catches settings that would otherwise fail at the first flush and crash loop.
    pub fn validate(&self) -> Result<(), String> {
        if !(0.0..=100.0).contains(&self.sample_percentage) {
            return Err(format!(
                "AI_RESEARCH_V4_SAMPLE_PERCENTAGE must be from 0 to 100, not {}",
                self.sample_percentage
            ));
        }
        let mut required = vec![
            ("KAFKA_TOPIC", &self.kafka_topic),
            (
                "EVENT_RESTRICTIONS_REDIS_URL",
                &self.event_restrictions_redis_url,
            ),
            ("AI_RESEARCH_V4_REDIS_URL", &self.redis_url),
        ];
        if self.write_enabled {
            required.extend([
                ("AI_RESEARCH_V4_KEY_TABLE", &self.key_table),
                ("AI_RESEARCH_V4_KMS_KEY_ARN", &self.kms_key_arn),
                ("AI_RESEARCH_V4_RRWEB_BUCKET", &self.rrweb_bucket),
                ("AI_RESEARCH_V4_IMAGES_BUCKET", &self.images_bucket),
                ("AI_RESEARCH_V4_IMAGE_FETCH_TOPIC", &self.image_fetch_topic),
                ("AI_RESEARCH_V4_INDEX_TOPIC", &self.index_topic),
            ]);
        }
        let missing: Vec<&str> = required
            .into_iter()
            .filter(|(_, value)| value.trim().is_empty())
            .map(|(name, _)| name)
            .collect();
        if !missing.is_empty() {
            return Err(format!("missing settings: {}", missing.join(", ")));
        }
        for (name, value) in [
            (
                "AI_RESEARCH_V4_NEW_SESSION_BUCKET_CAPACITY",
                self.new_session_bucket_capacity,
            ),
            (
                "AI_RESEARCH_V4_NEW_SESSION_BUCKET_REPLENISH_RATE",
                self.new_session_bucket_replenish_rate,
            ),
        ] {
            if !(value.is_finite() && value >= 0.0) {
                return Err(format!("{name} must be 0 or more, not {value}"));
            }
        }
        if self.team_refresh_secs == 0 {
            return Err("AI_RESEARCH_V4_TEAM_REFRESH_SECS must be over 0".to_owned());
        }
        if self.flush_budget() >= FLUSH_DEADLINE {
            return Err(format!(
                "AI_RESEARCH_V4_FLUSH_TIMEOUT_SECS and AI_RESEARCH_V4_FLUSH_RETRIES allow a flush of {:?}, which is not under the Kafka poll interval",
                self.flush_budget()
            ));
        }
        if self.image_fetch_delivery_timeout_ms as u64 >= self.flush_timeout_secs * 1000 {
            return Err(
                "AI_RESEARCH_V4_IMAGE_FETCH_DELIVERY_TIMEOUT_MS must be under the flush timeout"
                    .to_owned(),
            );
        }
        Ok(())
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
    fn writes_need_every_resource_name_at_startup() {
        assert_eq!(config(&[]).validate(), Ok(()));
        let error = config(&[
            ("AI_RESEARCH_V4_WRITE_ENABLED", "true"),
            ("AI_RESEARCH_V4_KEY_TABLE", "keys"),
            ("AI_RESEARCH_V4_RRWEB_BUCKET", "rrweb"),
        ])
        .validate()
        .unwrap_err();
        assert_eq!(
            error,
            "missing settings: AI_RESEARCH_V4_KMS_KEY_ARN, AI_RESEARCH_V4_IMAGES_BUCKET"
        );
        assert!(config(&[("AI_RESEARCH_V4_SAMPLE_PERCENTAGE", "110")])
            .validate()
            .is_err());
        assert!(config(&[("AI_RESEARCH_V4_TEAM_REFRESH_SECS", "0")])
            .validate()
            .is_err());
        assert!(
            config(&[("AI_RESEARCH_V4_NEW_SESSION_BUCKET_CAPACITY", "-1")])
                .validate()
                .is_err()
        );
        assert_eq!(
            config(&[("AI_RESEARCH_V4_REDIS_URL", " ")]).validate(),
            Err("missing settings: AI_RESEARCH_V4_REDIS_URL".to_owned())
        );
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
