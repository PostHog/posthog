use std::{collections::HashSet, num::ParseIntError, str::FromStr};

use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3310")]
    pub port: u16,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,

    #[envconfig(default = "redis://localhost:6379")]
    pub redis_url: String,

    #[envconfig(default = "http://localhost:9201")]
    pub opensearch_url: String,

    #[envconfig(default = "llm-traces")]
    pub opensearch_index_alias: String,

    #[envconfig(default = "opensearch_indexer_dlq")]
    pub opensearch_dlq_topic: String,

    // Cardinality cap for per-team metric labels. Teams outside the top-N by event volume
    // are folded into a single `team_id="other"` bucket.
    #[envconfig(default = "50")]
    pub metric_team_label_topn: usize,

    // Daily-floor sampling defaults (overridable per-team via Redis at runtime; see Stage D).
    #[envconfig(default = "10000")]
    pub default_floor: u64,

    #[envconfig(default = "0.20")]
    pub default_above_floor_rate: f64,

    // Comma-separated team IDs to drop entirely.
    #[envconfig(default = "")]
    pub deny_teams: TeamIdSet,
}

#[derive(Clone, Debug, Default)]
pub struct TeamIdSet(pub HashSet<i32>);

impl FromStr for TeamIdSet {
    type Err = ParseIntError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let mut set = HashSet::new();
        for raw in s.split(',') {
            let trimmed = raw.trim();
            if trimmed.is_empty() {
                continue;
            }
            set.insert(trimmed.parse()?);
        }
        Ok(TeamIdSet(set))
    }
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        // Default to clickhouse_events_json with a `event LIKE '$ai_*'` filter applied
        // at parse time. Stage 5 of the POC swaps this to clickhouse_ai_events_json
        // by overriding KAFKA_CONSUMER_TOPIC at deploy time — no code change needed.
        ConsumerConfig::set_defaults("opensearch-indexer", "clickhouse_events_json", true);
        Config::init_from_env()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_team_id_set() {
        let set: TeamIdSet = "1,2, 3 ,,42".parse().unwrap();
        assert_eq!(set.0, HashSet::from([1, 2, 3, 42]));
    }

    #[test]
    fn empty_team_id_set() {
        let set: TeamIdSet = "".parse().unwrap();
        assert!(set.0.is_empty());
    }
}
