use std::{
    str::FromStr,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use moka::sync::Cache;
use tracing::{info, warn};

use crate::{
    core::ids::TeamId,
    metric_consts::{FRAME_MISS_BREAKER_OPENED, FRAME_MISS_BREAKER_SKIPPED},
};

const WINDOW_BUCKETS: usize = 6;
const MAX_TRACKED_TEAMS: u64 = 100_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FrameMissBreakerMode {
    Off,
    // Runs the breaker and reports what it would skip, but every miss still uses Postgres.
    Log,
    Enforce,
}

impl FrameMissBreakerMode {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Off => "off",
            Self::Log => "log",
            Self::Enforce => "enforce",
        }
    }
}

impl FromStr for FrameMissBreakerMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_ascii_lowercase().as_str() {
            "off" => Ok(Self::Off),
            "log" => Ok(Self::Log),
            "enforce" => Ok(Self::Enforce),
            other => Err(format!(
                "unknown FRAME_MISS_BREAKER_MODE '{other}', expected 'off', 'log', or 'enforce'"
            )),
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct FrameMissBreakerConfig {
    pub mode: FrameMissBreakerMode,
    pub window: Duration,
    pub min_lookups: u64,
    pub miss_ratio: f64,
    pub cooldown: Duration,
    pub probe_lookups: u64,
}

#[derive(Debug, Clone, Copy, Default)]
struct Bucket {
    index: u64,
    lookups: u64,
    misses: u64,
}

// A ring of time buckets. A slot older than the window is reset when it is next used.
struct MissWindow {
    origin: Instant,
    bucket_len: Duration,
    buckets: [Bucket; WINDOW_BUCKETS],
}

impl MissWindow {
    fn new(origin: Instant, window: Duration) -> Self {
        Self {
            origin,
            bucket_len: (window / WINDOW_BUCKETS as u32).max(Duration::from_millis(1)),
            buckets: [Bucket::default(); WINDOW_BUCKETS],
        }
    }

    fn bucket_index(&self, now: Instant) -> u64 {
        (now.saturating_duration_since(self.origin).as_millis() / self.bucket_len.as_millis())
            as u64
    }

    fn record(&mut self, now: Instant, miss: bool) {
        let index = self.bucket_index(now);
        let bucket = &mut self.buckets[(index % WINDOW_BUCKETS as u64) as usize];
        if bucket.index != index {
            *bucket = Bucket {
                index,
                ..Bucket::default()
            };
        }
        bucket.lookups += 1;
        bucket.misses += u64::from(miss);
    }

    // Callers read the clock before the lock, so `now` can predate a bucket another caller began.
    fn totals(&self, now: Instant) -> (u64, u64) {
        let current = self.bucket_index(now);
        self.buckets
            .iter()
            .filter(|b| b.lookups > 0 && current.saturating_sub(b.index) < WINDOW_BUCKETS as u64)
            .fold((0, 0), |(lookups, misses), b| {
                (lookups + b.lookups, misses + b.misses)
            })
    }

    fn clear(&mut self) {
        self.buckets = [Bucket::default(); WINDOW_BUCKETS];
    }
}

enum BreakerState {
    Closed,
    Open {
        until: Instant,
    },
    HalfOpen {
        deadline: Instant,
        admitted: u64,
        lookups: u64,
        misses: u64,
    },
}

struct TeamBreaker {
    window: MissWindow,
    state: BreakerState,
}

// Per-team breaker on the share of Postgres frame lookups that find no fresh frame. Each
// such lookup costs a resolve and an INSERT, and a failed lookup counts as one. In-memory
// cache hits do not count, so repeated frames cannot dilute a flood, and frames cached
// while the breaker was open cannot close it. While open in `enforce`, cache misses skip
// the frame store. After the cooldown, at most `probe_lookups` misses reach Postgres. Their
// results close the breaker or open it again, and a probe with no result by the next
// cooldown counts as failed.
#[derive(Clone)]
pub struct FrameMissBreaker {
    config: FrameMissBreakerConfig,
    teams: Cache<TeamId, Arc<Mutex<TeamBreaker>>>,
}

impl FrameMissBreaker {
    pub fn new(config: FrameMissBreakerConfig) -> Self {
        let teams = Cache::builder()
            .max_capacity(MAX_TRACKED_TEAMS)
            .time_to_idle(config.window + config.cooldown)
            .build();
        Self { config, teams }
    }

