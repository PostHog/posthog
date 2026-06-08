//! `FilterCatalog` + atomic swap + refresh loop.
//!
//! Mirrors `rust/cohort-event-shuffler/src/filter_team_index.rs`: a lock-free
//! [`arc_swap::ArcSwap`] snapshot, an `is_loaded` fail-closed gate, and a jittered refresh task.
//! The refresh task has no liveness deadline — a refresh outage keeps the last good snapshot rather
//! than killing the service, since staleness is safe.

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
use tracing::{debug, info, warn};

use crate::filters::loader::{build_catalog_from_rows, load_realtime_cohorts, retain_allowlisted};
use crate::filters::reverse_index::TeamFilters;
use crate::filters::{FilterError, TeamId};
use crate::observability::metrics::{FILTER_CATALOG_TEAMS, FILTER_CATALOG_UNIQUE_CONDITIONS};

/// The in-memory view of all realtime cohorts, keyed by team. Each team's filters are an `Arc` so
/// the hot path can cheaply hold a per-team handle across an event batch.
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

    /// The construction seam used by
    /// [`build_catalog_from_rows`](crate::filters::loader::build_catalog_from_rows) and tests.
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

/// Lock-free, atomically-swapped catalog handle: hot-path reads via [`load`](Self::load) are
/// wait-free, and a refresh swaps a fresh `Arc<FilterCatalog>` without blocking readers. Starts
/// empty and unloaded so the pipeline fails closed until the first successful refresh, mirroring the
/// shuffler's `TeamIndex`.
pub struct CatalogHandle {
    catalog: ArcSwap<FilterCatalog>,
    loaded: AtomicBool,
    /// Applied at [`refresh`](Self::refresh) time: cohorts for teams outside this allowlist never
    /// enter the catalog, so per-team lookups, the `FILTER_CATALOG_TEAMS` gauge, and shadow output
    /// all reflect the scoped set for free.
    allowlist: TeamAllowlist,
}

impl CatalogHandle {
    pub fn new() -> Self {
        Self::with_allowlist(TeamAllowlist::All)
    }

    /// The production constructor: gate refreshes to `allowlist`.
    pub fn with_allowlist(allowlist: TeamAllowlist) -> Self {
        Self {
            catalog: ArcSwap::from_pointee(FilterCatalog::new()),
            loaded: AtomicBool::new(false),
            allowlist,
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

    /// Build an already-loaded handle from a prebuilt catalog — the test seam; production loads via
    /// [`refresh`](Self::refresh).
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
        let catalog = build_catalog_from_rows(rows);
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

/// Periodic catalog refresh task. Sleeps `interval ± jitter` to spread DB load across pods. On
/// failure it keeps serving the previous snapshot (staleness is safe) and retries next tick.
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

/// A sleep duration uniformly in `[interval - jitter, interval + jitter]`. Copied from the
/// shuffler's `filter_team_index::next_interval`.
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

    /// Live-DB smoke test of the refresh path. `#[ignore]` because CI runs this crate without
    /// Postgres; run against a local stack with `cargo test -p cohort-stream-processor -- --ignored`.
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
