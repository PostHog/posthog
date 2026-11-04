use std::collections::HashSet;
use std::time::Duration;

use common_database::PoolConfig;
use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

use crate::config::{IdentityTables, IdentityTablesConfig};
use crate::publish::DrainConfig;

/// librdkafka's Java-compatible partitioner. The cohort stream processor
/// keeps each person's state on the worker that this placement selects for
/// `team_id:person_uuid`, and every producer it reads from (the cohort
/// seeder, the cohort event shuffler, Node, which computes the partition
/// itself) places keys this way. librdkafka's own default is CRC32 based
/// and routes the same key elsewhere, and nothing downstream reports it.
pub const MURMUR2_RANDOM: &str = "murmur2_random";

#[derive(Envconfig, Clone)]
pub struct PublisherConfig {
    /// The persons primary identity writes to; the outbox lives there.
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub primary_database_url: String,

    #[envconfig(nested = true)]
    pub tables: IdentityTablesConfig,

    /// One pool: a replica holds one claim transaction at a time plus the
    /// gauge query, so a small pool is a ceiling, not a target.
    #[envconfig(default = "4")]
    pub max_pg_connections: u32,

    #[envconfig(default = "10")]
    pub acquire_timeout_secs: u64,

    /// Bounds any one statement of the claim transaction, so a stuck
    /// resolution cannot hold the claimed rows past the produce timeout
    /// by much.
    #[envconfig(default = "5000")]
    pub statement_timeout_ms: u64,

    #[envconfig(default = "300")]
    pub idle_timeout_secs: u64,

    #[envconfig(default = "9109")]
    pub metrics_port: u16,

    /// Idle poll between passes; a pass that claims a full batch loops
    /// again at once.
    #[envconfig(default = "200")]
    pub lifecycle_publish_interval_ms: u64,

    #[envconfig(default = "1000")]
    pub lifecycle_publish_batch_size: i64,

    /// Distinct id rows one pass produces at most, across every row it
    /// claimed. A large merge or delete drains across several passes, each
    /// advancing its pointer's cursor, so no transaction stays open across
    /// more produces than the produce timeout can carry.
    #[envconfig(default = "10000")]
    pub lifecycle_publish_max_rows_per_pass: i64,

    /// How long one claim waits for Kafka acks before it rolls back and
    /// retries. Keep it well under the database's
    /// idle_in_transaction_session_timeout.
    #[envconfig(default = "5000")]
    pub lifecycle_publish_produce_timeout_ms: u64,

    /// Lag above which the gauge refresh logs a warning. The page itself
    /// lives in Grafana on the lag gauge.
    #[envconfig(default = "300")]
    pub lifecycle_publish_lag_alert_secs: u64,

    /// No default on purpose. The table set defaults to the validation
    /// tables, whose versions come from a different sequence than the real
    /// tables and would win in ClickHouse, so a deployment must say which
    /// topic it feeds: `clickhouse_person_distinct_id` only behind the real
    /// tables, a capture topic behind the validation set.
    pub person_distinct_id_topic: String,

    #[envconfig(default = "false")]
    pub person_merge_events_enabled: bool,

    /// Required when merge events are enabled; no default, for the same
    /// reason as the distinct id topic.
    pub person_merge_events_topic: Option<String>,

    /// Teams whose merges emit `person_merge_events`: comma separated team
    /// ids, `*` for every team, empty for none. Same syntax and default as
    /// the Node setting. The cohort seeder's own allowlist must cover the
    /// same teams but reads an empty value as every team, so copy the ids
    /// across, not the string.
    #[envconfig(default = "2")]
    pub person_merge_events_team_allowlist: String,

    /// Read through [`PublisherConfig::kafka`], which pins the partitioner.
    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,
}

/// Teams whose merges emit `person_merge_events`, with Node's
/// PERSON_MERGE_EVENTS_TEAM_ALLOWLIST contract: `*` is every team and empty
/// is no team. Not `common_types::cohort::TeamAllowlist`, which reads an
/// empty value as every team and accepts ranges.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum MergeEventsAllowlist {
    All,
    Teams(HashSet<i64>),
}

impl MergeEventsAllowlist {
    /// An entry that is not a team id is an error instead of a silently
    /// dropped team, so a typo cannot close the gate for one team unnoticed.
    pub fn parse(value: &str) -> Result<Self, String> {
        let value = value.trim();
        if value == "*" {
            return Ok(Self::All);
        }
        let mut teams = HashSet::new();
        for entry in value.split(',').map(str::trim).filter(|e| !e.is_empty()) {
            let team_id = entry
                .parse::<i64>()
                .map_err(|_| format!("invalid team id {entry:?} in team allowlist {value:?}"))?;
            teams.insert(team_id);
        }
        Ok(Self::Teams(teams))
    }

    pub fn allows(&self, team_id: i64) -> bool {
        match self {
            Self::All => true,
            Self::Teams(teams) => teams.contains(&team_id),
        }
    }
}

#[derive(Clone, Debug)]
pub struct MergeEventsSettings {
    pub topic: String,
    pub team_allowlist: MergeEventsAllowlist,
}

impl PublisherConfig {
    pub fn tables(&self) -> IdentityTables {
        self.tables.tables()
    }

    pub fn pool_config(&self) -> PoolConfig {
        PoolConfig {
            min_connections: 0,
            max_connections: self.max_pg_connections,
            acquire_timeout: Duration::from_secs(self.acquire_timeout_secs),
            idle_timeout: (self.idle_timeout_secs != 0)
                .then(|| Duration::from_secs(self.idle_timeout_secs)),
            test_before_acquire: false,
            statement_timeout_ms: (self.statement_timeout_ms != 0)
                .then_some(self.statement_timeout_ms),
            pool_name: Some("publisher".to_string()),
        }
    }

