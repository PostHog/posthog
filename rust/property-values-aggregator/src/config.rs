use std::{num::ParseIntError, str::FromStr};

use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,

    /// Topic the aggregator emits flush messages to. CH's `kafka_property_values`
    /// engine table consumes from this and writes to `posthog.property_values`.
    #[envconfig(default = "clickhouse_property_values")]
    pub output_topic: String,

    /// How long to accumulate per-partition state before flushing to the
    /// output topic. Each flush emits one message per unique tuple seen
    /// during the window.
    #[envconfig(default = "30")]
    pub flush_interval_secs: u64,

    /// Hard cap on per-partition map size. If reached before the flush timer
    /// fires, we flush early to bound memory.
    #[envconfig(default = "500000")]
    pub max_entries_per_partition: usize,

    /// Teams to opt-in or opt-out of property-values aggregation.
    #[envconfig(default = "")]
    pub filtered_teams: TeamList,

    /// Whether the team list above filters teams IN or OUT of processing.
    /// `opt_out` with an empty list means "process every team".
    #[envconfig(default = "opt_out")]
    pub filter_mode: TeamFilterMode,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3302")]
    pub port: u16,
}

#[derive(Clone)]
pub struct TeamList {
    pub teams: Vec<i64>,
}

impl FromStr for TeamList {
    type Err = ParseIntError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let mut teams = Vec::new();
        for team in s.trim().split(',') {
            if team.is_empty() {
                continue;
            }
            teams.push(team.parse()?);
        }
        Ok(TeamList { teams })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TeamFilterMode {
    OptIn,
    OptOut,
}

impl FromStr for TeamFilterMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().trim() {
            "opt_in" | "opt-in" | "optin" => Ok(TeamFilterMode::OptIn),
            "opt_out" | "opt-out" | "optout" => Ok(TeamFilterMode::OptOut),
            _ => Err(format!("Invalid team filter mode: {s}")),
        }
    }
}

impl TeamFilterMode {
    pub fn should_process(&self, list: &[i64], team_id: i64) -> bool {
        match self {
            TeamFilterMode::OptIn => list.contains(&team_id),
            TeamFilterMode::OptOut => !list.contains(&team_id),
        }
    }
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        ConsumerConfig::set_defaults(
            "clickhouse-property-values-aggregator",
            "team_event_partitioned_events_json",
            true,
        );
        Config::init_from_env()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn opt_out_with_empty_list_processes_all_teams() {
        let mode = TeamFilterMode::OptOut;
        assert!(mode.should_process(&[], 1));
        assert!(mode.should_process(&[], 999));
    }

    #[test]
    fn opt_in_with_empty_list_processes_no_teams() {
        let mode = TeamFilterMode::OptIn;
        assert!(!mode.should_process(&[], 1));
    }

    #[test]
    fn opt_in_includes_only_listed_teams() {
        let mode = TeamFilterMode::OptIn;
        assert!(mode.should_process(&[2], 2));
        assert!(!mode.should_process(&[2], 3));
    }

    #[test]
    fn opt_out_excludes_listed_teams() {
        let mode = TeamFilterMode::OptOut;
        assert!(!mode.should_process(&[2], 2));
        assert!(mode.should_process(&[2], 3));
    }

    #[test]
    fn team_list_parses() {
        let list: TeamList = "1,2,3".parse().unwrap();
        assert_eq!(list.teams, vec![1, 2, 3]);
        let empty: TeamList = "".parse().unwrap();
        assert!(empty.teams.is_empty());
    }
}