    // Whether a frame cache miss for this team may read and write stored frames.
    pub fn admits(&self, team_id: TeamId, now: Instant) -> bool {
        if self.config.mode == FrameMissBreakerMode::Off {
            return true;
        }
        let breaker = self.team(team_id, now);
        let mut breaker = breaker.lock().unwrap_or_else(|e| e.into_inner());
        let open = match breaker.state {
            BreakerState::Closed => false,
            BreakerState::Open { until } if now < until => true,
            BreakerState::Open { .. } => {
                breaker.state = BreakerState::HalfOpen {
                    deadline: now + self.config.cooldown,
                    admitted: 1,
                    lookups: 0,
                    misses: 0,
                };
                false
            }
            BreakerState::HalfOpen {
                deadline,
                lookups,
                misses,
                ..
            } if now >= deadline => {
                self.open(team_id, &mut breaker, now, lookups, misses);
                true
            }
            BreakerState::HalfOpen {
                ref mut admitted, ..
            } if *admitted < self.config.probe_lookups => {
                *admitted += 1;
                false
            }
            BreakerState::HalfOpen { .. } => true,
        };
        if open {
            metrics::counter!(FRAME_MISS_BREAKER_SKIPPED, "mode" => self.config.mode.as_str())
                .increment(1);
        }
        !(open && self.config.mode == FrameMissBreakerMode::Enforce)
    }

    // Records one Postgres lookup. `miss` means it found no fresh frame or failed. Lookups
    // while open do not count.
    pub fn record(&self, team_id: TeamId, miss: bool, now: Instant) {
        if self.config.mode == FrameMissBreakerMode::Off {
            return;
        }
        let breaker = self.team(team_id, now);
        let mut breaker = breaker.lock().unwrap_or_else(|e| e.into_inner());
        match breaker.state {
            BreakerState::Closed => {
                breaker.window.record(now, miss);
                let (lookups, misses) = breaker.window.totals(now);
                if lookups >= self.config.min_lookups && self.over_threshold(lookups, misses) {
                    self.open(team_id, &mut breaker, now, lookups, misses);
                }
            }
            BreakerState::Open { .. } => {}
            BreakerState::HalfOpen {
                deadline,
                admitted,
                lookups,
                misses,
            } => {
                let lookups = lookups + 1;
                let misses = misses + u64::from(miss);
                if lookups < self.config.probe_lookups {
                    breaker.state = BreakerState::HalfOpen {
                        deadline,
                        admitted,
                        lookups,
                        misses,
                    };
                } else if self.over_threshold(lookups, misses) {
                    self.open(team_id, &mut breaker, now, lookups, misses);
                } else {
                    breaker.window.clear();
                    breaker.state = BreakerState::Closed;
                    info!(
                        team_id,
                        lookups,
                        misses,
                        mode = self.config.mode.as_str(),
                        "frame miss breaker closed"
                    );
                }
            }
        }
    }

    fn team(&self, team_id: TeamId, now: Instant) -> Arc<Mutex<TeamBreaker>> {
        self.teams.get_with(team_id, || {
            Arc::new(Mutex::new(TeamBreaker {
                window: MissWindow::new(now, self.config.window),
                state: BreakerState::Closed,
            }))
        })
    }

    fn over_threshold(&self, lookups: u64, misses: u64) -> bool {
        lookups > 0 && misses as f64 >= self.config.miss_ratio * lookups as f64
    }

    fn open(
        &self,
        team_id: TeamId,
        breaker: &mut TeamBreaker,
        now: Instant,
        lookups: u64,
        misses: u64,
    ) {
        breaker.state = BreakerState::Open {
            until: now + self.config.cooldown,
        };
        let team: Arc<str> = Arc::from(team_id.to_string());
        metrics::counter!(
            FRAME_MISS_BREAKER_OPENED,
            "mode" => self.config.mode.as_str(),
            "team_id" => team,
        )
        .increment(1);
        warn!(
            team_id,
            lookups,
            misses,
            mode = self.config.mode.as_str(),
            "frame miss breaker opened"
        );
    }
}

#[cfg(test)]
mod test {
    use std::time::{Duration, Instant};

    use super::{FrameMissBreaker, FrameMissBreakerConfig, FrameMissBreakerMode};

    const FLOOD_TEAM: i32 = 1;
    const NORMAL_TEAM: i32 = 2;
    const COOLDOWN: Duration = Duration::from_secs(300);

    fn config(mode: FrameMissBreakerMode) -> FrameMissBreakerConfig {
        FrameMissBreakerConfig {
            mode,
            window: Duration::from_secs(60),
            min_lookups: 10,
            miss_ratio: 0.9,
            cooldown: COOLDOWN,
            probe_lookups: 5,
        }
    }

    fn breaker(mode: FrameMissBreakerMode) -> FrameMissBreaker {
        FrameMissBreaker::new(config(mode))
    }

    fn record(breaker: &FrameMissBreaker, team_id: i32, misses: u64, hits: u64, at: Instant) {
        for _ in 0..misses {
            breaker.record(team_id, true, at);
        }
        for _ in 0..hits {
            breaker.record(team_id, false, at);
        }
    }

