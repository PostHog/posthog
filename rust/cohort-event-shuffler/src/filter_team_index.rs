//! In-memory index of teams with ≥1 realtime-supported cohort (TDD §2.2, step 3).
//!
//! The consumer consults [`TeamIndex::contains`] before forwarding an event — the team gate
//! that mirrors `realtime-supported-filter-manager-cdp.ts:219-222`. The set is refreshed on a
//! `refresh_secs ± jitter` poll and swapped atomically via [`arc_swap::ArcSwap`], so the hot
//! path reads are lock-free and a refresh never blocks the consumer.
//!
//! Staleness is safe by design (key design point 4): the gate is defense-in-depth and Stage 1
//! re-checks team membership (TDD §2.4), so a ≤5-min-stale snapshot only over-forwards briefly.
//! The index starts **empty and unloaded**, so nothing is forwarded until the first successful
//! refresh — avoiding a cold-start flood if the DB is briefly unreachable at boot.

use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use arc_swap::ArcSwap;
use lifecycle::Handle;
use metrics::gauge;
use rand::Rng;
use sqlx::PgPool;
use tracing::{info, warn};

use crate::observability::metrics::ACTIVE_TEAMS;

/// Teams with ≥1 realtime-supported cohort. Mirrors the Node filter manager's predicate
/// (`realtime-supported-filter-manager-cdp.ts:77-91`): `cohort_type='realtime'`, not deleted,
/// non-null `filters`. Projected to `DISTINCT team_id` because the shuffler only needs the
/// gate, not the per-cohort filter payloads.
const TEAMS_WITH_REALTIME_COHORTS_SQL: &str = "SELECT DISTINCT team_id \
     FROM posthog_cohort \
     WHERE cohort_type = 'realtime' AND deleted = false AND filters IS NOT NULL";

/// Lock-free, atomically-swapped set of realtime-cohort teams.
pub struct TeamIndex {
    teams: ArcSwap<HashSet<i32>>,
    loaded: AtomicBool,
}

impl TeamIndex {
    pub fn new() -> Self {
        Self {
            teams: ArcSwap::from_pointee(HashSet::new()),
            loaded: AtomicBool::new(false),
        }
    }

    /// True if `team_id` has ≥1 realtime cohort as of the last successful refresh.
    pub fn contains(&self, team_id: i32) -> bool {
        self.teams.load().contains(&team_id)
    }

    /// True once the first refresh has succeeded. Before that the set is empty and the
    /// consumer should forward nothing.
    pub fn is_loaded(&self) -> bool {
        self.loaded.load(Ordering::Acquire)
    }

    /// Number of teams in the current snapshot.
    pub fn len(&self) -> usize {
        self.teams.load().len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Build an already-loaded index from an explicit team set. Production loads via
    /// [`refresh`](Self::refresh) against `posthog_cohort`; this constructor is the seam for
    /// tests (and any future static-config mode) that need a populated index without a DB.
    pub fn from_teams(teams: impl IntoIterator<Item = i32>) -> Self {
        let index = Self::new();
        index.store(teams.into_iter().collect());
        index
    }

    /// Atomically install a new snapshot, mark the index loaded, and publish the gauge.
    fn store(&self, teams: HashSet<i32>) {
        gauge!(ACTIVE_TEAMS).set(teams.len() as f64);
        self.teams.store(Arc::new(teams));
        self.loaded.store(true, Ordering::Release);
    }

    /// Query `posthog_cohort` and swap in the fresh team set. Returns the team count.
    pub async fn refresh(&self, pool: &PgPool) -> Result<usize> {
        let rows: Vec<i32> = sqlx::query_scalar(TEAMS_WITH_REALTIME_COHORTS_SQL)
            .fetch_all(pool)
            .await
            .context("querying posthog_cohort for realtime teams")?;
        let count = rows.len();
        self.store(rows.into_iter().collect());
        Ok(count)
    }
}

impl Default for TeamIndex {
    fn default() -> Self {
        Self::new()
    }
}

/// Periodic team-index refresh task (TDD §2.2). Sleeps `interval ± jitter` between refreshes
/// to spread DB load across pods (matches the Node `LazyLoader` jitter at
/// `realtime-supported-filter-manager-cdp.ts:38-39`). On failure it keeps serving the previous
/// snapshot — staleness is safe — and retries on the next tick.
///
/// Registered as a `lifecycle` component without a liveness deadline: a refresh outage must not
/// kill the service (that would stop forwarding entirely, which is worse than a stale gate). An
/// unexpected exit of this task, however, drops the process-scope guard and signals the manager.
pub async fn run_refresh_loop(
    index: Arc<TeamIndex>,
    pool: PgPool,
    interval: Duration,
    jitter: Duration,
    handle: Handle,
) {
    let _guard = handle.process_scope();

    loop {
        let sleep_for = next_interval(interval, jitter);
        tokio::select! {
            _ = handle.shutdown_recv() => break,
            _ = tokio::time::sleep(sleep_for) => match index.refresh(&pool).await {
                Ok(0) => {
                    warn!("team index refreshed with zero realtime teams; forwarding nothing");
                }
                Ok(count) => info!(active_teams = count, "team index refreshed"),
                Err(err) => warn!(
                    error = %err,
                    "team index refresh failed; keeping previous snapshot",
                ),
            },
        }
    }
}

/// A sleep duration uniformly in `[interval - jitter, interval + jitter]`.
fn next_interval(interval: Duration, jitter: Duration) -> Duration {
    if jitter.is_zero() {
        return interval;
    }
    let lo = interval.saturating_sub(jitter).as_millis() as u64;
    let hi = interval.saturating_add(jitter).as_millis() as u64;
    // Scoped so the non-Send `ThreadRng` is dropped before any later await in the caller.
    let millis = rand::thread_rng().gen_range(lo..=hi);
    Duration::from_millis(millis)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_index_is_unloaded_and_empty() {
        let index = TeamIndex::new();
        assert!(!index.is_loaded());
        assert!(index.is_empty());
        assert!(!index.contains(2));
    }

    #[test]
    fn store_marks_loaded_and_updates_membership() {
        let index = TeamIndex::new();
        index.store(HashSet::from([1, 2, 42]));

        assert!(index.is_loaded());
        assert_eq!(index.len(), 3);
        assert!(index.contains(1));
        assert!(index.contains(42));
        assert!(!index.contains(3));
    }

    #[test]
    fn store_replaces_the_previous_snapshot() {
        let index = TeamIndex::new();
        index.store(HashSet::from([1, 2]));
        index.store(HashSet::from([3]));

        assert!(!index.contains(1));
        assert!(index.contains(3));
        assert_eq!(index.len(), 1);
    }

    #[test]
    fn next_interval_without_jitter_is_exact() {
        let interval = Duration::from_secs(300);
        assert_eq!(next_interval(interval, Duration::ZERO), interval);
    }

    #[test]
    fn next_interval_stays_within_jitter_band() {
        let interval = Duration::from_secs(300);
        let jitter = Duration::from_secs(60);
        for _ in 0..1000 {
            let d = next_interval(interval, jitter);
            assert!(d >= Duration::from_secs(240), "{d:?} below lower bound");
            assert!(d <= Duration::from_secs(360), "{d:?} above upper bound");
        }
    }
}
