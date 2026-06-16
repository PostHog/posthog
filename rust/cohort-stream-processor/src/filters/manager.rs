//! `FilterCatalog` + atomic swap + jittered periodic refresh loop.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use arc_swap::{ArcSwap, Guard};
use common_types::cohort::TeamAllowlist;
use lifecycle::Handle;
use metrics::gauge;
use rand::Rng;
use sqlx::PgPool;
use tokio::sync::Notify;
use tracing::{debug, info, warn};

use crate::filters::loader::{build_catalog_from_rows, load_realtime_cohorts, retain_allowlisted};
use crate::filters::reverse_index::TeamFilters;
use crate::filters::{FilterError, TeamId};
use crate::observability::metrics::{FILTER_CATALOG_TEAMS, FILTER_CATALOG_UNIQUE_CONDITIONS};

/// The in-memory view of all realtime cohorts, keyed by team.
#[derive(Debug, Default)]
pub struct FilterCatalog {
    teams: HashMap<TeamId, Arc<TeamFilters>>,
}

impl FilterCatalog {
    pub fn new() -> Self {
        Self {
            teams: HashMap::new(),
        }
    }

    /// The frozen filters for a team, or `None` if it has no realtime cohorts.
    pub fn team(&self, team_id: TeamId) -> Option<&Arc<TeamFilters>> {
        self.teams.get(&team_id)
    }

    pub fn team_count(&self) -> usize {
        self.teams.len()
    }

    /// Total distinct conditionHashes across all teams (sum of the per-team dedup sets).
    pub fn total_unique_conditions(&self) -> usize {
        self.teams
            .values()
            .map(|team| team.unique_condition_hashes.len())
            .sum()
    }

    /// Construct from pre-built per-team filters.
    pub fn from_teams(teams: impl IntoIterator<Item = (TeamId, TeamFilters)>) -> Self {
        Self {
            teams: teams
                .into_iter()
                .map(|(team, filters)| (team, Arc::new(filters)))
                .collect(),
        }
    }
}

/// Snapshot counts returned by [`CatalogHandle::refresh`] for logging.
#[derive(Debug, Clone, Copy)]
pub struct CatalogStats {
    pub teams: usize,
    pub unique_conditions: usize,
}

/// Lock-free, atomically-swapped catalog handle. Starts empty and unloaded; the pipeline fails
/// closed until the first successful refresh.
pub struct CatalogHandle {
    catalog: ArcSwap<FilterCatalog>,
    loaded: AtomicBool,
    /// Wakes [`wait_until_loaded`](Self::wait_until_loaded) waiters on the first successful store.
    loaded_notify: Notify,
    /// Cohorts for teams outside this allowlist never enter the catalog.
    allowlist: TeamAllowlist,
    /// Whether each refresh freezes with cohort-cascade composition enabled.
    cascade_enabled: bool,
}

impl CatalogHandle {
    pub fn new() -> Self {
        Self::with_allowlist(TeamAllowlist::All, false)
    }

    /// The production constructor: gate refreshes to `allowlist`, and freeze with cascade composition
    /// when `cascade_enabled`.
    pub fn with_allowlist(allowlist: TeamAllowlist, cascade_enabled: bool) -> Self {
        Self {
            catalog: ArcSwap::from_pointee(FilterCatalog::new()),
            loaded: AtomicBool::new(false),
            loaded_notify: Notify::new(),
            allowlist,
            cascade_enabled,
        }
    }

    /// Load the current snapshot for a wait-free hot-path read.
    pub fn load(&self) -> Guard<Arc<FilterCatalog>> {
        self.catalog.load()
    }

    /// True once the first refresh has succeeded. Before that the catalog is empty and consumers
    /// should treat every team as having no realtime cohorts.
    pub fn is_loaded(&self) -> bool {
        self.loaded.load(Ordering::Acquire)
    }

    /// Resolve once the first refresh has succeeded; immediate if it already has.
    pub async fn wait_until_loaded(&self) {
        while !self.is_loaded() {
            // Register the waiter *before* re-checking, so a store that lands between the check and
            // the await still wakes us (`notify_waiters` reaches futures created before the call).
            let notified = self.loaded_notify.notified();
            if self.is_loaded() {
                return;
            }
            notified.await;
        }
    }

    /// Build an already-loaded handle from a prebuilt catalog (test seam).
    pub fn from_catalog(catalog: FilterCatalog) -> Self {
        let handle = Self::new();
        handle.store(catalog);
        handle
    }

    fn store(&self, catalog: FilterCatalog) {
        gauge!(FILTER_CATALOG_TEAMS).set(catalog.team_count() as f64);
        gauge!(FILTER_CATALOG_UNIQUE_CONDITIONS).set(catalog.total_unique_conditions() as f64);
        self.catalog.store(Arc::new(catalog));
        self.loaded.store(true, Ordering::Release);
        self.loaded_notify.notify_waiters();
    }

