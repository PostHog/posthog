use std::hash::{Hash, Hasher};
use std::time::Duration;

use siphasher::sip::SipHasher13;

use crate::config::{Config, TeamList};

pub struct AppContext {
    pub allowed_teams: TeamList,
    pub blocked_teams: TeamList,
    pub rollout_percentage: u8,
    pub flush_interval: Duration,
    pub max_buffered_tuples: usize,
}

impl AppContext {
    pub fn new(config: &Config) -> Self {
        Self {
            allowed_teams: config.allowed_teams.clone(),
            blocked_teams: config.blocked_teams.clone(),
            rollout_percentage: config.rollout_percentage,
            flush_interval: Duration::from_secs(config.flush_interval_secs),
            max_buffered_tuples: config.max_buffered_tuples,
        }
    }

    pub fn should_process(&self, team_id: i64) -> bool {
        if self.blocked_teams.teams.contains(&team_id) {
            return false;
        }
        if self.allowed_teams.teams.contains(&team_id) {
            return true;
        }
        self.team_in_rollout(team_id)
    }

    fn team_in_rollout(&self, team_id: i64) -> bool {
        if self.rollout_percentage >= 100 {
            return true;
        }
        if self.rollout_percentage == 0 {
            return false;
        }
        let mut hasher = SipHasher13::new();
        team_id.hash(&mut hasher);
        (hasher.finish() % 100) < self.rollout_percentage as u64
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    fn ctx(allowed: Vec<i64>, blocked: Vec<i64>, rollout_percentage: u8) -> AppContext {
        AppContext {
            allowed_teams: TeamList { teams: allowed },
            blocked_teams: TeamList { teams: blocked },
            rollout_percentage,
            flush_interval: Duration::from_secs(0),
            max_buffered_tuples: 0,
        }
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
            let c = ctx(allowed, blocked, rollout);
            prop_assert!(!c.should_process(team_id));
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
            let c = ctx(allowed, blocked, rollout);
            prop_assert!(c.should_process(team_id));
        }

        #[test]
        fn full_rollout_processes_any_non_blocked_team(
            team_id: i64,
            allowed in arb_team_list(),
            blocked in arb_team_list(),
        ) {
            let blocked: Vec<i64> = blocked.into_iter().filter(|t| *t != team_id).collect();
            let c = ctx(allowed, blocked, 100);
            prop_assert!(c.should_process(team_id));
        }

        #[test]
        fn zero_rollout_drops_any_non_allowed_team(
            team_id: i64,
            allowed in arb_team_list(),
            blocked in arb_team_list(),
        ) {
            let allowed: Vec<i64> = allowed.into_iter().filter(|t| *t != team_id).collect();
            let blocked: Vec<i64> = blocked.into_iter().filter(|t| *t != team_id).collect();
            let c = ctx(allowed, blocked, 0);
            prop_assert!(!c.should_process(team_id));
        }

        #[test]
        fn should_process_is_deterministic(
            team_id: i64,
            rollout in 0u8..=100,
            allowed in arb_team_list(),
            blocked in arb_team_list(),
        ) {
            let c = ctx(allowed, blocked, rollout);
            let first = c.should_process(team_id);
            for _ in 0..5 {
                prop_assert_eq!(c.should_process(team_id), first);
            }
        }
    }

    #[test]
    fn rollout_percentage_approximates_target_share() {
        let c = ctx(vec![], vec![], 10);
        let included = (1..=10_000).filter(|t| c.should_process(*t)).count();
        assert!(
            (900..=1100).contains(&included),
            "expected ~1000 of 10000 at 10%, got {included}"
        );
    }
}