    pub fn kafka(&self) -> Result<KafkaConfig, String> {
        let mut kafka = self.kafka.clone();
        match kafka.kafka_producer_partitioner.as_deref() {
            None => kafka.kafka_producer_partitioner = Some(MURMUR2_RANDOM.to_string()),
            Some(MURMUR2_RANDOM) => {}
            Some(other) => {
                return Err(format!(
                    "KAFKA_PRODUCER_PARTITIONER must be {MURMUR2_RANDOM} or unset, got {other:?}: person_merge_events are placed by key"
                ))
            }
        }
        Ok(kafka)
    }

    pub fn merge_events(&self) -> Result<Option<MergeEventsSettings>, String> {
        if !self.person_merge_events_enabled {
            return Ok(None);
        }
        let topic = self
            .person_merge_events_topic
            .clone()
            .filter(|t| !t.trim().is_empty())
            .ok_or_else(|| {
                "PERSON_MERGE_EVENTS_ENABLED is set but PERSON_MERGE_EVENTS_TOPIC is not"
                    .to_string()
            })?;
        let team_allowlist = MergeEventsAllowlist::parse(&self.person_merge_events_team_allowlist)?;
        Ok(Some(MergeEventsSettings {
            topic,
            team_allowlist,
        }))
    }

    pub fn drain_config(&self, merge_events: Option<&MergeEventsSettings>) -> DrainConfig {
        DrainConfig {
            batch_size: self.lifecycle_publish_batch_size,
            max_rows_per_pass: self.lifecycle_publish_max_rows_per_pass,
            interval: Duration::from_millis(self.lifecycle_publish_interval_ms),
            lag_alert: Duration::from_secs(self.lifecycle_publish_lag_alert_secs),
            merge_events: merge_events.map(|settings| settings.team_allowlist.clone()),
        }
    }

    pub fn produce_timeout(&self) -> Duration {
        Duration::from_millis(self.lifecycle_publish_produce_timeout_ms)
    }

    /// How long a pass usually takes at most: one produce wait plus one
    /// slow statement. The publisher component's graceful shutdown covers
    /// it so an in-flight claim normally commits or rolls back cleanly. It
    /// is not a hard bound: a pass with many pointers runs two statements
    /// per pointer, and a pass torn down past the window only rolls back,
    /// because nothing commits before the acks.
    pub fn pass_deadline(&self) -> Duration {
        self.produce_timeout() + Duration::from_millis(self.statement_timeout_ms)
    }
}

#[cfg(test)]
mod tests {
    use std::collections::{HashMap, HashSet};

    use envconfig::Envconfig;

    use super::{MergeEventsAllowlist, PublisherConfig, MURMUR2_RANDOM};

    fn config(extra: &[(&str, &str)]) -> PublisherConfig {
        let mut env: HashMap<String, String> =
            HashMap::from([("PERSON_DISTINCT_ID_TOPIC".to_string(), "t".to_string())]);
        for (key, value) in extra {
            env.insert(key.to_string(), value.to_string());
        }
        PublisherConfig::init_from_hashmap(&env).expect("config initializes")
    }

    // Node reads an empty value as no team and `*` as every team; the cohort
    // crates read empty as every team, so a parser that drifted either way
    // would open or close the gate for every team unnoticed.
    #[test]
    fn team_allowlist_follows_the_node_syntax() {
        let cases = [
            ("", Some(MergeEventsAllowlist::Teams(HashSet::new()))),
            ("*", Some(MergeEventsAllowlist::All)),
            (
                "2,125931",
                Some(MergeEventsAllowlist::Teams(HashSet::from([2, 125931]))),
            ),
            (
                " 2 , 3 ",
                Some(MergeEventsAllowlist::Teams(HashSet::from([2, 3]))),
            ),
            ("1000:2000", None),
        ];
        for (input, expected) in cases {
            assert_eq!(
                MergeEventsAllowlist::parse(input).ok(),
                expected,
                "input {input:?}"
            );
        }
        assert!(MergeEventsAllowlist::All.allows(7));
        assert!(!MergeEventsAllowlist::Teams(HashSet::new()).allows(7));
    }

    #[test]
    fn the_producer_partitioner_is_pinned_to_murmur2_random() {
        assert_eq!(
            config(&[])
                .kafka()
                .unwrap()
                .kafka_producer_partitioner
                .as_deref(),
            Some(MURMUR2_RANDOM)
        );
        assert_eq!(
            config(&[("KAFKA_PRODUCER_PARTITIONER", MURMUR2_RANDOM)])
                .kafka()
                .unwrap()
                .kafka_producer_partitioner
                .as_deref(),
            Some(MURMUR2_RANDOM)
        );
        assert!(
            config(&[("KAFKA_PRODUCER_PARTITIONER", "consistent_random")])
                .kafka()
                .is_err()
        );
    }

    #[test]
    fn merge_events_need_a_topic_once_enabled() {
        assert!(config(&[]).merge_events().unwrap().is_none());
        assert!(config(&[("PERSON_MERGE_EVENTS_ENABLED", "true")])
            .merge_events()
            .is_err());
        let settings = config(&[
            ("PERSON_MERGE_EVENTS_ENABLED", "true"),
            ("PERSON_MERGE_EVENTS_TOPIC", "person_merge_events_capture"),
            ("PERSON_MERGE_EVENTS_TEAM_ALLOWLIST", "*"),
        ])
        .merge_events()
        .unwrap()
        .expect("enabled");
        assert_eq!(settings.topic, "person_merge_events_capture");
        assert_eq!(settings.team_allowlist, MergeEventsAllowlist::All);
    }
}
