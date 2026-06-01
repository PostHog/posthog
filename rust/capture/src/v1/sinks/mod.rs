pub mod constants;
pub mod event;
pub mod kafka;
pub mod router;
pub mod sink;
pub mod types;

use std::collections::HashMap;
use std::str::FromStr;
use std::time::Duration;

use envconfig::Envconfig;

pub use event::Event;
pub use kafka::KafkaSink;
pub use router::{Router, RouterError};
pub use sink::Sink;
pub use types::{Destination, Outcome, SinkResult};

// ---------------------------------------------------------------------------
// SinkName
// ---------------------------------------------------------------------------

/// Identity of a v1 sink target. Adding a new sink requires a new variant
/// here plus its `as_str()`, `env_prefix()`, and `FromStr` arms.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SinkName {
    /// Primary MSK sink.
    Msk,
    /// Secondary MSK sink for upgrades, cutovers, or dual-writes.
    MskAlt,
    /// WarpStream sink for upgrades, cutovers, or dual-writes.
    Ws,
}

impl SinkName {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Msk => "msk",
            Self::MskAlt => "msk_alt",
            Self::Ws => "ws",
        }
    }

    pub fn env_prefix(&self) -> &'static str {
        match self {
            Self::Msk => "CAPTURE_V1_SINK_MSK_",
            Self::MskAlt => "CAPTURE_V1_SINK_MSK_ALT_",
            Self::Ws => "CAPTURE_V1_SINK_WS_",
        }
    }
}

impl FromStr for SinkName {
    type Err = anyhow::Error;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "msk" => Ok(Self::Msk),
            "msk_alt" => Ok(Self::MskAlt),
            "ws" => Ok(Self::Ws),
            other => Err(anyhow::anyhow!("unknown sink: {other}")),
        }
    }
}

impl std::fmt::Display for SinkName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

// ---------------------------------------------------------------------------
// Config (per-sink composite)
// ---------------------------------------------------------------------------

/// Composite per-sink configuration. Contains the transport-agnostic
/// produce timeout alongside transport-specific config (Kafka today,
/// S3/etc. in the future).
#[derive(Clone, Debug)]
pub struct Config {
    pub produce_timeout: Duration,
    pub kafka: kafka::config::Config,
}

