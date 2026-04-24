use envconfig::Envconfig;

use crate::v1::sinks::types::Destination;

/// Per-sink Kafka producer configuration. Loaded via `Envconfig::init_from_hashmap`
/// from env vars under the `KAFKA_` sub-prefix of a sink's env namespace.
///
/// For example, for sink "msk" the env var `CAPTURE_V1_SINK_MSK_KAFKA_HOSTS`
/// is stripped to key `HOSTS` in the hashmap fed to this struct.
#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    // -- Connection --
    /// Comma-separated broker list (e.g. "broker1:9092,broker2:9092").
    pub hosts: String,
    #[envconfig(default = "false")]
    pub tls: bool,
    #[envconfig(default = "")]
    pub client_id: String,

    // -- Producer tuning (maps to librdkafka settings) --
    #[envconfig(default = "20")]
    pub linger_ms: u32,
    /// In-memory producer queue size in MiB (converted to KB for rdkafka).
    #[envconfig(default = "400")]
    pub queue_mib: u32,
    /// Time before we stop retrying producing a message (ms).
    /// Allows ~6 retry cycles at 5s socket timeout.
    #[envconfig(default = "30000")]
    pub message_timeout_ms: u32,
    #[envconfig(default = "1000000")]
    pub message_max_bytes: u32,
    /// none, gzip, snappy, lz4, zstd
    #[envconfig(default = "lz4")]
    pub compression_codec: String,
    #[envconfig(default = "all")]
    pub acks: String,
    #[envconfig(default = "false")]
    pub enable_idempotence: bool,
    #[envconfig(default = "10000")]
    pub batch_num_messages: u32,
    #[envconfig(default = "1000000")]
    pub batch_size: u32,
    /// How often librdkafka refreshes topic metadata from brokers (ms).
    /// Low value ensures fast leader discovery on broker failover.
    #[envconfig(default = "5000")]
    pub metadata_refresh_interval_ms: u32,
    /// Max age of cached metadata before forced refresh (ms). Should be
    /// `>= 3x` metadata_refresh_interval_ms. Keeping this low ensures
    /// stale broker state is flushed promptly after recovery.
    #[envconfig(default = "15000")]
    pub metadata_max_age_ms: u32,
    /// Timeout for socket operations (ms). Lower = faster dead broker detection.
    #[envconfig(default = "5000")]
    pub socket_timeout_ms: u32,
    /// How often librdkafka fires the stats callback (ms). Controls the
    /// refresh cadence for broker health, queue depth, and RTT gauges.
    #[envconfig(default = "10000")]
    pub statistics_interval_ms: u32,

    // -- QueueFull backpressure --
    /// Max enqueue retry attempts when rdkafka returns QueueFull.
    /// 0 = no retries (immediate failure, pre-backpressure behavior).
    #[envconfig(default = "3")]
    pub enqueue_retry_max: u32,
    /// Pause between QueueFull retry attempts (ms). Gives rdkafka's
    /// background poller time to drain in-flight deliveries.
    #[envconfig(default = "33")]
    pub enqueue_poll_ms: u32,

    // -- Topics (all required -- envconfig errors if any are missing) --
    pub topic_main: String,
    pub topic_historical: String,
    pub topic_overflow: String,
    pub topic_dlq: String,
}

const VALID_ACKS: &[&str] = &["0", "1", "-1", "all"];
const VALID_COMPRESSION: &[&str] = &["none", "gzip", "snappy", "lz4", "zstd"];

