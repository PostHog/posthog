use std::collections::HashSet;
use std::time::Duration;

use envconfig::Envconfig;
use personhog_common::cdc_parity::Side;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "localhost:9092")]
    pub node_kafka_hosts: String,
    #[envconfig(default = "false")]
    pub node_kafka_tls: bool,
    #[envconfig(default = "clickhouse_person_distinct_id")]
    pub node_distinct_id_topic: String,
    #[envconfig(default = "person_merge_events")]
    pub node_merge_events_topic: String,

    #[envconfig(default = "localhost:9092")]
    pub personhog_kafka_hosts: String,
    #[envconfig(default = "false")]
    pub personhog_kafka_tls: bool,
    pub personhog_distinct_id_topic: String,
    pub personhog_merge_events_topic: String,

    /// Has to exceed the publisher's drain lag, or every pair settles
    /// one-sided before the personhog copy arrives.
    #[envconfig(default = "60")]
    pub parity_grace_seconds: u64,
    /// A quiet partition stops holding the watermark back after this long.
    #[envconfig(default = "30")]
    pub parity_idle_partition_seconds: u64,
    /// Covers the timestamp skew between a merge event and the rows it moved.
    #[envconfig(default = "2000")]
    pub parity_mapping_lag_ms: u64,
    /// An entry costs about half a kilobyte.
    #[envconfig(default = "1000000")]
    pub parity_max_entries: usize,
    /// Empty means every team. Set it to the merge events allowlist when
    /// that is a subset, or every other team's merges settle one-sided.
    #[envconfig(default = "")]
    pub parity_teams: String,
    #[envconfig(default = "500")]
    pub parity_sample_ring_size: usize,
    #[envconfig(default = "1000")]
    pub parity_sweep_interval_ms: u64,

    /// Unset leaves `/debug/mismatches` off; its samples carry distinct ids.
    pub debug_api_secret: Option<String>,

    #[envconfig(default = "0.0.0.0")]
    pub bind_host: String,
    #[envconfig(default = "3301")]
    pub bind_port: u16,
}

#[derive(Clone, Debug)]
pub struct FeedConfig {
    pub side: Side,
    pub kafka_hosts: String,
    pub kafka_tls: bool,
    pub distinct_id_topic: String,
    pub merge_events_topic: String,
}

impl Config {
    pub fn feeds(&self) -> [FeedConfig; 2] {
        [
            FeedConfig {
                side: Side::Node,
                kafka_hosts: self.node_kafka_hosts.clone(),
                kafka_tls: self.node_kafka_tls,
                distinct_id_topic: self.node_distinct_id_topic.clone(),
                merge_events_topic: self.node_merge_events_topic.clone(),
            },
            FeedConfig {
                side: Side::Personhog,
                kafka_hosts: self.personhog_kafka_hosts.clone(),
                kafka_tls: self.personhog_kafka_tls,
                distinct_id_topic: self.personhog_distinct_id_topic.clone(),
                merge_events_topic: self.personhog_merge_events_topic.clone(),
            },
        ]
    }

    pub fn teams(&self) -> Result<Option<HashSet<i64>>, String> {
        let teams = self
            .parity_teams
            .split(',')
            .map(str::trim)
            .filter(|team| !team.is_empty())
            .map(|team| {
                team.parse::<i64>()
                    .map_err(|_| format!("PARITY_TEAMS holds {team:?}, expected integer team ids"))
            })
            .collect::<Result<HashSet<i64>, String>>()?;
        Ok((!teams.is_empty()).then_some(teams))
    }

    pub fn grace(&self) -> Duration {
        Duration::from_secs(self.parity_grace_seconds)
    }

    pub fn idle_partition(&self) -> Duration {
        Duration::from_secs(self.parity_idle_partition_seconds)
    }

    pub fn mapping_lag(&self) -> Duration {
        Duration::from_millis(self.parity_mapping_lag_ms)
    }

    pub fn sweep_interval(&self) -> Duration {
        Duration::from_millis(self.parity_sweep_interval_ms.max(100))
    }

    pub fn bind(&self) -> String {
        format!("{}:{}", self.bind_host, self.bind_port)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(teams: &str) -> Config {
        Config::init_from_hashmap(&std::collections::HashMap::from([
            ("PERSONHOG_DISTINCT_ID_TOPIC".to_string(), "a".to_string()),
            ("PERSONHOG_MERGE_EVENTS_TOPIC".to_string(), "b".to_string()),
            ("PARITY_TEAMS".to_string(), teams.to_string()),
        ]))
        .expect("config")
    }

    #[test]
    fn team_filter_parses_or_refuses() {
        assert_eq!(config("").teams(), Ok(None));
        assert_eq!(config(" 2, 15 ").teams(), Ok(Some(HashSet::from([2, 15]))));
        assert!(config("2,all").teams().is_err());
    }
}