impl Config {
    pub fn validate(&self) -> anyhow::Result<()> {
        let msg_timeout = Duration::from_millis(self.kafka.message_timeout_ms as u64);
        anyhow::ensure!(
            self.produce_timeout >= msg_timeout,
            "produce_timeout ({:?}) must be >= message_timeout_ms ({:?}) \
             to avoid ghost deliveries after application-level timeout",
            self.produce_timeout,
            msg_timeout,
        );
        self.kafka.validate()?;
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Sinks (loaded collection)
// ---------------------------------------------------------------------------

/// Parsed set of v1 sink configs. The first entry in the CSV is the
/// default sink for single-write mode.
pub struct Sinks {
    pub default: SinkName,
    pub configs: HashMap<SinkName, Config>,
}

impl Sinks {
    pub fn validate(&self) -> anyhow::Result<()> {
        anyhow::ensure!(!self.configs.is_empty(), "no v1 sinks configured");
        anyhow::ensure!(
            self.configs.contains_key(&self.default),
            "default sink '{}' is not present in configured sinks",
            self.default,
        );
        for (&name, cfg) in &self.configs {
            cfg.validate()
                .map_err(|e| anyhow::anyhow!("sink {}: {e}", name))?;
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Loaders
// ---------------------------------------------------------------------------

/// Production entry point: reads env vars and loads sink configs.
pub fn load_sinks(sinks_csv: &str) -> anyhow::Result<Sinks> {
    let env: HashMap<String, String> = std::env::vars().collect();
    load_sinks_from(sinks_csv, &env)
}

/// Testable core: loads sink configs from a provided env snapshot.
pub fn load_sinks_from(sinks_csv: &str, env: &HashMap<String, String>) -> anyhow::Result<Sinks> {
    let names: Vec<SinkName> = sinks_csv
        .split(',')
        .filter(|s| !s.trim().is_empty())
        .map(|s| s.parse::<SinkName>())
        .collect::<Result<_, _>>()
        .map_err(|e| anyhow::anyhow!("bad CAPTURE_V1_SINKS: {e}"))?;

    anyhow::ensure!(!names.is_empty(), "CAPTURE_V1_SINKS is empty");
    let default = names[0];

    let mut configs = HashMap::new();
    for name in names {
        let config = load_sink_config(name, env)
            .map_err(|e| anyhow::anyhow!("sink {}: {e}", name.as_str()))?;
        configs.insert(name, config);
    }
    Ok(Sinks { default, configs })
}

/// Load a single sink's config by stripping its env prefix and splitting
/// keys by the `KAFKA_` sub-prefix.
fn load_sink_config(name: SinkName, env: &HashMap<String, String>) -> anyhow::Result<Config> {
    let prefix = name.env_prefix();

    // Collect prefixes of other sinks so we can skip keys that belong to a
    // longer prefix (e.g. MSK_ALT_ keys when loading MSK_).
    let other_prefixes: Vec<&str> = [SinkName::Msk, SinkName::MskAlt, SinkName::Ws]
        .iter()
        .filter(|n| **n != name)
        .map(|n| n.env_prefix())
        .collect();

    let mut kafka_map = HashMap::new();
    let mut sink_map = HashMap::new();
    for (k, v) in env {
        if let Some(rest) = k.strip_prefix(prefix) {
            if other_prefixes.iter().any(|op| k.starts_with(op)) {
                continue;
            }
            if let Some(kafka_key) = rest.strip_prefix("KAFKA_") {
                kafka_map.insert(kafka_key.to_string(), v.clone());
            } else {
                sink_map.insert(rest.to_string(), v.clone());
            }
        }
    }

    let kafka = kafka::config::Config::init_from_hashmap(&kafka_map)
        .map_err(|e| anyhow::anyhow!("kafka config: {e}"))?;

    let produce_timeout_ms: u64 = sink_map
        .get("PRODUCE_TIMEOUT_MS")
        .map(|v| v.parse::<u64>())
        .transpose()
        .map_err(|e| anyhow::anyhow!("bad PRODUCE_TIMEOUT_MS: {e}"))?
        .unwrap_or(constants::DEFAULT_PRODUCE_TIMEOUT.as_millis() as u64);

    Ok(Config {
        produce_timeout: Duration::from_millis(produce_timeout_ms),
        kafka,
    })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::time::Duration;

    use super::*;

    /// Build a minimal valid env hashmap for a given SinkName.
    fn test_env_for(name: SinkName) -> HashMap<String, String> {
        let prefix = name.env_prefix();
        [
            (
                format!("{prefix}PRODUCE_TIMEOUT_MS"),
                constants::DEFAULT_PRODUCE_TIMEOUT.as_millis().to_string(),
            ),
            (format!("{prefix}KAFKA_HOSTS"), "localhost:9092".into()),
            (format!("{prefix}KAFKA_TOPIC_MAIN"), "events_main".into()),
            (
                format!("{prefix}KAFKA_TOPIC_HISTORICAL"),
                "events_hist".into(),
            ),
            (
                format!("{prefix}KAFKA_TOPIC_OVERFLOW"),
                "events_overflow".into(),
            ),
            (format!("{prefix}KAFKA_TOPIC_DLQ"), "events_dlq".into()),
        ]
        .into_iter()
        .collect()
    }

    // -- SinkName tests --

    #[test]
    fn parse_valid_names() {
        assert_eq!("msk".parse::<SinkName>().unwrap(), SinkName::Msk);
        assert_eq!("msk_alt".parse::<SinkName>().unwrap(), SinkName::MskAlt);
        assert_eq!("ws".parse::<SinkName>().unwrap(), SinkName::Ws);
    }

    #[test]
    fn parse_case_insensitive() {
        assert_eq!("MSK".parse::<SinkName>().unwrap(), SinkName::Msk);
        assert_eq!("Msk_Alt".parse::<SinkName>().unwrap(), SinkName::MskAlt);
        assert_eq!("WS".parse::<SinkName>().unwrap(), SinkName::Ws);
    }

    #[test]
    fn parse_unknown_name() {
        assert!("foo".parse::<SinkName>().is_err());
        assert!("warpstream".parse::<SinkName>().is_err());
    }

    #[test]
    fn parse_empty_string() {
        assert!("".parse::<SinkName>().is_err());
    }

    #[test]
    fn env_prefix_correctness() {
        assert_eq!(SinkName::Msk.env_prefix(), "CAPTURE_V1_SINK_MSK_");
        assert_eq!(SinkName::MskAlt.env_prefix(), "CAPTURE_V1_SINK_MSK_ALT_");
        assert_eq!(SinkName::Ws.env_prefix(), "CAPTURE_V1_SINK_WS_");
    }

    #[test]
    fn as_str_round_trip() {
        for name in [SinkName::Msk, SinkName::MskAlt, SinkName::Ws] {
            let parsed: SinkName = name.as_str().parse().unwrap();
            assert_eq!(parsed, name);
        }
    }

    // -- load_sink_config tests --

    #[test]
    fn two_pass_split_routes_kafka_keys() {
        let env = test_env_for(SinkName::Msk);
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        assert_eq!(cfg.kafka.hosts, "localhost:9092");
        assert_eq!(cfg.produce_timeout, constants::DEFAULT_PRODUCE_TIMEOUT);
    }

    #[test]
    fn produce_timeout_default() {
        let mut env = test_env_for(SinkName::Msk);
        env.remove("CAPTURE_V1_SINK_MSK_PRODUCE_TIMEOUT_MS");
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        assert_eq!(cfg.produce_timeout, constants::DEFAULT_PRODUCE_TIMEOUT);
    }

    #[test]
    fn produce_timeout_custom() {
        let mut env = test_env_for(SinkName::Msk);
        env.insert(
            "CAPTURE_V1_SINK_MSK_PRODUCE_TIMEOUT_MS".into(),
            "45000".into(),
        );
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        assert_eq!(cfg.produce_timeout, Duration::from_millis(45000));
    }

    #[test]
    fn produce_timeout_invalid() {
        let mut env = test_env_for(SinkName::Msk);
        env.insert(
            "CAPTURE_V1_SINK_MSK_PRODUCE_TIMEOUT_MS".into(),
            "abc".into(),
        );
        assert!(load_sink_config(SinkName::Msk, &env).is_err());
    }

    #[test]
    fn kafka_sub_prefix_stripped() {
        let mut env = test_env_for(SinkName::Msk);
        env.insert("CAPTURE_V1_SINK_MSK_KAFKA_LINGER_MS".into(), "50".into());
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        assert_eq!(cfg.kafka.linger_ms, 50);
    }

    #[test]
    fn msk_alt_keys_do_not_leak_into_msk_config() {
        let mut env = test_env_for(SinkName::Msk);
        env.insert(
            "CAPTURE_V1_SINK_MSK_ALT_KAFKA_HOSTS".into(),
            "alt-host:9092".into(),
        );
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        assert_eq!(
            cfg.kafka.hosts, "localhost:9092",
            "MSK_ALT host should not leak into MSK config"
        );
    }

    #[test]
    fn non_kafka_keys_ignored_by_kafka_config() {
        let mut env = test_env_for(SinkName::Msk);
        env.insert(
            "CAPTURE_V1_SINK_MSK_SOME_FUTURE_FIELD".into(),
            "whatever".into(),
        );
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        assert_eq!(cfg.kafka.hosts, "localhost:9092");
    }

    #[test]
    fn missing_kafka_hosts_errors() {
        let mut env = test_env_for(SinkName::Msk);
        env.remove("CAPTURE_V1_SINK_MSK_KAFKA_HOSTS");
        assert!(load_sink_config(SinkName::Msk, &env).is_err());
    }

    // -- load_sinks_from tests --

    #[test]
    fn single_sink_csv() {
        let env = test_env_for(SinkName::Msk);
        let sinks = load_sinks_from("msk", &env).unwrap();
        assert_eq!(sinks.default, SinkName::Msk);
        assert_eq!(sinks.configs.len(), 1);
        assert!(sinks.configs.contains_key(&SinkName::Msk));
    }

    #[test]
    fn multi_sink_csv() {
        let mut env = test_env_for(SinkName::Msk);
        env.extend(test_env_for(SinkName::Ws));
        let sinks = load_sinks_from("msk,ws", &env).unwrap();
        assert_eq!(sinks.default, SinkName::Msk);
        assert_eq!(sinks.configs.len(), 2);
    }

    #[test]
    fn default_is_first_entry() {
        let mut env = test_env_for(SinkName::Ws);
        env.extend(test_env_for(SinkName::Msk));
        let sinks = load_sinks_from("ws,msk", &env).unwrap();
        assert_eq!(sinks.default, SinkName::Ws);
    }

    #[test]
    fn empty_csv_errors() {
        let env = HashMap::new();
        assert!(load_sinks_from("", &env).is_err());
    }

    #[test]
    fn unknown_name_in_csv_errors() {
        let env = test_env_for(SinkName::Msk);
        assert!(load_sinks_from("msk,bogus", &env).is_err());
    }

    #[test]
    fn missing_env_for_listed_sink_errors() {
        let env = HashMap::new();
        assert!(load_sinks_from("msk", &env).is_err());
    }

    // -- validation tests --

    #[test]
    fn config_validate_ok() {
        let env = test_env_for(SinkName::Msk);
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        assert!(cfg.validate().is_ok());
    }

    #[test]
    fn config_validate_timeout_too_short() {
        let mut env = test_env_for(SinkName::Msk);
        env.insert(
            "CAPTURE_V1_SINK_MSK_PRODUCE_TIMEOUT_MS".into(),
            "15000".into(),
        );
        env.insert(
            "CAPTURE_V1_SINK_MSK_KAFKA_MESSAGE_TIMEOUT_MS".into(),
            "20000".into(),
        );
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        let err = cfg.validate().unwrap_err();
        assert!(
            err.to_string().contains("produce_timeout"),
            "expected produce_timeout in error: {err}"
        );
    }

    #[test]
    fn config_validate_empty_hosts() {
        let mut env = test_env_for(SinkName::Msk);
        env.insert("CAPTURE_V1_SINK_MSK_KAFKA_HOSTS".into(), "".into());
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        let err = cfg.validate().unwrap_err();
        assert!(
            err.to_string().contains("empty kafka hosts"),
            "expected empty hosts in error: {err}"
        );
    }

    #[test]
    fn sinks_validate_empty_map() {
        let sinks = Sinks {
            default: SinkName::Msk,
            configs: HashMap::new(),
        };
        assert!(sinks.validate().is_err());
    }

    #[test]
    fn config_validate_propagates_kafka_validation() {
        let mut env = test_env_for(SinkName::Msk);
        env.insert("CAPTURE_V1_SINK_MSK_KAFKA_QUEUE_MIB".into(), "0".into());
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        let err = cfg.validate().unwrap_err();
        assert!(
            err.to_string().contains("queue_mib"),
            "expected queue_mib in error: {err}"
        );
    }

    #[test]
    fn sinks_validate_default_not_in_configs() {
        let env = test_env_for(SinkName::Msk);
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        let sinks = Sinks {
            default: SinkName::Ws,
            configs: [(SinkName::Msk, cfg)].into_iter().collect(),
        };
        let err = sinks.validate().unwrap_err();
        assert!(
            err.to_string().contains("default sink"),
            "expected 'default sink' in error: {err}"
        );
    }

    #[test]
    fn sinks_validate_propagates_config_error() {
        let mut env = test_env_for(SinkName::Msk);
        env.insert("CAPTURE_V1_SINK_MSK_KAFKA_HOSTS".into(), "".into());
        let cfg = load_sink_config(SinkName::Msk, &env).unwrap();
        let sinks = Sinks {
            default: SinkName::Msk,
            configs: [(SinkName::Msk, cfg)].into_iter().collect(),
        };
        let err = sinks.validate().unwrap_err();
        assert!(
            err.to_string().contains("sink msk"),
            "expected sink name in error: {err}"
        );
    }
}
