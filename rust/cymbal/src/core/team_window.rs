//! The `metrics` recorder keeps every series until the process exits, so this counter writes its
//! own `/metrics` lines. A team has a series only while its count in the last full window is at or
//! over the floor, for at most `max_teams` teams.

use std::{
    collections::HashMap,
    fmt::Write,
    num::NonZeroU64,
    sync::{Mutex, MutexGuard, PoisonError},
    time::{Duration, Instant},
};

use crate::core::ids::TeamId;

pub struct TeamWindowCounter {
    name: &'static str,
    help: &'static str,
    window: Duration,
    floor: u64,
    max_teams: usize,
    state: Mutex<WindowState>,
}

struct WindowState {
    started: Instant,
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
        now: Instant,
    ) -> Self {
        Self {
            name,
            help,
            window,
            floor: floor.get(),
            max_teams,
            state: Mutex::new(WindowState {
                started: now,
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

    pub fn render(&self, out: &mut String, labels: &[(&str, &str)]) {
        self.render_at(out, labels, Instant::now());
    }

    pub fn render_at(&self, out: &mut String, labels: &[(&str, &str)], now: Instant) {
        let teams = {
            let mut state = self.lock();
            self.rotate(&mut state, now);
            state.last_window.clone()
        };
        if teams.is_empty() {
            return;
        }

        // Writing to a String cannot fail.
        let _ = writeln!(out, "# HELP {} {}", self.name, self.help);
        let _ = writeln!(out, "# TYPE {} gauge", self.name);
        for (team_id, count) in teams {
            out.push_str(self.name);
            out.push('{');
            for (key, value) in labels {
                let _ = write!(out, "{key}=\"{value}\",");
            }
            let _ = writeln!(out, "team_id=\"{team_id}\"}} {count}");
        }
    }

    fn rotate(&self, state: &mut WindowState, now: Instant) {
        let elapsed = now.saturating_duration_since(state.started);
        if elapsed < self.window {
            return;
        }

        let counts = std::mem::take(&mut state.counts);
        let counts_are_last_window = self
            .window
            .checked_mul(2)
            .is_none_or(|two_windows| elapsed < two_windows);
        state.last_window = if counts_are_last_window {
            self.over_floor(counts)
        } else {
            Vec::new()
        };

        let into_current = elapsed.as_nanos() % self.window.as_nanos();
        let into_current = Duration::from_nanos(u64::try_from(into_current).unwrap_or(0));
        state.started = now.checked_sub(into_current).unwrap_or(now);
    }

    fn over_floor(&self, counts: HashMap<TeamId, u64>) -> Vec<(TeamId, u64)> {
        let mut teams: Vec<(TeamId, u64)> = counts
            .into_iter()
            .filter(|&(_, count)| count >= self.floor)
            .collect();
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

    fn rendered(counter: &TeamWindowCounter, at: Instant) -> String {
        let mut out = String::new();
        counter.render_at(&mut out, &[("product", "cymbal-test")], at);
        out
    }

    #[test]
    fn team_appears_only_after_a_full_window_at_or_over_the_floor_and_expires_after() {
        let start = Instant::now();
        let counter = counter(3, 10, start);

        record_n(&counter, 1, 3, start);
        record_n(&counter, 2, 2, start + Duration::from_secs(30));
        assert_eq!(rendered(&counter, start + Duration::from_secs(59)), "");

        let expected = "# HELP test_team_gauge Test gauge.\n\
                        # TYPE test_team_gauge gauge\n\
                        test_team_gauge{product=\"cymbal-test\",team_id=\"1\"} 3\n";
        assert_eq!(rendered(&counter, start + WINDOW), expected);
        assert_eq!(
            rendered(&counter, start + WINDOW + Duration::from_secs(59)),
            expected
        );

        record_n(&counter, 1, 2, start + WINDOW + Duration::from_secs(10));
        assert_eq!(rendered(&counter, start + WINDOW * 2), "");

        record_n(&counter, 1, 5, start + WINDOW * 2);
        assert!(rendered(&counter, start + WINDOW * 3).contains("team_id=\"1\"} 5"));
        assert_eq!(rendered(&counter, start + WINDOW * 4), "");
        record_n(&counter, 1, 5, start + WINDOW * 4);
        assert_eq!(rendered(&counter, start + WINDOW * 6), "");
    }

    #[test]
    fn exports_at_most_max_teams_with_the_highest_counts() {
        let start = Instant::now();
        for (max_teams, expected_teams) in [(2, vec![30, 20]), (0, vec![])] {
            let counter = counter(1, max_teams, start);
            for (team_id, n) in [(10, 10), (20, 20), (30, 30)] {
                record_n(&counter, team_id, n, start);
            }
            for team_id in 1000..2000 {
                counter.record_at(team_id, start);
            }

            let out = rendered(&counter, start + WINDOW);
            let teams: Vec<TeamId> = out
                .lines()
                .filter_map(|line| line.split("team_id=\"").nth(1))
                .map(|rest| rest.split('"').next().unwrap().parse().unwrap())
                .collect();
            assert_eq!(teams, expected_teams, "max_teams {max_teams}");
        }
    }
}
