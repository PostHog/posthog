//! In-memory index of teams with ≥1 realtime-supported cohort, consulted by the consumer's team
//! gate. Refreshed on a `refresh_secs ± jitter` poll and swapped atomically via
//! [`arc_swap::ArcSwap`] so hot-path reads are lock-free and a refresh never blocks the consumer.
//!
//! Staleness is safe: the gate is defense-in-depth and the downstream processor re-checks
//! membership, so a stale snapshot only over-forwards briefly. The index starts empty and unloaded
//! so nothing is forwarded until the first refresh — avoiding a cold-start flood if the DB is
//! briefly unreachable at boot.

use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use arc_swap::ArcSwap;
use common_types::cohort::TeamAllowlist;
use lifecycle::Handle;
use metrics::gauge;
use rand::Rng;
use sqlx::PgPool;
use tracing::{debug, info, warn};

use crate::observability::metrics::ACTIVE_TEAMS;

/// Must match the Node filter manager's predicate (`cohort_type='realtime'`, not deleted, non-null
/// `filters`); projected to `DISTINCT team_id` since the shuffler only needs the gate.
const TEAMS_WITH_REALTIME_COHORTS_SQL: &str = "SELECT DISTINCT team_id \
     FROM posthog_cohort \
     WHERE cohort_type = 'realtime' AND deleted = false AND filters IS NOT NULL";

pub struct TeamIndex {
    teams: ArcSwap<HashSet<i32>>,
    loaded: AtomicBool,
    /// Applied at [`refresh`](Self::refresh) time: teams the DB reports as realtime but outside this
    /// allowlist never enter the snapshot, so the hot-path gate and the `ACTIVE_TEAMS` gauge both
    /// reflect the scoped set for free.
    allowlist: TeamAllowlist,
}

impl TeamIndex {
    pub fn new() -> Self {
        Self::with_allowlist(TeamAllowlist::All)
    }

    pub fn with_allowlist(allowlist: TeamAllowlist) -> Self {
        Self {
            teams: ArcSwap::from_pointee(HashSet::new()),
            loaded: AtomicBool::new(false),
            allowlist,
        }
    }

    pub fn contains(&self, team_id: i32) -> bool {
        self.teams.load().contains(&team_id)
    }

    /// False until the first refresh succeeds, while the set is empty and nothing should forward.
    pub fn is_loaded(&self) -> bool {
        self.loaded.load(Ordering::Acquire)
    }

    pub fn len(&self) -> usize {
        self.teams.load().len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Test seam: an already-loaded index without a DB. Production loads via [`refresh`](Self::refresh).
    pub fn from_teams(teams: impl IntoIterator<Item = i32>) -> Self {
        let index = Self::new();
        index.store(teams.into_iter().collect());
        index
    }

    fn store(&self, teams: HashSet<i32>) {
        gauge!(ACTIVE_TEAMS).set(teams.len() as f64);
        self.teams.store(Arc::new(teams));
        self.loaded.store(true, Ordering::Release);
    }

    pub async fn refresh(&self, pool: &PgPool) -> Result<usize> {
        let fetched: Vec<i32> = sqlx::query_scalar(TEAMS_WITH_REALTIME_COHORTS_SQL)
            .fetch_all(pool)
            .await
            .context("querying posthog_cohort for realtime teams")?;
        let fetched_count = fetched.len();
        let kept = filter_by_allowlist(fetched, &self.allowlist);
        if kept.len() != fetched_count {
            debug!(
                fetched = fetched_count,
                kept = kept.len(),
                excluded = fetched_count - kept.len(),
                "team index filtered realtime teams by the allowlist",
            );
        }
        let count = kept.len();
        self.store(kept);
        Ok(count)
    }
}

/// Keep only the teams in scope. Separated from [`TeamIndex::refresh`] so the allowlist filter is
/// testable without a database.
fn filter_by_allowlist(fetched: Vec<i32>, allowlist: &TeamAllowlist) -> HashSet<i32> {
    fetched
        .into_iter()
        .filter(|team_id| allowlist.includes(*team_id))
        .collect()
}

impl Default for TeamIndex {
    fn default() -> Self {
        Self::new()
    }
}

/// Sleeps `interval ± jitter` between refreshes to spread DB load across pods. On failure it keeps
/// serving the previous snapshot — staleness is safe — and retries next tick.
///
/// Registered without a liveness deadline: a refresh outage must not kill the service (that stops
/// forwarding entirely, worse than a stale gate). An unexpected exit still drops the process-scope
/// guard and signals the manager.
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
                    warn!(
                        "team index has zero in-scope teams (no realtime cohorts, or all filtered \
                         by REALTIME_COHORT_TEAM_ALLOWLIST); forwarding nothing",
                    );
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

fn next_interval(interval: Duration, jitter: Duration) -> Duration {
    if jitter.is_zero() {
        return interval;
    }
    let lo = interval.saturating_sub(jitter).as_millis() as u64;
    let hi = interval.saturating_add(jitter).as_millis() as u64;
    // Drop the non-Send `ThreadRng` before returning so it never spans an await.
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
    fn filter_by_allowlist_all_keeps_everything() {
        let kept = filter_by_allowlist(vec![1, 2, 99], &TeamAllowlist::All);
        assert_eq!(kept, HashSet::from([1, 2, 99]));
    }

    #[test]
    fn filter_by_allowlist_only_drops_out_of_scope_teams() {
        let kept = filter_by_allowlist(vec![1, 2, 99], &TeamAllowlist::Only(HashSet::from([2])));
        assert_eq!(kept, HashSet::from([2]));
    }

    #[test]
    fn filter_by_allowlist_empty_scope_keeps_nothing() {
        let kept = filter_by_allowlist(vec![1, 2, 99], &TeamAllowlist::Only(HashSet::new()));
        assert!(kept.is_empty());
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