    /// Query `posthog_cohort`, drop out-of-scope teams, rebuild the catalog, and swap it in.
    pub async fn refresh(&self, pool: &PgPool) -> Result<CatalogStats, FilterError> {
        let mut rows = load_realtime_cohorts(pool).await?;
        let fetched_rows = rows.len();
        retain_allowlisted(&mut rows, &self.allowlist);
        if rows.len() != fetched_rows {
            debug!(
                fetched_rows,
                kept_rows = rows.len(),
                "filter catalog dropped cohort rows outside REALTIME_COHORT_TEAM_ALLOWLIST",
            );
        }
        let catalog = build_catalog_from_rows(rows, self.cascade_enabled);
        let stats = CatalogStats {
            teams: catalog.team_count(),
            unique_conditions: catalog.total_unique_conditions(),
        };
        self.store(catalog);
        Ok(stats)
    }
}

impl Default for CatalogHandle {
    fn default() -> Self {
        Self::new()
    }
}

/// Periodic catalog refresh task. On failure, keeps the previous snapshot and retries next tick.
pub async fn run_refresh_loop(
    catalog: Arc<CatalogHandle>,
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
            _ = tokio::time::sleep(sleep_for) => match catalog.refresh(&pool).await {
                Ok(stats) => info!(
                    teams = stats.teams,
                    unique_conditions = stats.unique_conditions,
                    "filter catalog refreshed",
                ),
                Err(err) => warn!(
                    error = %err,
                    "filter catalog refresh failed; keeping previous snapshot",
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
    let millis = rand::thread_rng().gen_range(lo..=hi);
    Duration::from_millis(millis)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::json;

    use crate::filters::reverse_index::TeamFiltersBuilder;
    use crate::filters::CohortId;

    fn team_with_one_behavioral() -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        let filters = json!({
            "properties": {
                "type": "AND",
                "values": [{
                    "type": "behavioral",
                    "value": "performed_event",
                    "key": "$pageview",
                    "time_value": 7,
                    "time_interval": "day",
                    "conditionHash": "0123456789abcdef",
                    "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
                }],
            }
        });
        builder
            .add_cohort(CohortId(1), TeamId(7), &filters)
            .unwrap();
        builder.freeze(UTC)
    }

    #[test]
    fn new_handle_is_unloaded_and_empty() {
        let handle = CatalogHandle::new();
        assert!(!handle.is_loaded());
        assert_eq!(handle.load().team_count(), 0);
    }

    #[test]
    fn from_catalog_marks_loaded_and_populates_teams() {
        let catalog = FilterCatalog::from_teams([(TeamId(7), team_with_one_behavioral())]);
        let handle = CatalogHandle::from_catalog(catalog);

        assert!(handle.is_loaded());
        let snapshot = handle.load();
        assert_eq!(snapshot.team_count(), 1);
        assert!(snapshot.team(TeamId(7)).is_some());
        assert!(snapshot.team(TeamId(8)).is_none());
        assert_eq!(snapshot.total_unique_conditions(), 1);
    }

    #[tokio::test]
    async fn wait_until_loaded_resolves_on_the_first_store_and_immediately_after() {
        let handle = Arc::new(CatalogHandle::new());

        let waiter = {
            let handle = handle.clone();
            tokio::spawn(async move { handle.wait_until_loaded().await })
        };
        // The waiter cannot resolve before the first store.
        tokio::task::yield_now().await;
        assert!(!waiter.is_finished());

        handle.store(FilterCatalog::from_teams([(
            TeamId(7),
            team_with_one_behavioral(),
        )]));
        waiter.await.expect("waiter resolves on the first store");

        // Already loaded → immediate.
        handle.wait_until_loaded().await;
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
            let sleep_for = next_interval(interval, jitter);
            assert!(
                sleep_for >= Duration::from_secs(240),
                "{sleep_for:?} below bound"
            );
            assert!(
                sleep_for <= Duration::from_secs(360),
                "{sleep_for:?} above bound"
            );
        }
    }

    /// Requires a live Postgres; run with `cargo test -p cohort-stream-processor -- --ignored`.
    #[tokio::test]
    #[ignore]
    async fn refresh_builds_catalog_from_live_postgres() {
        let url = std::env::var("DATABASE_URL")
            .unwrap_or_else(|_| "postgres://posthog:posthog@localhost:5432/posthog".to_string());
        let pool =
            common_database::get_pool_with_config(&url, common_database::PoolConfig::default())
                .expect("build posthog_cohort pool");

        let handle = CatalogHandle::new();
        assert!(!handle.is_loaded());

        let stats = handle
            .refresh(&pool)
            .await
            .expect("refresh against live posthog_cohort");

        assert!(handle.is_loaded());
        assert_eq!(handle.load().team_count(), stats.teams);
    }
}
