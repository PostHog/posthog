use std::{
    collections::{HashMap, HashSet},
    num::ParseIntError,
    str::FromStr,
};

use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

use crate::sampling::TeamOverride;

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

    // Bulk batching: size in bytes and max age in ms. OS recommends ~5-15MB per request;
    // we default to 5MB to keep latency tight and stay well under typical proxy buffers.
    #[envconfig(default = "5242880")]
    pub bulk_max_batch_bytes: usize,

    #[envconfig(default = "1000")]
    pub bulk_max_age_ms: u64,

    // Daily-floor sampling defaults; overridable per-team via Redis at runtime.
    #[envconfig(default = "10000")]
    pub default_floor: u64,

    #[envconfig(default = "0.20")]
    pub default_above_floor_rate: f64,

    // Comma-separated team IDs to drop entirely.
    #[envconfig(default = "")]
    pub deny_teams: TeamIdSet,

    // JSON map of per-team overrides for floor + above-floor rate. Empty string
    // means no overrides. Format: {"42":{"floor":50000,"rate":0.5}, ...}.
    // Invalid JSON or invalid team_id key fails startup.
    #[envconfig(default = "")]
    pub team_overrides: TeamOverridesEnv,
}

#[derive(Clone, Debug, Default)]
pub struct TeamOverridesEnv {
    pub overrides: HashMap<i32, TeamOverride>,
}

#[derive(Debug, thiserror::Error)]
pub enum TeamOverridesParseError {
    #[error("invalid JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("invalid team_id key {0:?}: {1}")]
    InvalidTeamId(String, ParseIntError),
    #[error("invalid rate for team_id {0}: {1} (must be finite and within [0.0, 1.0])")]
    InvalidRate(i32, f64),
}

impl FromStr for TeamOverridesEnv {
    type Err = TeamOverridesParseError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let trimmed = s.trim();
        if trimmed.is_empty() {
            return Ok(TeamOverridesEnv::default());
        }
        let raw: HashMap<String, TeamOverride> = serde_json::from_str(trimmed)?;
        let mut overrides = HashMap::with_capacity(raw.len());
        for (k, v) in raw {
            let id = k
                .parse::<i32>()
                .map_err(|e| TeamOverridesParseError::InvalidTeamId(k.clone(), e))?;
            if !v.rate.is_finite() || !(0.0..=1.0).contains(&v.rate) {
                return Err(TeamOverridesParseError::InvalidRate(id, v.rate));
            }
            overrides.insert(id, v);
        }
        Ok(TeamOverridesEnv { overrides })
    }
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

    #[test]
    fn parses_empty_team_overrides() {
        let parsed: TeamOverridesEnv = "".parse().unwrap();
        assert!(parsed.overrides.is_empty());

        let parsed: TeamOverridesEnv = "   ".parse().unwrap();
        assert!(parsed.overrides.is_empty());
    }

    #[test]
    fn parses_team_overrides_json() {
        let parsed: TeamOverridesEnv =
            r#"{"42":{"floor":50000,"rate":0.5},"99":{"floor":1000,"rate":1.0}}"#
                .parse()
                .unwrap();
        assert_eq!(parsed.overrides.len(), 2);
        assert_eq!(parsed.overrides[&42].floor, 50000);
        assert_eq!(parsed.overrides[&42].rate, 0.5);
        assert_eq!(parsed.overrides[&99].floor, 1000);
        assert_eq!(parsed.overrides[&99].rate, 1.0);
    }

    #[test]
    fn rejects_invalid_team_overrides_json() {
        assert!("{not json}".parse::<TeamOverridesEnv>().is_err());
    }

    #[test]
    fn rejects_non_numeric_team_overrides_key() {
        let err = r#"{"abc":{"floor":1,"rate":1.0}}"#.parse::<TeamOverridesEnv>().unwrap_err();
        assert!(matches!(
            err,
            TeamOverridesParseError::InvalidTeamId(ref k, _) if k == "abc"
        ));
    }

    #[test]
    fn rejects_rate_above_one() {
        let err = r#"{"42":{"floor":100,"rate":1.5}}"#.parse::<TeamOverridesEnv>().unwrap_err();
        assert!(matches!(
            err,
            TeamOverridesParseError::InvalidRate(42, r) if (r - 1.5).abs() < 1e-9
        ));
    }

    #[test]
    fn rejects_negative_rate() {
        let err = r#"{"42":{"floor":100,"rate":-0.1}}"#.parse::<TeamOverridesEnv>().unwrap_err();
        assert!(matches!(
            err,
            TeamOverridesParseError::InvalidRate(42, r) if (r + 0.1).abs() < 1e-9
        ));
    }

    #[test]
    fn rate_at_zero_and_one_are_accepted() {
        // Boundary values are valid; only out-of-range or non-finite are rejected.
        let parsed: TeamOverridesEnv =
            r#"{"42":{"floor":100,"rate":0.0},"99":{"floor":50,"rate":1.0}}"#
                .parse()
                .unwrap();
        assert_eq!(parsed.overrides[&42].rate, 0.0);
        assert_eq!(parsed.overrides[&99].rate, 1.0);
    }
}
