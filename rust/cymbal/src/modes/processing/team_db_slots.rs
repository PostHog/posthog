//! A per-team count of the Postgres connections that a team's work holds, kept in each pod.
//!
//! The error tracking consumer hashes each team to one Cymbal pod, so the count in a pod is the
//! team's count across the fleet. A slot is taken before the wait for a pool connection and is
//! released with the connection, so the count includes calls that wait for the pool.
//!
//! In `log` mode the count is only measured. A team whose count goes over its limit is marked hot
//! for a short window, and the events that arrive for it in that window are counted.

use std::{
    collections::HashMap,
    ops::{Deref, DerefMut},
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Mutex, MutexGuard,
    },
    time::{Duration, Instant},
};

use sqlx::{pool::PoolConnection, PgConnection, PgPool, Postgres};
use tracing::warn;

use crate::{
    error::UnhandledError,
    metric_consts::{
        TEAM_DB_SLOTS_CALLS, TEAM_DB_SLOTS_HOT_EVENTS, TEAM_DB_SLOTS_IN_FLIGHT, TEAM_DB_SLOTS_TEAMS,
    },
    modes::processing::config::ProcessingConfig,
    types::operator::TeamId,
};

const SWEEP_INTERVAL: Duration = Duration::from_secs(1);
const WARN_INTERVAL: Duration = Duration::from_secs(60);

pub struct TeamDbSlots {
    default_limit: usize,
    overrides: HashMap<TeamId, usize>,
    hot_window: Duration,
    state: Mutex<State>,
}

struct State {
    teams: HashMap<TeamId, TeamUsage>,
    last_sweep: Instant,
}

#[derive(Default)]
struct TeamUsage {
    in_flight: Arc<AtomicUsize>,
    hot_until: Option<Instant>,
    quiet_until: Option<Instant>,
}

struct SlotGuard(Arc<AtomicUsize>);

impl Drop for SlotGuard {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::Relaxed);
    }
}

/// A pooled connection that holds one of its team's slots until it goes back to the pool.
pub struct TeamConnection {
    conn: PoolConnection<Postgres>,
    _slot: Option<SlotGuard>,
}

impl Deref for TeamConnection {
    type Target = PgConnection;

    fn deref(&self) -> &PgConnection {
        &self.conn
    }
}

impl DerefMut for TeamConnection {
    fn deref_mut(&mut self) -> &mut PgConnection {
        &mut self.conn
    }
}

/// Checks out a pool connection that holds one of the team's slots. With `slots` off, it is a
/// plain pool checkout.
pub async fn acquire_connection(
    slots: Option<&TeamDbSlots>,
    pool: &PgPool,
    team_id: TeamId,
) -> Result<TeamConnection, sqlx::Error> {
    let slot = slots.map(|slots| slots.acquire_at(team_id, Instant::now()));
    let conn = pool.acquire().await?;
    Ok(TeamConnection { conn, _slot: slot })
}

impl TeamDbSlots {
    pub fn from_config(config: &ProcessingConfig) -> Result<Option<Arc<Self>>, UnhandledError> {
        match config.team_db_slots_mode.as_str() {
            "off" => return Ok(None),
            "log" => {}
            other => {
                return Err(UnhandledError::Other(format!(
                    "invalid CYMBAL_TEAM_DB_SLOTS_MODE: {other} (expected off or log)"
                )))
            }
        }
        if config.team_db_slots == 0 {
            return Err(UnhandledError::Other(
                "CYMBAL_TEAM_DB_SLOTS must be at least 1".to_string(),
            ));
        }
        let overrides = parse_overrides(&config.team_db_slots_overrides)?;
        Ok(Some(Arc::new(Self::new(
            config.team_db_slots,
            overrides,
            Duration::from_secs(config.team_hot_window_secs),
        ))))
    }

    fn new(default_limit: usize, overrides: HashMap<TeamId, usize>, hot_window: Duration) -> Self {
        Self {
            default_limit,
            overrides,
            hot_window,
            state: Mutex::new(State {
                teams: HashMap::new(),
                last_sweep: Instant::now(),
            }),
        }
    }

    pub fn is_hot(&self, team_id: TeamId) -> bool {
        self.is_hot_at(team_id, Instant::now())
    }

    /// Counts the events whose team is hot.
    pub fn record_hot_arrivals(&self, team_ids: impl IntoIterator<Item = TeamId>) {
        self.record_hot_arrivals_at(team_ids, Instant::now());
    }

    fn acquire_at(&self, team_id: TeamId, now: Instant) -> SlotGuard {
        let limit = self.limit(team_id);
        let mut state = self.lock(now);
        let usage = state.teams.entry(team_id).or_default();
        let in_flight = usage.in_flight.fetch_add(1, Ordering::Relaxed) + 1;
        let over_limit = in_flight > limit;
        let warn_now = over_limit && usage.quiet_until.is_none_or(|quiet| now >= quiet);
        if over_limit {
            usage.hot_until = usage.hot_until.max(Some(now + self.hot_window));
        }
        if warn_now {
            usage.quiet_until = Some(now + WARN_INTERVAL);
        }
        let guard = SlotGuard(usage.in_flight.clone());
        drop(state);

        metrics::histogram!(TEAM_DB_SLOTS_IN_FLIGHT).record(in_flight as f64);
        if over_limit {
            metrics::counter!(TEAM_DB_SLOTS_CALLS, "outcome" => "over_limit").increment(1);
        } else {
            metrics::counter!(TEAM_DB_SLOTS_CALLS, "outcome" => "within").increment(1);
        }
        if warn_now {
            warn!(
                team_id,
                in_flight, limit, "Team is over its database slot limit"
            );
        }
        guard
    }

