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

    // Bulk batching: size in bytes and max age in ms. OS recommends ~5-15MB per request;
    // we default to 5MB to keep latency tight and stay well under typical proxy buffers.
    #[envconfig(default = "5242880")]
    pub bulk_max_batch_bytes: usize,

    #[envconfig(default = "1000")]
    pub bulk_max_age_ms: u64,

    // Cardinality cap for per-team metric labels. Teams outside the top-N by event volume
    // are folded into a single `team_id="other"` bucket.
    #[envconfig(default = "50")]
    pub metric_team_label_topn: usize,

    // Daily-floor sampling defaults; overridable per-team via Redis at runtime.
    #[envconfig(default = "10000")]
    pub default_floor: u64,

    #[envconfig(default = "0.20")]
    pub default_above_floor_rate: f64,

    // Comma-separated team IDs to drop entirely.
    #[envconfig(default = "")]
    pub deny_teams: TeamIdSet,
}

#[derive(Clone, Debug, Default)]
pub struct TeamIdSet {
    pub teams: HashSet<i32>,
}

impl TeamIdSet {
    pub fn contains(&self, id: i32) -> bool {
        self.teams.contains(&id)
    }
}

impl FromStr for TeamIdSet {
    type Err = ParseIntError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let mut teams = HashSet::new();
        for raw in s.split(',') {
            let trimmed = raw.trim();
            if trimmed.is_empty() {
                continue;
            }
            teams.insert(trimmed.parse()?);
        }
        Ok(TeamIdSet { teams })
    }
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        // Defaults to clickhouse_events_json with an `event LIKE '$ai_*'` filter applied
        // at parse time. Override KAFKA_CONSUMER_TOPIC at deploy time to switch topics
        // without a code change.
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
        assert_eq!(set.teams, HashSet::from([1, 2, 3, 42]));
        assert!(set.contains(3));
        assert!(!set.contains(99));
    }

    #[test]
    fn empty_team_id_set() {
        let set: TeamIdSet = "".parse().unwrap();
        assert!(set.teams.is_empty());
    }

    #[test]
    fn whitespace_only_team_id_set() {
        let set: TeamIdSet = " , , ".parse().unwrap();
        assert!(set.teams.is_empty());
    }

    #[test]
    fn rejects_non_numeric_team_id() {
        assert!("1,abc,3".parse::<TeamIdSet>().is_err());
    }
}
