//! The `metrics` recorder keeps every series until the process exits, so this counter hands its
//! gauge to `/metrics` itself. A team has a series only while its count in the last full window is
//! at or over the floor, for at most `max_teams` teams.

use std::{
    collections::HashMap,
    num::NonZeroU64,
    sync::{Mutex, MutexGuard, PoisonError},
    time::{Duration, Instant},
};

use common_metrics::ExtraGauge;

use crate::core::ids::TeamId;

pub struct TeamWindowCounter {
    name: &'static str,
    help: &'static str,
    window: Duration,
    floor: u64,
    max_teams: usize,
    origin: Instant,
    state: Mutex<WindowState>,
}

struct WindowState {
    index: u128,
    counts: HashMap<TeamId, u64>,
    last_window: Vec<(TeamId, u64)>,
}

impl TeamWindowCounter {
    pub fn new(
        name: &'static str,
        help: &'static str,
        window: Duration,
        floor: NonZeroU64,
        max_teams: usize,
    ) -> Self {
        Self::new_at(name, help, window, floor, max_teams, Instant::now())
    }

    fn new_at(
        name: &'static str,
        help: &'static str,
        window: Duration,
        floor: NonZeroU64,
        max_teams: usize,
        origin: Instant,
    ) -> Self {
        Self {
            name,
            help,
            window,
            floor: floor.get(),
            max_teams,
            origin,
            state: Mutex::new(WindowState {
                index: 0,
                counts: HashMap::new(),
                last_window: Vec::new(),
            }),
        }
    }

    pub fn record(&self, team_id: TeamId) {
        self.record_at(team_id, Instant::now());
    }

    fn record_at(&self, team_id: TeamId, now: Instant) {
        if self.max_teams == 0 {
            return;
        }
        let mut state = self.lock();
        self.rotate(&mut state, now);
        *state.counts.entry(team_id).or_insert(0) += 1;
    }

    pub fn gauge(&self) -> ExtraGauge {
        self.gauge_at(Instant::now())
    }

    fn gauge_at(&self, now: Instant) -> ExtraGauge {
        ExtraGauge {
            name: self.name,
            help: self.help,
            series: self
                .last_window_at(now)
                .into_iter()
                .map(|(team_id, count)| (vec![("team_id", team_id.to_string())], count as f64))
                .collect(),
        }
    }

    pub fn last_window_at(&self, now: Instant) -> Vec<(TeamId, u64)> {
        let mut state = self.lock();
        self.rotate(&mut state, now);
        state.last_window.clone()
    }

    fn rotate(&self, state: &mut WindowState, now: Instant) {
        let index = now.saturating_duration_since(self.origin).as_nanos() / self.window.as_nanos();
        if index <= state.index {
            return;
        }
        state.last_window = if index == state.index + 1 {
            self.over_floor(state.counts.drain())
        } else {
            state.counts.clear();
            Vec::new()
        };
        state.index = index;
    }

    fn over_floor(&self, counts: impl Iterator<Item = (TeamId, u64)>) -> Vec<(TeamId, u64)> {
        let mut teams: Vec<(TeamId, u64)> =
            counts.filter(|&(_, count)| count >= self.floor).collect();
        teams.sort_unstable_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
        teams.truncate(self.max_teams);
        teams
    }

    fn lock(&self) -> MutexGuard<'_, WindowState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const WINDOW: Duration = Duration::from_secs(60);

    fn counter(floor: u64, max_teams: usize, start: Instant) -> TeamWindowCounter {
        TeamWindowCounter::new_at(
            "test_team_gauge",
            "Test gauge.",
            WINDOW,
            NonZeroU64::new(floor).unwrap(),
            max_teams,
            start,
        )
    }

    fn record_n(counter: &TeamWindowCounter, team_id: TeamId, n: u64, at: Instant) {
        for _ in 0..n {
            counter.record_at(team_id, at);
        }
    }

    #[test]
    fn team_appears_only_after_a_full_window_at_or_over_the_floor_and_expires_after() {
        let start = Instant::now();
        let counter = counter(3, 10, start);

        record_n(&counter, 1, 3, start);
        record_n(&counter, 2, 2, start + Duration::from_secs(30));
        assert_eq!(counter.last_window_at(start + Duration::from_secs(59)), []);

        assert_eq!(counter.last_window_at(start + WINDOW), [(1, 3)]);
        assert_eq!(
            counter
                .gauge_at(start + WINDOW + Duration::from_secs(59))
                .series,
            [(vec![("team_id", "1".to_string())], 3.0)]
        );

        record_n(&counter, 1, 2, start + WINDOW + Duration::from_secs(10));
        assert_eq!(counter.last_window_at(start + WINDOW * 2), []);

        record_n(&counter, 1, 5, start + WINDOW * 2);
        assert_eq!(counter.last_window_at(start + WINDOW * 3), [(1, 5)]);
        assert_eq!(counter.last_window_at(start + WINDOW * 4), []);
        record_n(&counter, 1, 5, start + WINDOW * 4);
        assert_eq!(counter.last_window_at(start + WINDOW * 6), []);
    }

    #[test]
    fn exports_at_most_max_teams_with_the_highest_counts() {
        let start = Instant::now();
        for (max_teams, expected) in [(2, vec![(30, 30), (20, 20)]), (0, vec![])] {
            let counter = counter(1, max_teams, start);
            for (team_id, n) in [(10, 10), (20, 20), (30, 30)] {
                record_n(&counter, team_id, n, start);
            }
            for team_id in 1000..2000 {
                counter.record_at(team_id, start);
            }

            assert_eq!(
                counter.last_window_at(start + WINDOW),
                expected,
                "max_teams {max_teams}"
            );
        }
    }
}