    fn is_hot_at(&self, team_id: TeamId, now: Instant) -> bool {
        self.lock(now).is_hot(team_id, now)
    }

    fn record_hot_arrivals_at(&self, team_ids: impl IntoIterator<Item = TeamId>, now: Instant) {
        let mut events_per_team: HashMap<TeamId, u64> = HashMap::new();
        for team_id in team_ids {
            *events_per_team.entry(team_id).or_default() += 1;
        }
        let state = self.lock(now);
        let hot_events: u64 = events_per_team
            .iter()
            .filter(|(team_id, _)| state.is_hot(**team_id, now))
            .map(|(_, events)| events)
            .sum();
        drop(state);
        if hot_events > 0 {
            metrics::counter!(TEAM_DB_SLOTS_HOT_EVENTS).increment(hot_events);
        }
    }

    fn lock(&self, now: Instant) -> MutexGuard<'_, State> {
        let mut state = self.state.lock().expect("team db slots mutex poisoned");
        if now.saturating_duration_since(state.last_sweep) >= SWEEP_INTERVAL {
            // Each guard holds a clone of its team's count, so a count with one owner has nothing
            // in flight. Removing a count that a guard still holds would start a second count for
            // the same team.
            state.teams.retain(|_, usage| {
                Arc::strong_count(&usage.in_flight) > 1
                    || usage.hot_until.is_some_and(|until| until > now)
                    || usage.quiet_until.is_some_and(|until| until > now)
            });
            state.last_sweep = now;
            metrics::gauge!(TEAM_DB_SLOTS_TEAMS).set(state.teams.len() as f64);
        }
        state
    }

    fn limit(&self, team_id: TeamId) -> usize {
        self.overrides
            .get(&team_id)
            .copied()
            .unwrap_or(self.default_limit)
    }
}

impl State {
    fn is_hot(&self, team_id: TeamId, now: Instant) -> bool {
        self.teams
            .get(&team_id)
            .and_then(|usage| usage.hot_until)
            .is_some_and(|until| until > now)
    }
}

/// Parses `team:limit` pairs. A typo must stop startup, because a skipped entry would silently
/// give that team the default limit.
fn parse_overrides(value: &str) -> Result<HashMap<TeamId, usize>, UnhandledError> {
    let mut overrides = HashMap::new();
    for entry in value.split(',').map(str::trim).filter(|e| !e.is_empty()) {
        let invalid = || {
            UnhandledError::Other(format!(
                "invalid entry {entry:?} in CYMBAL_TEAM_DB_SLOTS_OVERRIDES (expected team:limit, limit at least 1)"
            ))
        };
        let (team, limit) = entry.split_once(':').ok_or_else(invalid)?;
        let team: TeamId = team.trim().parse().map_err(|_| invalid())?;
        let limit: usize = limit.trim().parse().map_err(|_| invalid())?;
        if limit == 0 || overrides.insert(team, limit).is_some() {
            return Err(invalid());
        }
    }
    Ok(overrides)
}

#[cfg(test)]
mod tests {
    use super::*;

    const WINDOW: Duration = Duration::from_secs(10);

    fn slots(default_limit: usize, overrides: &[(TeamId, usize)]) -> TeamDbSlots {
        TeamDbSlots::new(default_limit, overrides.iter().copied().collect(), WINDOW)
    }

    #[test]
    fn a_team_turns_hot_only_when_its_own_calls_exceed_its_limit() {
        let slots = slots(2, &[(3, 4)]);
        let now = Instant::now();

        let first = slots.acquire_at(1, now);
        drop(slots.acquire_at(1, now));
        let _second = slots.acquire_at(1, now);
        let _other_team = slots.acquire_at(2, now);
        assert!(!slots.is_hot_at(1, now), "a released slot still counted");

        let _third = slots.acquire_at(1, now);
        assert!(slots.is_hot_at(1, now));
        assert!(
            !slots.is_hot_at(2, now),
            "one team's calls counted for another"
        );

        let _overridden: Vec<_> = (0..4).map(|_| slots.acquire_at(3, now)).collect();
        assert!(
            !slots.is_hot_at(3, now),
            "the override limit was not applied"
        );
        drop(first);
    }

    #[test]
    fn a_hot_team_cools_down_after_the_window() {
        let slots = slots(1, &[]);
        let now = Instant::now();
        {
            let _a = slots.acquire_at(1, now);
            let _b = slots.acquire_at(1, now);
        }

        assert!(slots.is_hot_at(1, now + WINDOW - Duration::from_millis(1)));
        assert!(!slots.is_hot_at(1, now + WINDOW));
    }

    #[test]
    fn the_sweep_keeps_held_and_hot_teams_and_drops_idle_ones() {
        let slots = slots(1, &[]);
        let now = Instant::now();
        let held = slots.acquire_at(1, now);
        {
            let _a = slots.acquire_at(2, now);
            let _b = slots.acquire_at(2, now);
        }
        drop(slots.acquire_at(3, now));

        let later = now + SWEEP_INTERVAL;
        let _second = slots.acquire_at(1, later);

        assert!(
            slots.is_hot_at(1, later),
            "the sweep dropped a held slot, so the team's count restarted"
        );
        let teams = slots.state.lock().unwrap().teams.len();
        assert_eq!(teams, 2, "expected only the held team 1 and the hot team 2");
        drop(held);
    }

    #[test]
    fn overrides_parse_strictly() {
        assert_eq!(
            parse_overrides(" 1:5, 2:3 ,").unwrap(),
            HashMap::from([(1, 5), (2, 3)])
        );
        for bad in ["1", "x:1", "1:x", "1:0", "1:2,1:3"] {
            assert!(parse_overrides(bad).is_err(), "{bad:?} was accepted");
        }
    }
}
