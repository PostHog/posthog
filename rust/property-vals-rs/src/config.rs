use std::hash::{Hash, Hasher};
use std::{num::ParseIntError, str::FromStr};

use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;
use siphasher::sip::SipHasher13;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,

    #[envconfig(default = "clickhouse_property_values")]
    pub output_topic: String,

    #[envconfig(default = "30")]
    pub flush_interval_secs: u64,

    #[envconfig(default = "500000")]
    pub max_buffered_tuples: usize,

    #[envconfig(default = "property-vals-rs-local-events")]
    pub kafka_transactional_id: String,

    #[envconfig(default = "60")]
    pub kafka_transaction_timeout_secs: u64,

    #[envconfig(default = "clickhouse_groups")]
    pub groups_kafka_consumer_topic: String,

    #[envconfig(default = "clickhouse-property-vals-rs-groups")]
    pub groups_kafka_consumer_group: String,

    #[envconfig(default = "property-vals-rs-local-groups")]
    pub groups_kafka_transactional_id: String,

    #[envconfig(default = "")]
    pub allowed_teams: TeamList,

    #[envconfig(default = "")]
    pub blocked_teams: TeamList,

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
        // auto_commit=false because offsets are committed by the
        // transactional producer via send_offsets_to_transaction; auto-commit
        // would break the exactly-once guarantee.
        ConsumerConfig::set_defaults(
            "clickhouse-property-vals-rs",
            "clickhouse_events_json",
            false,
        );
        Config::init_from_env()
    }

    pub fn should_process(&self, team_id: i64) -> bool {
        team_filter_allows(
            team_id,
            &self.allowed_teams.teams,
            &self.blocked_teams.teams,
            self.rollout_percentage,
        )
    }
}

pub fn team_filter_allows(
    team_id: i64,
    allowed: &[i64],
    blocked: &[i64],
    rollout_percentage: u8,
) -> bool {
    if blocked.contains(&team_id) {
        return false;
    }
    if allowed.contains(&team_id) {
        return true;
    }
    team_in_rollout(team_id, rollout_percentage)
}

fn team_in_rollout(team_id: i64, rollout_percentage: u8) -> bool {
    if rollout_percentage >= 100 {
        return true;
    }
    if rollout_percentage == 0 {
        return false;
    }
    let mut hasher = SipHasher13::new();
    team_id.hash(&mut hasher);
    (hasher.finish() % 100) < rollout_percentage as u64
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    #[test]
    fn team_list_parses() {
        let list: TeamList = "1,2,3".parse().unwrap();
        assert_eq!(list.teams, vec![1, 2, 3]);
        let empty: TeamList = "".parse().unwrap();
        assert!(empty.teams.is_empty());
    }

    fn arb_team_list() -> impl Strategy<Value = Vec<i64>> {
        prop::collection::vec(-1_000i64..=1_000, 0..10)
    }

    proptest! {
        #[test]
        fn blocked_teams_never_process(
            team_id: i64,
            rollout in 0u8..=100,
            allowed in arb_team_list(),
            mut blocked in arb_team_list(),
        ) {
            blocked.push(team_id);
            prop_assert!(!team_filter_allows(team_id, &allowed, &blocked, rollout));
        }

        #[test]
        fn allowed_teams_process_when_not_blocked(
            team_id: i64,
            rollout in 0u8..=100,
            blocked in arb_team_list(),
            mut allowed in arb_team_list(),
        ) {
            let blocked: Vec<i64> = blocked.into_iter().filter(|t| *t != team_id).collect();
            allowed.push(team_id);
            prop_assert!(team_filter_allows(team_id, &allowed, &blocked, rollout));
        }

        #[test]
        fn full_rollout_processes_any_non_blocked_team(
            team_id: i64,
            allowed in arb_team_list(),
            blocked in arb_team_list(),
        ) {
            let blocked: Vec<i64> = blocked.into_iter().filter(|t| *t != team_id).collect();
            prop_assert!(team_filter_allows(team_id, &allowed, &blocked, 100));
        }

        #[test]
        fn zero_rollout_drops_any_non_allowed_team(
            team_id: i64,
            allowed in arb_team_list(),
            blocked in arb_team_list(),
        ) {
            let allowed: Vec<i64> = allowed.into_iter().filter(|t| *t != team_id).collect();
            let blocked: Vec<i64> = blocked.into_iter().filter(|t| *t != team_id).collect();
            prop_assert!(!team_filter_allows(team_id, &allowed, &blocked, 0));
        }

        #[test]
        fn should_process_is_deterministic(
            team_id: i64,
            rollout in 0u8..=100,
            allowed in arb_team_list(),
            blocked in arb_team_list(),
        ) {
            let first = team_filter_allows(team_id, &allowed, &blocked, rollout);
            for _ in 0..5 {
                prop_assert_eq!(team_filter_allows(team_id, &allowed, &blocked, rollout), first);
            }
        }
    }

    #[test]
    fn rollout_percentage_approximates_target_share() {
        let included = (1..=10_000)
            .filter(|t| team_filter_allows(*t, &[], &[], 10))
            .count();
        assert!(
            (900..=1100).contains(&included),
            "expected ~1000 of 10000 at 10%, got {included}"
        );
    }
}