impl Config {
    /// Validate kafka-specific configuration invariants that would otherwise
    /// blow up at rdkafka producer creation or silently break runtime health.
    pub fn validate(&self) -> anyhow::Result<()> {
        anyhow::ensure!(!self.hosts.is_empty(), "empty kafka hosts");

        anyhow::ensure!(
            self.queue_mib > 0,
            "queue_mib must be > 0 (got 0, which makes the producer queue zero-size)"
        );

        anyhow::ensure!(
            VALID_ACKS.contains(&self.acks.as_str()),
            "acks must be one of {VALID_ACKS:?} (got {:?})",
            self.acks
        );

        anyhow::ensure!(
            VALID_COMPRESSION.contains(&self.compression_codec.as_str()),
            "compression_codec must be one of {VALID_COMPRESSION:?} (got {:?})",
            self.compression_codec
        );

        anyhow::ensure!(
            self.statistics_interval_ms > 0,
            "statistics_interval_ms must be > 0 (0 disables stats callback, breaking health heartbeat)"
        );

        anyhow::ensure!(
            self.metadata_max_age_ms >= self.metadata_refresh_interval_ms * 3,
            "metadata_max_age_ms ({}) should be >= 3x metadata_refresh_interval_ms ({}) \
             for reliable metadata refresh after broker failover",
            self.metadata_max_age_ms,
            self.metadata_refresh_interval_ms
        );

        Ok(())
    }

