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
    /// The two `clickhouse_person` feeds; persons are compared only when
    /// both are set.
    pub node_person_topic: Option<String>,
    pub personhog_person_topic: Option<String>,
    /// Comma separated top level property keys left out of the person
    /// comparison: their values depend on the order each backend applied a
    /// merge's writes in.
    #[envconfig(default = "$creator_event_uuid")]
    pub parity_person_ignored_properties: String,
    /// The share of persons compared, 1 to 100. Both feeds keep the same
    /// persons, picked by a hash of the key, so every kept person still gets a
    /// full verdict.
    #[envconfig(default = "100")]
    pub parity_person_sample_percent: u32,

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
    /// Defaults to the grace. Zero turns the warmup off, for a fixture
    /// whose readers start before any traffic.
    pub parity_warmup_seconds: Option<u64>,
    /// Retained rows, merges and persons across both feeds; each costs about half a
    /// kilobyte.
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
    /// Half the default grace, so the partitions a repartition adds are
    /// read before their counterparts on the other feed settle one-sided.
    #[envconfig(default = "30")]
    pub parity_metadata_poll_seconds: u64,

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
    pub person_topic: Option<String>,
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
                person_topic: self.node_person_topic.clone(),
            },
            FeedConfig {
                side: Side::Personhog,
                kafka_hosts: self.personhog_kafka_hosts.clone(),
                kafka_tls: self.personhog_kafka_tls,
                distinct_id_topic: self.personhog_distinct_id_topic.clone(),
                merge_events_topic: self.personhog_merge_events_topic.clone(),
                person_topic: self.personhog_person_topic.clone(),
            },
        ]
    }

    pub fn compares_persons(&self) -> Result<bool, String> {
        let set = |topic: &Option<String>| topic.as_deref().is_some_and(|t| !t.is_empty());
        match (
            set(&self.node_person_topic),
            set(&self.personhog_person_topic),
        ) {
            (true, true) => Ok(true),
            (false, false) => Ok(false),
            _ => Err("set NODE_PERSON_TOPIC and PERSONHOG_PERSON_TOPIC together".to_string()),
        }
    }

    pub fn person_ignored_properties(&self) -> HashSet<String> {
        self.parity_person_ignored_properties
            .split(',')
            .map(str::trim)
            .filter(|key| !key.is_empty())
            .map(str::to_string)
            .collect()
    }

    pub fn person_sample_percent(&self) -> Result<u32, String> {
        match self.parity_person_sample_percent {
            percent @ 1..=100 => Ok(percent),
            percent => Err(format!(
                "PARITY_PERSON_SAMPLE_PERCENT is {percent}, expected 1 to 100"
            )),
        }
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

    pub fn warmup(&self) -> Duration {
        Duration::from_secs(
            self.parity_warmup_seconds
                .unwrap_or(self.parity_grace_seconds),
        )
    }

    pub fn sweep_interval(&self) -> Duration {
        Duration::from_millis(self.parity_sweep_interval_ms.max(100))
    }

    pub fn metadata_poll(&self) -> Duration {
        Duration::from_secs(self.parity_metadata_poll_seconds.max(1))
    }

    pub fn bind(&self) -> String {
        format!("{}:{}", self.bind_host, self.bind_port)
    }

    /// An empty value is unset: an empty header must not open the endpoint.
    pub fn debug_api_secret(&self) -> Option<&str> {
        self.debug_api_secret
            .as_deref()
            .filter(|secret| !secret.is_empty())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(vars: &[(&str, &str)]) -> Config {
        let mut env = std::collections::HashMap::from([
            ("PERSONHOG_DISTINCT_ID_TOPIC".to_string(), "a".to_string()),
            ("PERSONHOG_MERGE_EVENTS_TOPIC".to_string(), "b".to_string()),
        ]);
        env.extend(vars.iter().map(|(k, v)| (k.to_string(), v.to_string())));
        Config::init_from_hashmap(&env).expect("config")
    }

    #[test]
    fn team_filter_parses_or_refuses() {
        assert_eq!(config(&[("PARITY_TEAMS", "")]).teams(), Ok(None));
        assert_eq!(
            config(&[("PARITY_TEAMS", " 2, 15 ")]).teams(),
            Ok(Some(HashSet::from([2, 15])))
        );
        assert!(config(&[("PARITY_TEAMS", "2,all")]).teams().is_err());
    }

    #[test]
    fn the_person_sample_accepts_a_percentage_only() {
        for (value, expected) in [
            ("100", Ok(100)),
            ("1", Ok(1)),
            ("0", Err(())),
            ("101", Err(())),
        ] {
            assert_eq!(
                config(&[("PARITY_PERSON_SAMPLE_PERCENT", value)])
                    .person_sample_percent()
                    .map_err(|_| ()),
                expected,
                "{value}"
            );
        }
    }

    #[test]
    fn persons_are_compared_only_with_both_topics() {
        let cases = [
            ("neither", vec![], Ok(false)),
            (
                "both",
                vec![("NODE_PERSON_TOPIC", "n"), ("PERSONHOG_PERSON_TOPIC", "p")],
                Ok(true),
            ),
            ("only node", vec![("NODE_PERSON_TOPIC", "n")], Err(())),
            (
                "only personhog",
                vec![("PERSONHOG_PERSON_TOPIC", "p")],
                Err(()),
            ),
        ];
        for (name, vars, expected) in cases {
            assert_eq!(
                config(&vars).compares_persons().map_err(|_| ()),
                expected,
                "{name}"
            );
        }
        assert_eq!(
            config(&[]).person_ignored_properties(),
            HashSet::from(["$creator_event_uuid".to_string()])
        );
    }

    #[test]
    fn the_warmup_follows_the_grace_unless_set() {
        assert_eq!(
            config(&[("PARITY_GRACE_SECONDS", "7")]).warmup(),
            Duration::from_secs(7)
        );
        assert_eq!(
            config(&[
                ("PARITY_GRACE_SECONDS", "7"),
                ("PARITY_WARMUP_SECONDS", "0")
            ])
            .warmup(),
            Duration::ZERO
        );
    }

    #[test]
    fn an_empty_debug_secret_leaves_the_endpoint_off() {
        assert_eq!(config(&[("DEBUG_API_SECRET", "")]).debug_api_secret(), None);
        assert_eq!(
            config(&[("DEBUG_API_SECRET", "s")]).debug_api_secret(),
            Some("s")
        );
    }
}
