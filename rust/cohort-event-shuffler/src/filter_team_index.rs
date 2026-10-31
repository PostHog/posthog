//! In-memory index of teams with ≥1 realtime-supported cohort, and the consumer's [`TeamGate`]
//! that joins it with the team access record. Refreshed on a `refresh_secs ± jitter` poll and
//! swapped atomically via [`arc_swap::ArcSwap`] so hot-path reads are lock-free and a refresh never
//! blocks the consumer.
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
use common_cohort_team_access::TeamAccess;
use lifecycle::Handle;
use rand::Rng;
use sqlx::PgPool;
use tracing::{info, warn};

/// Must match the Node filter manager's predicate (`cohort_type='realtime'`, not deleted, non-null
/// `filters`); projected to `DISTINCT team_id` since the shuffler only needs the gate.
const TEAMS_WITH_REALTIME_COHORTS_SQL: &str = "SELECT DISTINCT team_id \
     FROM posthog_cohort \
     WHERE cohort_type = 'realtime' AND deleted = false AND filters IS NOT NULL";

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
        self.teams.store(Arc::new(teams));
        self.loaded.store(true, Ordering::Release);
    }

    pub async fn refresh(&self, pool: &PgPool) -> Result<usize> {
        let fetched: HashSet<i32> = sqlx::query_scalar(TEAMS_WITH_REALTIME_COHORTS_SQL)
            .fetch_all(pool)
            .await
            .context("querying posthog_cohort for realtime teams")?
            .into_iter()
            .collect();
        let count = fetched.len();
        self.store(fetched);
        Ok(count)
    }
}

impl Default for TeamIndex {
    fn default() -> Self {
        Self::new()
    }
}

/// Passes an event when its team processes and has a realtime cohort. The index and the access
/// record refresh on their own polls. Neither rebuilds the other's snapshot, because two writers
/// to one snapshot can lose an update and bring back a revoked team.
pub struct TeamGate {
    index: Arc<TeamIndex>,
    access: Arc<TeamAccess>,
}

impl TeamGate {
    pub fn new(index: Arc<TeamIndex>, access: Arc<TeamAccess>) -> Self {
        Self { index, access }
    }

    pub fn passes(&self, team_id: i32) -> bool {
        self.index.contains(team_id) && self.access.processing(team_id)
    }

    /// False until both halves have loaded once.
    pub fn is_loaded(&self) -> bool {
        self.index.is_loaded() && self.access.is_loaded()
    }

    pub fn passing_teams(&self) -> usize {
        self.index
            .teams
            .load()
            .iter()
            .filter(|&&team_id| self.access.processing(team_id))
            .count()
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
                Ok(0) => warn!("team index has no team with a realtime cohort; forwarding nothing"),
                Ok(count) => info!(realtime_teams = count, "team index refreshed"),
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
    use common_types::cohort::TeamAllowlist;

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
    fn gate_passes_teams_that_process_and_have_a_realtime_cohort() {
        let gate = TeamGate::new(
            Arc::new(TeamIndex::from_teams([2, 5, 6])),
            TeamAccess::with_granted(TeamAllowlist::Only(HashSet::from([2, 3])), [5]),
        );

        for (team_id, expected) in [(2, true), (3, false), (5, true), (6, false), (7, false)] {
            assert_eq!(gate.passes(team_id), expected, "team {team_id}");
        }
        assert_eq!(gate.passing_teams(), 2);
    }

    #[test]
    fn gate_is_loaded_only_once_both_halves_are() {
        let (unloaded_access, _poller) = TeamAccess::new(TeamAllowlist::All);
        let loaded_access = TeamAccess::with_granted(TeamAllowlist::All, []);

        let index_only = TeamGate::new(Arc::new(TeamIndex::from_teams([2])), unloaded_access);
        let access_only = TeamGate::new(Arc::new(TeamIndex::new()), loaded_access.clone());
        let both = TeamGate::new(Arc::new(TeamIndex::from_teams([2])), loaded_access);

        assert!(!index_only.is_loaded());
        assert!(!index_only.passes(2));
        assert!(!access_only.is_loaded());
        assert!(both.is_loaded());
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
