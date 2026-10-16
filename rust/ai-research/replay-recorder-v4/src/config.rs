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

    /// A flush attempt that takes longer fails. The consumer does not poll Kafka during a flush, so all attempts
    /// together stay under the poll interval and the group keeps the partitions while they run.
    #[envconfig(default = "60")]
    pub flush_timeout_secs: u64,

    /// How often a failed flush is tried again in-process before the recorder exits.
    #[envconfig(default = "3")]
    pub flush_retries: u32,

    /// On shutdown the buffer is flushed if that takes at most this long. Otherwise nothing is committed.
    #[envconfig(default = "20")]
    pub shutdown_flush_secs: u64,

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

    /// A fetch job not delivered in this time fails its flush. It is well under the flush timeout.
    #[envconfig(default = "20000")]
    pub image_fetch_delivery_timeout_ms: u32,

    #[envconfig(default = "9104")]
    pub metrics_port: u16,
}

/// The consumer's `max.poll.interval.ms`.
pub const MAX_POLL_INTERVAL: Duration = Duration::from_secs(300);

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

    /// Catches settings that would otherwise fail at the first flush and crash loop.
    pub fn validate(&self) -> Result<(), String> {
        if !(0.0..=100.0).contains(&self.sample_percentage) {
            return Err(format!(
                "SESSION_RECORDING_ML_V4_SAMPLE_PERCENTAGE must be from 0 to 100, not {}",
                self.sample_percentage
            ));
        }
        let mut required = vec![
            ("KAFKA_TOPIC", &self.kafka_topic),
            (
                "EVENT_RESTRICTIONS_REDIS_URL",
                &self.event_restrictions_redis_url,
            ),
            (
                "SESSION_RECORDING_REDIS_URL",
                &self.session_recording_redis_url,
            ),
        ];
        if self.write_enabled {
            required.extend([
                ("AI_RESEARCH_REPLAY_V4_KEY_TABLE", &self.key_table),
                ("AI_RESEARCH_REPLAY_V4_KMS_KEY_ARN", &self.kms_key_arn),
                ("AI_RESEARCH_REPLAY_V4_RRWEB_BUCKET", &self.rrweb_bucket),
                ("AI_RESEARCH_REPLAY_V4_IMAGES_BUCKET", &self.images_bucket),
                ("IMAGE_FETCH_TOPIC", &self.image_fetch_topic),
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
        if self.flush_budget() >= MAX_POLL_INTERVAL - Duration::from_secs(10) {
            return Err(format!(
                "FLUSH_TIMEOUT_SECS and FLUSH_RETRIES allow a flush of {:?}, which is not under the Kafka poll interval",
                self.flush_budget()
            ));
        }
        if self.image_fetch_delivery_timeout_ms as u64 >= self.flush_timeout_secs * 1000 {
            return Err(
                "IMAGE_FETCH_DELIVERY_TIMEOUT_MS must be under the flush timeout".to_owned(),
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
                "SESSION_RECORDING_REDIS_URL".to_owned(),
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
            ("SESSION_RECORDING_ML_V4_WRITE_ENABLED", "true"),
            ("AI_RESEARCH_REPLAY_V4_KEY_TABLE", "keys"),
            ("AI_RESEARCH_REPLAY_V4_RRWEB_BUCKET", "rrweb"),
        ])
        .validate()
        .unwrap_err();
        assert_eq!(
            error,
            "missing settings: AI_RESEARCH_REPLAY_V4_KMS_KEY_ARN, AI_RESEARCH_REPLAY_V4_IMAGES_BUCKET"
        );
        assert!(
            config(&[("SESSION_RECORDING_ML_V4_SAMPLE_PERCENTAGE", "110")])
                .validate()
                .is_err()
        );
    }
}