    #[test]
    fn opens_at_the_threshold_once_the_window_holds_min_lookups() {
        let start = Instant::now();
        for (misses, hits, expect_open) in [(9, 0, false), (9, 1, true), (8, 2, false)] {
            let breaker = breaker(FrameMissBreakerMode::Enforce);
            record(&breaker, FLOOD_TEAM, misses, hits, start);
            assert_eq!(
                !breaker.admits(FLOOD_TEAM, start),
                expect_open,
                "{misses} misses, {hits} hits"
            );
        }
    }

    #[test]
    fn lookups_older_than_the_window_do_not_count() {
        let breaker = breaker(FrameMissBreakerMode::Enforce);
        let start = Instant::now();

        record(&breaker, FLOOD_TEAM, 9, 0, start);
        record(&breaker, FLOOD_TEAM, 1, 0, start + Duration::from_secs(75));

        assert!(breaker.admits(FLOOD_TEAM, start + Duration::from_secs(75)));
    }

    #[test]
    fn stays_open_for_the_cooldown_then_probes() {
        let start = Instant::now();
        for (probe_misses, expect_open_after_probe) in [(5, true), (2, false)] {
            let breaker = breaker(FrameMissBreakerMode::Enforce);
            record(&breaker, FLOOD_TEAM, 10, 0, start);
            assert!(!breaker.admits(FLOOD_TEAM, start + COOLDOWN - Duration::from_secs(1)));

            let probe_at = start + COOLDOWN;
            assert!(breaker.admits(FLOOD_TEAM, probe_at), "{probe_misses}");
            record(
                &breaker,
                FLOOD_TEAM,
                probe_misses,
                5 - probe_misses,
                probe_at,
            );

            assert_eq!(
                !breaker.admits(FLOOD_TEAM, probe_at),
                expect_open_after_probe,
                "{probe_misses} probe misses"
            );
        }
    }

    #[test]
    fn half_open_admits_at_most_the_probe_size() {
        let breaker = breaker(FrameMissBreakerMode::Enforce);
        let start = Instant::now();
        record(&breaker, FLOOD_TEAM, 10, 0, start);

        let probe_at = start + COOLDOWN;
        let admitted: Vec<bool> = (0..6)
            .map(|_| breaker.admits(FLOOD_TEAM, probe_at))
            .collect();

        assert_eq!(admitted, [true, true, true, true, true, false]);
    }

    #[test]
    fn a_probe_without_results_by_the_next_cooldown_reopens() {
        let breaker = breaker(FrameMissBreakerMode::Enforce);
        let start = Instant::now();
        record(&breaker, FLOOD_TEAM, 10, 0, start);

        let probe_at = start + COOLDOWN;
        breaker.admits(FLOOD_TEAM, probe_at);
        record(&breaker, FLOOD_TEAM, 0, 2, probe_at);

        assert!(!breaker.admits(FLOOD_TEAM, probe_at + COOLDOWN));
    }

    #[test]
    fn a_closed_breaker_needs_a_full_window_again_to_reopen() {
        // A cooldown shorter than the window keeps the opening misses in the window.
        let cooldown = Duration::from_secs(30);
        let breaker = FrameMissBreaker::new(FrameMissBreakerConfig {
            cooldown,
            ..config(FrameMissBreakerMode::Enforce)
        });
        let start = Instant::now();
        record(&breaker, FLOOD_TEAM, 10, 0, start);

        let probe_at = start + cooldown;
        breaker.admits(FLOOD_TEAM, probe_at);
        record(&breaker, FLOOD_TEAM, 0, 5, probe_at);
        record(&breaker, FLOOD_TEAM, 9, 0, probe_at);

        assert!(breaker.admits(FLOOD_TEAM, probe_at));
    }

    #[test]
    fn one_team_opening_does_not_affect_another() {
        let breaker = breaker(FrameMissBreakerMode::Enforce);
        let start = Instant::now();

        record(&breaker, FLOOD_TEAM, 10, 0, start);
        record(&breaker, NORMAL_TEAM, 1, 0, start);

        assert!(!breaker.admits(FLOOD_TEAM, start));
        assert!(breaker.admits(NORMAL_TEAM, start));
    }

    #[test]
    fn only_enforce_mode_refuses_postgres() {
        let start = Instant::now();
        for (mode, admitted_while_open) in [
            (FrameMissBreakerMode::Off, true),
            (FrameMissBreakerMode::Log, true),
            (FrameMissBreakerMode::Enforce, false),
        ] {
            let breaker = breaker(mode);
            record(&breaker, FLOOD_TEAM, 10, 0, start);
            assert_eq!(
                breaker.admits(FLOOD_TEAM, start),
                admitted_while_open,
                "{mode:?}"
            );
        }
    }
}