    /// Resolve which topic to use for the given destination on this sink.
    pub fn topic_for<'a>(&'a self, dest: &'a Destination) -> Option<&'a str> {
        match dest {
            Destination::AnalyticsMain => Some(&self.topic_main),
            Destination::AnalyticsHistorical => Some(&self.topic_historical),
            Destination::Overflow => Some(&self.topic_overflow),
            Destination::Dlq => Some(&self.topic_dlq),
            Destination::Custom(t) => Some(t.as_str()),
            Destination::Drop => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use envconfig::Envconfig;

    use super::Config;

    fn required_kafka_env() -> HashMap<String, String> {
        [
            ("HOSTS", "localhost:9092"),
            ("TOPIC_MAIN", "events_main"),
            ("TOPIC_HISTORICAL", "events_hist"),
            ("TOPIC_OVERFLOW", "events_overflow"),
            ("TOPIC_DLQ", "events_dlq"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
    }

    #[test]
    fn all_fields_from_hashmap() {
        let mut env = required_kafka_env();
        env.insert("TLS".into(), "true".into());
        env.insert("CLIENT_ID".into(), "my-client".into());
        env.insert("LINGER_MS".into(), "50".into());
        env.insert("QUEUE_MIB".into(), "800".into());
        env.insert("MESSAGE_TIMEOUT_MS".into(), "30000".into());
        env.insert("MESSAGE_MAX_BYTES".into(), "2000000".into());
        env.insert("COMPRESSION_CODEC".into(), "lz4".into());
        env.insert("ACKS".into(), "1".into());
        env.insert("ENABLE_IDEMPOTENCE".into(), "true".into());
        env.insert("BATCH_NUM_MESSAGES".into(), "5000".into());
        env.insert("BATCH_SIZE".into(), "500000".into());
        env.insert("METADATA_REFRESH_INTERVAL_MS".into(), "10000".into());
        env.insert("METADATA_MAX_AGE_MS".into(), "30000".into());
        env.insert("SOCKET_TIMEOUT_MS".into(), "30000".into());
        env.insert("STATISTICS_INTERVAL_MS".into(), "5000".into());
        env.insert("ENQUEUE_RETRY_MAX".into(), "5".into());
        env.insert("ENQUEUE_POLL_MS".into(), "50".into());

        let cfg = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(cfg.hosts, "localhost:9092");
        assert!(cfg.tls);
        assert_eq!(cfg.client_id, "my-client");
        assert_eq!(cfg.linger_ms, 50);
        assert_eq!(cfg.queue_mib, 800);
        assert_eq!(cfg.message_timeout_ms, 30000);
        assert_eq!(cfg.message_max_bytes, 2000000);
        assert_eq!(cfg.compression_codec, "lz4");
        assert_eq!(cfg.acks, "1");
        assert!(cfg.enable_idempotence);
        assert_eq!(cfg.batch_num_messages, 5000);
        assert_eq!(cfg.batch_size, 500000);
        assert_eq!(cfg.metadata_refresh_interval_ms, 10000);
        assert_eq!(cfg.metadata_max_age_ms, 30000);
        assert_eq!(cfg.socket_timeout_ms, 30000);
        assert_eq!(cfg.statistics_interval_ms, 5000);
        assert_eq!(cfg.enqueue_retry_max, 5);
        assert_eq!(cfg.enqueue_poll_ms, 50);
        assert_eq!(cfg.topic_main, "events_main");
    }

    #[test]
    fn defaults_applied() {
        let env = required_kafka_env();
        let cfg = Config::init_from_hashmap(&env).unwrap();
        assert!(!cfg.tls);
        assert_eq!(cfg.client_id, "");
        assert_eq!(cfg.linger_ms, 20);
        assert_eq!(cfg.queue_mib, 400);
        assert_eq!(cfg.message_timeout_ms, 30000);
        assert_eq!(cfg.message_max_bytes, 1000000);
        assert_eq!(cfg.compression_codec, "lz4");
        assert_eq!(cfg.acks, "all");
        assert!(!cfg.enable_idempotence);
        assert_eq!(cfg.batch_num_messages, 10000);
        assert_eq!(cfg.batch_size, 1000000);
        assert_eq!(cfg.metadata_refresh_interval_ms, 5000);
        assert_eq!(cfg.metadata_max_age_ms, 15000);
        assert_eq!(cfg.socket_timeout_ms, 5000);
        assert_eq!(cfg.statistics_interval_ms, 10000);
        assert_eq!(cfg.enqueue_retry_max, 3);
        assert_eq!(cfg.enqueue_poll_ms, 33);
    }

    #[test]
    fn missing_required_hosts() {
        let mut env = required_kafka_env();
        env.remove("HOSTS");
        assert!(Config::init_from_hashmap(&env).is_err());
    }

    #[test]
    fn missing_required_topic() {
        let mut env = required_kafka_env();
        env.remove("TOPIC_MAIN");
        assert!(Config::init_from_hashmap(&env).is_err());
    }

    #[test]
    fn numeric_field_parsing_error() {
        let mut env = required_kafka_env();
        env.insert("LINGER_MS".into(), "not_a_number".into());
        assert!(Config::init_from_hashmap(&env).is_err());
    }

    // -- validate() tests --

    type Mutator = (&'static str, fn(&mut Config));

    fn valid_config() -> Config {
        Config::init_from_hashmap(&required_kafka_env()).unwrap()
    }

    #[test]
    fn validate_accepts_defaults() {
        assert!(valid_config().validate().is_ok());
    }

    #[test]
    fn validate_rejects_bad_configs() {
        let cases: &[Mutator] = &[
            ("empty_hosts", |c| c.hosts = "".into()),
            ("queue_mib_zero", |c| c.queue_mib = 0),
            ("acks_garbage", |c| c.acks = "banana".into()),
            ("compression_garbage", |c| {
                c.compression_codec = "brotli".into()
            }),
            ("stats_interval_zero", |c| c.statistics_interval_ms = 0),
            ("metadata_age_too_low", |c| {
                c.metadata_refresh_interval_ms = 5000;
                c.metadata_max_age_ms = 10000;
            }),
        ];

        for (label, mutate) in cases {
            let mut cfg = valid_config();
            mutate(&mut cfg);
            assert!(
                cfg.validate().is_err(),
                "case '{label}' should fail validation"
            );
        }
    }

    #[test]
    fn validate_accepts_valid_acks_values() {
        for acks in ["0", "1", "-1", "all"] {
            let mut cfg = valid_config();
            cfg.acks = acks.to_string();
            assert!(cfg.validate().is_ok(), "acks={acks} should be valid");
        }
    }

    #[test]
    fn validate_accepts_all_compression_codecs() {
        for codec in ["none", "gzip", "snappy", "lz4", "zstd"] {
            let mut cfg = valid_config();
            cfg.compression_codec = codec.to_string();
            assert!(cfg.validate().is_ok(), "codec={codec} should be valid");
        }
    }

    #[test]
    fn validate_metadata_age_boundary() {
        let mut cfg = valid_config();
        cfg.metadata_refresh_interval_ms = 5000;

        cfg.metadata_max_age_ms = 14999;
        assert!(cfg.validate().is_err(), "just under 3x should fail");

        cfg.metadata_max_age_ms = 15000;
        assert!(cfg.validate().is_ok(), "exactly 3x should pass");
    }
}
