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

    /// How long to accumulate aggregator state before flushing. Each flush
    /// emits one message per unique tuple seen during the window.
    #[envconfig(default = "30")]
    pub flush_interval_secs: u64,

    /// Cap on the worker's in-memory tuple buffer. Hitting this triggers
    /// an early backpressure flush ahead of the timer.
    #[envconfig(default = "500000")]
    pub max_buffered_tuples: usize,

    /// Transactional producer ID for the events worker. Must be unique per
    /// pod and stable across restarts (e.g. K8s pod name + "-events"). The
    /// groups worker uses a separate id because rdkafka allows only one
    /// outstanding transaction per `transactional.id`.
    #[envconfig(default = "property-vals-rs-local-events")]
    pub kafka_transactional_id: String,

    /// How long Kafka will wait on init_transactions, send_offsets_to_transaction,
    /// and commit_transaction calls before timing out the transaction.
    #[envconfig(default = "60")]
    pub kafka_transaction_timeout_secs: u64,

    /// Topic that carries `$groupidentify` messages. Each message is one
    /// group update with the full property blob.
    #[envconfig(default = "clickhouse_groups")]
    pub groups_kafka_consumer_topic: String,

    /// Consumer group for the groups worker. Independent of the events
    /// consumer group; the two workers are unrelated for Kafka's purposes.
    #[envconfig(default = "clickhouse-property-vals-rs-groups")]
    pub groups_kafka_consumer_group: String,

    /// Transactional producer ID for the groups worker. Distinct from
    /// `kafka_transactional_id` because each producer needs its own id.
    #[envconfig(default = "property-vals-rs-local-groups")]
    pub groups_kafka_transactional_id: String,

    /// Teams that are always processed regardless of `rollout_percentage`.
    /// Use to pin specific teams during testing or keep a hand-picked
    /// team included while ramping the rest of the fleet.
    #[envconfig(default = "")]
    pub allowed_teams: TeamList,

    /// Teams that are never processed regardless of allow-list or rollout.
    /// `blocked_teams` wins over `allowed_teams` on overlap, since "drop
    /// this team" is a safer default than "process this team".
    #[envconfig(default = "")]
    pub blocked_teams: TeamList,

    /// Percentage of teams (0-100) to process, picked by a stable hash
    /// of `team_id`. `allowed_teams` overrides this; `blocked_teams` still
    /// excludes. Default in code is 100 (process all) so `cargo run`
    /// against the local stack does something visible. Production charts
    /// set this to 0 and ramp via overrides.
    #[envconfig(default = "100")]
    pub rollout_percentage: u8,

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

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        // Default to clickhouse_events_json so cargo run works against the local
        // dev stack with no env overrides. Production charts set
        // KAFKA_CONSUMER_TOPIC=team_event_partitioned_events_json.
        //
        // auto_commit=false because offsets are committed by the
        // transactional producer via send_offsets_to_transaction. If
        // librdkafka auto-committed in the background we'd lose the
        // exactly-once guarantee.
        ConsumerConfig::set_defaults(
            "clickhouse-property-vals-rs",
            "clickhouse_events_json",
            false,
        );
        Config::init_from_env()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn team_list_parses() {
        let list: TeamList = "1,2,3".parse().unwrap();
        assert_eq!(list.teams, vec![1, 2, 3]);
        let empty: TeamList = "".parse().unwrap();
        assert!(empty.teams.is_empty());
    }
}
