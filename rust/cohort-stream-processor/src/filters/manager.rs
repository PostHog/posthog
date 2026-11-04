//! `FilterCatalog` + atomic swap + the refresher that rebuilds it on a team access change or a
//! jittered period.

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use arc_swap::{ArcSwap, Guard};
use common_cohort_team_access::{
    next_poll_delay, PollError, ProcessingTeams, TeamAccess, TeamAccessPoller,
};
use common_types::cohort::TeamAllowlist;
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rand::Rng;
use sqlx::PgPool;
use thiserror::Error;
use tokio::sync::Notify;
use tokio::task::JoinError;
use tracing::{debug, info, warn};

use crate::filters::loader::{
    build_catalog_from_rows, load_realtime_cohorts, load_realtime_cohorts_for_teams, CohortRow,
};
use crate::filters::FilterError;
use crate::filters::{FilterCatalog, Generation};
use crate::observability::metrics::{
    FILTER_CATALOG_BUILD_DURATION_SECONDS, FILTER_CATALOG_LAST_SUCCESS_TIMESTAMP_SECONDS,
    FILTER_CATALOG_REFRESH_TOTAL, FILTER_CATALOG_TEAMS, FILTER_CATALOG_UNIQUE_CONDITIONS,
};

/// Snapshot counts returned by [`CatalogRefresher::refresh`] for logging.
#[derive(Debug, Clone, Copy)]
pub struct CatalogStats {
    pub teams: usize,
    pub unique_conditions: usize,
}

#[derive(Debug, Error)]
pub enum CatalogRefreshError {
    /// The refresh has no access read that began after it did, so it reads no cohort rows.
    #[error("reading team access failed: {0}")]
    Access(#[from] PollError),
    #[error(transparent)]
    Load(#[from] FilterError),
    #[error("loading posthog_cohort timed out")]
    LoadTimedOut(#[from] tokio::time::error::Elapsed),
    #[error("filter catalog build worker failed: {0}")]
    Build(#[from] JoinError),
}

/// Ordinal of a catalog refresh, taken when the refresh starts. A snapshot published by refresh `n`
/// read Postgres after `n` began. Only [`CatalogHandle`] mints one.
///
/// "Read after it began" also assumes the database the refresh reads is current. When the catalog
/// reads a read replica, a reconcile job relies on replica lag staying below the delay from
/// Django's commit to the job's admission, which spans the seeder, Kafka and the seed consumer.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) struct RefreshSeq(u64);

/// One consistent read of the handle: the snapshot and the refresh that published it.
pub(crate) enum CatalogView {
    NotLoaded,
    Loaded {
        published: RefreshSeq,
        catalog: Arc<FilterCatalog>,
    },
}

/// Lock-free, atomically-swapped catalog handle. Starts empty and unloaded; the pipeline fails
/// closed until the first successful refresh.
///
/// Its [`CatalogRefresher`] is its only writer, and a refresh takes the refresher by `&mut`, so
/// refreshes never overlap.
pub struct CatalogHandle {
    catalog: ArcSwap<FilterCatalog>,
    /// Refreshes started. Refresh `n` takes `n` when it starts.
    begun: AtomicU64,
    /// Sequence of the published snapshot, 0 before the first store.
    published: AtomicU64,
    loaded_notify: Notify,
    /// Last stamped generation, advanced by [`Self::store`]. Single-writer (the refresher), so
    /// `Relaxed` suffices.
    current_generation: AtomicU64,
    /// Signature of the last stored catalog, to detect a no-op refresh.
    current_signature: AtomicU64,
}

impl CatalogHandle {
    /// An unloaded handle that nothing refreshes from Postgres.
    pub fn new() -> Self {
        Self {
            catalog: ArcSwap::from_pointee(FilterCatalog::new()),
            begun: AtomicU64::new(0),
            published: AtomicU64::new(0),
            loaded_notify: Notify::new(),
            current_generation: AtomicU64::new(0),
            current_signature: AtomicU64::new(0),
        }
    }

    /// An unloaded handle and the one refresher that publishes to it, for the teams in `env` and the
    /// teams that a `cohort_realtime_team_access` row grants.
    pub fn with_refresher(
        env: TeamAllowlist,
        pool: PgPool,
        interval: Duration,
        jitter: Duration,
        cascade_enabled: bool,
    ) -> (Arc<Self>, CatalogRefresher) {
        let catalog = Arc::new(Self::new());
        let (access, poller) = TeamAccess::new(env);
        let refresher = CatalogRefresher {
            catalog: catalog.clone(),
            access,
            poller,
            pool,
            interval,
            jitter,
            cascade_enabled,
            last: None,
        };
        (catalog, refresher)
    }

    /// Load the current snapshot for a wait-free hot-path read.
    pub fn load(&self) -> Guard<Arc<FilterCatalog>> {
        self.catalog.load()
    }

    /// Load the current snapshot as an owned `Arc` that borrows nothing from `self`, so it can move
    /// into a `'static` blocking closure (e.g. a
    /// [`StoreHandle::run_section`](crate::store::StoreHandle::run_section) body).
    pub fn load_full(&self) -> Arc<FilterCatalog> {
        self.catalog.load_full()
    }

    /// True once the first refresh has succeeded. Before that the catalog is empty and consumers
    /// should treat every team as having no realtime cohorts.
    pub fn is_loaded(&self) -> bool {
        self.published.load(Ordering::Acquire) > 0
    }

    /// The newest refresh that has started. An admitted reconcile job records it.
    pub(crate) fn last_begun(&self) -> RefreshSeq {
        RefreshSeq(self.begun.load(Ordering::SeqCst))
    }

    /// Reads `published` before the snapshot, so the snapshot is at least as new as the sequence it
    /// reports.
    pub(crate) fn view(&self) -> CatalogView {
        match self.published.load(Ordering::Acquire) {
            0 => CatalogView::NotLoaded,
            published => CatalogView::Loaded {
                published: RefreshSeq(published),
                catalog: self.catalog.load_full(),
            },
        }
    }

    fn begin(&self) -> RefreshSeq {
        RefreshSeq(self.begun.fetch_add(1, Ordering::SeqCst) + 1)
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
        handle.store(catalog, handle.begin());
        handle
    }

    /// A refresh that begins now and publishes `catalog`, for tests that need a refresh after some
    /// event.
    #[cfg(test)]
    pub(crate) fn publish(&self, catalog: FilterCatalog) {
        self.begin_refresh().publish(catalog);
    }

    /// A refresh that begins now and publishes later, for tests of a refresh in flight across some
    /// event.
    #[cfg(test)]
    pub(crate) fn begin_refresh(&self) -> PendingRefresh<'_> {
        PendingRefresh {
            handle: self,
            seq: self.begin(),
        }
    }

    fn store(&self, catalog: FilterCatalog, seq: RefreshSeq) {
        debug_assert!(
            seq.0 > self.published.load(Ordering::Acquire),
            "catalog refreshes overlapped: refresh {seq:?} stores after a newer one",
        );
        // Advance the generation only on a content change (`INITIAL` is the first store); a no-op
        // refresh reuses it so memo entries stay valid.
        let signature = catalog_signature(&catalog);
        let prev = Generation(self.current_generation.load(Ordering::Relaxed));
        let prev_sig = self.current_signature.load(Ordering::Relaxed);
        let generation = if prev == Generation::INITIAL || signature != prev_sig {
            prev.next()
        } else {
            prev
        };
        self.current_signature.store(signature, Ordering::Relaxed);
        self.current_generation
            .store(generation.0, Ordering::Relaxed);
        let catalog = catalog.with_generation(generation);

        gauge!(FILTER_CATALOG_TEAMS).set(catalog.team_count() as f64);
        gauge!(FILTER_CATALOG_UNIQUE_CONDITIONS).set(catalog.total_unique_conditions() as f64);
        self.catalog.store(Arc::new(catalog));
        self.published.fetch_max(seq.0, Ordering::Release);
        self.loaded_notify.notify_waiters();
    }

    async fn build_and_store(
        &self,
        seq: RefreshSeq,
        build: impl FnOnce() -> FilterCatalog + Send + 'static,
    ) -> Result<CatalogStats, CatalogRefreshError> {
        let catalog = tokio::task::spawn_blocking(move || {
            let build_started = Instant::now();
            let catalog = build();
            histogram!(FILTER_CATALOG_BUILD_DURATION_SECONDS)
                .record(build_started.elapsed().as_secs_f64());
            catalog
        })
        .await?;
        let stats = CatalogStats {
            teams: catalog.team_count(),
            unique_conditions: catalog.total_unique_conditions(),
        };
        self.store(catalog, seq);
        Ok(stats)
    }
}

/// Seconds since the Unix epoch, saturating at 0 on a clock set before it.
fn now_unix_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|since| since.as_secs_f64())
        .unwrap_or(0.0)
}

/// Bounds the cohort load on the client. The statement timeout stops only the server, so a socket
/// that dies after the pool hands it out would otherwise hang the refresher, and with it every grant
/// and revoke. Keep it longer than `PG_ACQUIRE_TIMEOUT_SECS` plus `PG_STATEMENT_TIMEOUT_MS`, so the
/// pool and the server end a slow load first.
const LOAD_TIMEOUT: Duration = Duration::from_secs(30);

async fn load_processing(
    pool: &PgPool,
    teams: &ProcessingTeams,
) -> Result<Vec<CohortRow>, FilterError> {
    match teams.scope() {
        TeamAllowlist::All => load_realtime_cohorts(pool).await,
        TeamAllowlist::Only(team_ids) => {
            let team_ids: Vec<i32> = team_ids.iter().copied().collect();
            load_realtime_cohorts_for_teams(pool, &team_ids).await
        }
    }
}

/// Backstop for the load query's team filter.
fn retain_processing(rows: &mut Vec<CohortRow>, teams: &ProcessingTeams) {
    rows.retain(|row| teams.scope().includes(row.team_id));
}

/// A refresh that has begun and not yet published (test seam).
#[cfg(test)]
#[must_use = "a pending refresh publishes nothing until `publish` is called"]
pub(crate) struct PendingRefresh<'a> {
    handle: &'a CatalogHandle,
    seq: RefreshSeq,
}

#[cfg(test)]
impl PendingRefresh<'_> {
    pub(crate) fn publish(self, catalog: FilterCatalog) {
        self.handle.store(catalog, self.seq);
    }
}

impl Default for CatalogHandle {
    fn default() -> Self {
        Self::new()
    }
}

/// Hashes equal iff each team carries the same condition set — the sorts make it independent of
/// `HashMap`/`HashSet` order. `DefaultHasher` is unseeded; only intra-process consistency is needed
/// (the memo it gates resets on restart).
fn catalog_signature(catalog: &FilterCatalog) -> u64 {
    let mut hasher = DefaultHasher::new();
    catalog.hash(&mut hasher);
    hasher.finish()
}

/// Why a tick of [`CatalogRefresher::run`] refreshes the catalog.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RefreshReason {
    /// No refresh has published, so a failed boot load retries on every access poll.
    NeverPublished,
    /// Team access lets through other teams than the published catalog covers.
    AccessChanged,
    /// `interval ± jitter` has passed since the last refresh.
    Due,
}

/// The teams of the published catalog, and when the next periodic refresh is due.
#[derive(Debug)]
struct Published {
    teams: Arc<ProcessingTeams>,
    due: Instant,
}

/// The only writer of its [`CatalogHandle`] outside tests. It owns the team access poller, and each
/// refresh builds a catalog only for the teams of an access read that the refresh made itself. A
/// catalog built for the env list alone would lack the granted teams, so stage 2 GC would delete
/// their state.
pub struct CatalogRefresher {
    catalog: Arc<CatalogHandle>,
    access: Arc<TeamAccess>,
    poller: TeamAccessPoller,
    pool: PgPool,
    interval: Duration,
    jitter: Duration,
    cascade_enabled: bool,
    /// `None` until a refresh publishes. A failed refresh after that moves only `due`. So a cohort
    /// load that keeps failing waits for `due`, but a grant or a revoke that no refresh has published
    /// retries on every access poll.
    last: Option<Published>,
}

impl CatalogRefresher {
    /// Read team access and `posthog_cohort`, rebuild the catalog for the teams that team access
    /// lets through, and swap it in.
    ///
    /// The staleness metrics are stamped here rather than in [`Self::run`] so the boot load in
    /// `main` counts too. Otherwise a pod that booted fine and then lost its refresh loop would look
    /// identical to one that never loaded.
    ///
    /// # Errors
    ///
    /// Fails before it reads a cohort row when the access read fails, so also before the first
    /// accepted read. Also fails when the cohort load or the build fails. The previous catalog then
    /// stays.
    #[hotpath::measure(impl_type = "CatalogRefresher")]
    pub async fn refresh(&mut self) -> Result<CatalogStats, CatalogRefreshError> {
        let pool = self.pool.clone();
        match self
            .refresh_from(
                async |poller| poller.poll(&pool).await,
                async |teams| load_processing(&pool, teams).await,
            )
            .await
        {
            Ok(stats) => {
                gauge!(FILTER_CATALOG_LAST_SUCCESS_TIMESTAMP_SECONDS).set(now_unix_seconds());
                counter!(FILTER_CATALOG_REFRESH_TOTAL, "result" => "success").increment(1);
                Ok(stats)
            }
            Err(err) => {
                counter!(FILTER_CATALOG_REFRESH_TOTAL, "result" => "error").increment(1);
                Err(err)
            }
        }
    }

    /// `poll` reads team access, and `load` reads the cohort rows of its teams. The refresh begins
    /// before both reads, so every write committed before it began is in what it uses.
    async fn refresh_from(
        &mut self,
        poll: impl AsyncFnOnce(&mut TeamAccessPoller) -> Result<usize, PollError>,
        load: impl AsyncFnOnce(&ProcessingTeams) -> Result<Vec<CohortRow>, FilterError>,
    ) -> Result<CatalogStats, CatalogRefreshError> {
        let seq = self.catalog.begin();
        let polled = poll(&mut self.poller).await;
        let teams = self.current_teams(polled)?;
        let refreshed = self.load_and_store(seq, &teams, load).await;
        let due = Instant::now() + next_interval(self.interval, self.jitter);
        if refreshed.is_ok() {
            self.last = Some(Published { teams, due });
        } else if let Some(last) = &mut self.last {
            last.due = due;
        }
        refreshed
    }

    async fn load_and_store(
        &self,
        seq: RefreshSeq,
        teams: &ProcessingTeams,
        load: impl AsyncFnOnce(&ProcessingTeams) -> Result<Vec<CohortRow>, FilterError>,
    ) -> Result<CatalogStats, CatalogRefreshError> {
        let mut rows = tokio::time::timeout(LOAD_TIMEOUT, load(teams)).await??;
        let fetched_rows = rows.len();
        retain_processing(&mut rows, teams);
        if rows.len() != fetched_rows {
            debug!(
                fetched_rows,
                kept_rows = rows.len(),
                "filter catalog dropped cohort rows of teams it does not process",
            );
        }
        let cascade_enabled = self.cascade_enabled;
        self.catalog
            .build_and_store(seq, move || build_catalog_from_rows(rows, cascade_enabled))
            .await
    }

    /// The teams of the read that `polled` reports. A failed read leaves an earlier read in place,
    /// which can predate the refresh's [`RefreshSeq`], so this returns its error instead. A regressed
    /// read is current, except that the teams it regressed keep their previous rows.
    fn current_teams(
        &self,
        polled: Result<usize, PollError>,
    ) -> Result<Arc<ProcessingTeams>, PollError> {
        match polled {
            Ok(granted) => debug!(granted_teams = granted, "team access polled"),
            Err(err @ PollError::RegressedRows(_)) => {
                warn!(error = %err, "team access poll kept regressed rows")
            }
            Err(
                err @ (PollError::Query(_)
                | PollError::TimedOut(_)
                | PollError::UnknownLevel { .. }),
            ) => return Err(err),
        }
        Ok(self
            .access
            .processing_teams()
            .expect("a read that does not fail stores a snapshot"))
    }

    fn refresh_reason(&self, current: &ProcessingTeams, now: Instant) -> Option<RefreshReason> {
        match &self.last {
            None => Some(RefreshReason::NeverPublished),
            Some(last) if *last.teams != *current => Some(RefreshReason::AccessChanged),
            Some(last) => (now >= last.due).then_some(RefreshReason::Due),
        }
    }

    async fn tick(&mut self) {
        let polled = self.poller.poll(&self.pool).await;
        let current = match self.current_teams(polled) {
            Ok(current) => current,
            Err(err) => {
                warn!(error = %err, "team access poll failed; the catalog waits for the next poll");
                return;
            }
        };
        let Some(reason) = self.refresh_reason(&current, Instant::now()) else {
            return;
        };
        // `refresh` polls again after it begins, so the access read it uses follows its
        // `RefreshSeq`.
        match self.refresh().await {
            Ok(stats) => info!(
                ?reason,
                teams = stats.teams,
                unique_conditions = stats.unique_conditions,
                "filter catalog refreshed",
            ),
            Err(err) => warn!(
                ?reason,
                error = %err,
                "filter catalog refresh failed; keeping previous snapshot",
            ),
        }
    }

    /// Polls team access every [`next_poll_delay`] until shutdown. After each poll whose read does
    /// not fail, refreshes until a refresh publishes, and after that when team access changes or
    /// `interval ± jitter` has passed. Shutdown also cancels a poll or a refresh in flight, which
    /// then publishes nothing, so the task stays inside a short graceful window.
    ///
    /// Register `handle` without a liveness deadline: a database outage must not stop a processor
    /// that can run on its last catalog.
    pub async fn run(mut self, handle: Handle) {
        let _guard = handle.process_scope();

        loop {
            let tick = async {
                tokio::time::sleep(next_poll_delay()).await;
                self.tick().await;
            };
            tokio::select! {
                _ = handle.shutdown_recv() => break,
                () = tick => {}
            }
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
    use std::cell::Cell;
    use std::collections::{BTreeSet, HashSet};

    use super::*;
    use chrono_tz::UTC;
    use serde_json::json;

    use crate::filters::reverse_index::TeamFiltersBuilder;
    use crate::filters::{CohortId, TeamFilters, TeamId};

    fn cohort_row(id: i32, team_id: i32) -> CohortRow {
        CohortRow {
            id,
            team_id,
            filters: serde_json::Value::Null,
            behavioral_filters_shape_hash: None,
            person_filters_shape_hash: None,
            timezone: "UTC".to_string(),
        }
    }

    fn processing(env: TeamAllowlist, granted: &[i32]) -> Arc<ProcessingTeams> {
        TeamAccess::with_granted(env, granted.iter().copied())
            .processing_teams()
            .expect("with_granted accepts a read")
    }

    /// The tests read team access and cohort rows through the closures of `refresh_from`, so
    /// nothing reads this pool.
    fn refresher(env: TeamAllowlist) -> (Arc<CatalogHandle>, CatalogRefresher) {
        let pool = PgPool::connect_lazy("postgres://localhost/unused").expect("a valid url");
        CatalogHandle::with_refresher(env, pool, Duration::from_secs(300), Duration::ZERO, false)
    }

    fn access_read_failed() -> Result<usize, PollError> {
        Err(PollError::Query(sqlx::Error::PoolClosed))
    }

    fn cohort_load_failed() -> Result<Vec<CohortRow>, FilterError> {
        Err(FilterError::Query(sqlx::Error::PoolClosed))
    }

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

    fn team_with_one_person() -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        let filters = json!({
            "properties": {
                "type": "AND",
                "values": [{
                    "type": "person",
                    "key": "email",
                    "value": "a@b.com",
                    "operator": "exact",
                    "conditionHash": "fedcba9876543210",
                    "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
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
    async fn catalog_build_runs_off_the_runtime_and_failure_keeps_the_snapshot() {
        let handle = CatalogHandle::new();
        let runtime_thread = std::thread::current().id();
        let stats = handle
            .build_and_store(handle.begin(), move || {
                assert_ne!(std::thread::current().id(), runtime_thread);
                FilterCatalog::from_teams([(TeamId(7), team_with_one_behavioral())])
            })
            .await
            .unwrap();
        assert_eq!(stats.teams, 1);
        assert_eq!(stats.unique_conditions, 1);
        assert!(handle.is_loaded());
        let snapshot = handle.load_full();

        let error = handle
            .build_and_store(handle.begin(), || panic!("catalog build failed"))
            .await
            .unwrap_err();
        assert!(matches!(error, CatalogRefreshError::Build(error) if error.is_panic()));
        assert!(Arc::ptr_eq(&snapshot, &handle.load_full()));
        assert!(handle.is_loaded());
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

        handle.publish(FilterCatalog::from_teams([(
            TeamId(7),
            team_with_one_behavioral(),
        )]));
        waiter.await.expect("waiter resolves on the first store");

        // Already loaded → immediate.
        handle.wait_until_loaded().await;
    }

    #[tokio::test]
    async fn a_refresh_begins_before_it_reads_team_access_and_the_cohort_rows_of_the_granted_teams()
    {
        let (catalog, mut refresher) = refresher(TeamAllowlist::Only(HashSet::from([2])));
        let before_refresh = catalog.last_begun();
        let begun_at_access_read = Cell::new(before_refresh);
        let begun_at_cohort_read = Cell::new(before_refresh);

        refresher
            .refresh_from(
                async |poller| {
                    begun_at_access_read.set(catalog.last_begun());
                    poller.accept_granted([5])
                },
                async |teams| {
                    assert_eq!(teams.scope(), &TeamAllowlist::Only(HashSet::from([2, 5])));
                    begun_at_cohort_read.set(catalog.last_begun());
                    Ok(Vec::new())
                },
            )
            .await
            .unwrap();

        for begun_at_read in [begun_at_access_read, begun_at_cohort_read] {
            assert!(
                begun_at_read.get() > before_refresh,
                "a job admitted during a read must not count the refresh as begun after it",
            );
        }
    }

    #[tokio::test]
    async fn a_refresh_reads_no_cohort_rows_only_when_its_access_read_fails() {
        let (catalog, mut refresher) = refresher(TeamAllowlist::Only(HashSet::from([2])));
        let cohorts_read = Cell::new(false);
        let read_cohorts = async |_: &ProcessingTeams| {
            cohorts_read.set(true);
            Ok(Vec::new())
        };

        let before_first_read = refresher
            .refresh_from(async |_| access_read_failed(), read_cohorts)
            .await;
        assert!(matches!(
            before_first_read,
            Err(CatalogRefreshError::Access(PollError::Query(_)))
        ));
        assert!(
            !cohorts_read.get(),
            "a catalog of the env list alone lets stage 2 GC delete the granted teams' state",
        );
        assert!(!catalog.is_loaded());

        refresher
            .refresh_from(
                async |poller| poller.accept_granted([5]),
                async |_| Ok(Vec::new()),
            )
            .await
            .unwrap();
        let after_publish = refresher
            .refresh_from(async |_| access_read_failed(), read_cohorts)
            .await;
        assert!(after_publish.is_err());
        assert!(
            !cohorts_read.get(),
            "the rows of an earlier read can lack a grant that a job admitted after it relies on",
        );

        refresher
            .refresh_from(
                async |poller| poller.accept_granted([]),
                async |teams| {
                    assert_eq!(teams.scope(), &TeamAllowlist::Only(HashSet::from([2, 5])));
                    Ok(Vec::new())
                },
            )
            .await
            .expect("a deleted access row must not fail every refresh until a restart");
    }

    #[tokio::test(start_paused = true)]
    async fn a_refresh_is_due_until_one_publishes_then_on_an_access_change_or_after_the_period() {
        let (_catalog, mut refresher) = refresher(TeamAllowlist::Only(HashSet::from([2])));
        let now = Instant::now();
        let past_due = now + Duration::from_secs(3600);

        let polled = refresher.poller.accept_granted([5]);
        let granted = refresher.current_teams(polled).unwrap();
        assert_eq!(
            refresher.refresh_reason(&granted, now),
            Some(RefreshReason::NeverPublished)
        );
        let hung_boot_load = refresher
            .refresh_from(
                async |poller| poller.accept_granted([5]),
                async |_| {
                    tokio::time::sleep(2 * LOAD_TIMEOUT).await;
                    Ok(Vec::new())
                },
            )
            .await;
        assert!(matches!(
            hung_boot_load,
            Err(CatalogRefreshError::LoadTimedOut(_))
        ));
        assert_eq!(
            refresher.refresh_reason(&granted, now),
            Some(RefreshReason::NeverPublished),
            "a boot load that times out retries on the next tick",
        );

        refresher
            .refresh_from(
                async |poller| poller.accept_granted([5]),
                async |_| Ok(Vec::new()),
            )
            .await
            .unwrap();
        assert_eq!(refresher.refresh_reason(&granted, now), None);
        assert_eq!(
            refresher.refresh_reason(&granted, past_due),
            Some(RefreshReason::Due)
        );
        // A failed refresh that moves `due` puts it after `past_due`.
        refresher.interval = Duration::from_secs(7200);
        refresher
            .refresh_from(
                async |poller| poller.accept_granted([5]),
                async |_| cohort_load_failed(),
            )
            .await
            .unwrap_err();
        assert_eq!(
            refresher.refresh_reason(&granted, past_due),
            None,
            "a cohort load that keeps failing waits for the period, not for the next tick",
        );

        let polled = refresher.poller.accept_granted([5, 6]);
        let regranted = refresher.current_teams(polled).unwrap();
        assert_eq!(
            refresher.refresh_reason(&regranted, now),
            Some(RefreshReason::AccessChanged)
        );
        refresher
            .refresh_from(async |_| access_read_failed(), async |_| Ok(Vec::new()))
            .await
            .unwrap_err();
        assert_eq!(
            refresher.refresh_reason(&regranted, now),
            Some(RefreshReason::AccessChanged),
            "a refresh whose access read failed retries on the next tick",
        );
        refresher
            .refresh_from(
                async |poller| poller.accept_granted([5, 6]),
                async |_| cohort_load_failed(),
            )
            .await
            .unwrap_err();
        assert_eq!(
            refresher.refresh_reason(&regranted, now),
            Some(RefreshReason::AccessChanged),
            "a grant that a failed cohort load did not publish retries on the next tick",
        );
    }

    #[test]
    fn first_store_advances_past_the_initial_generation() {
        let handle = CatalogHandle::new();
        assert_eq!(handle.load().generation(), Generation::INITIAL);
        handle.publish(FilterCatalog::from_teams([(
            TeamId(7),
            team_with_one_behavioral(),
        )]));
        assert_eq!(handle.load().generation(), Generation(1));
    }

    #[test]
    fn now_unix_seconds_is_a_plausible_epoch_second() {
        // The staleness alert computes `time() - gauge`, so a gauge stamped in the wrong unit (or
        // from a monotonic clock starting near zero) would read as decades stale and page forever.
        let now = now_unix_seconds();
        assert!(now > 1_700_000_000.0, "expected epoch seconds, got {now}");
    }

    #[test]
    fn no_op_refresh_keeps_the_generation_and_a_content_change_bumps_it() {
        let handle = CatalogHandle::new();
        handle.publish(FilterCatalog::from_teams([(
            TeamId(7),
            team_with_one_behavioral(),
        )]));
        let gen1 = handle.load().generation();

        // Same condition set → same signature → generation unchanged (the memo survives the refresh).
        handle.publish(FilterCatalog::from_teams([(
            TeamId(7),
            team_with_one_behavioral(),
        )]));
        assert_eq!(
            handle.load().generation(),
            gen1,
            "a no-op refresh reuses the generation",
        );

        // A different condition hash → signature changes → generation advances (memo invalidates).
        handle.publish(FilterCatalog::from_teams([(
            TeamId(7),
            team_with_one_person(),
        )]));
        assert_ne!(
            handle.load().generation(),
            gen1,
            "a content change bumps the generation",
        );
    }

    #[test]
    fn catalog_signature_ignores_team_iteration_order() {
        let a = FilterCatalog::from_teams([
            (TeamId(7), team_with_one_behavioral()),
            (TeamId(8), team_with_one_person()),
        ]);
        let b = FilterCatalog::from_teams([
            (TeamId(8), team_with_one_person()),
            (TeamId(7), team_with_one_behavioral()),
        ]);
        assert_eq!(catalog_signature(&a), catalog_signature(&b));
    }

    #[test]
    fn retain_processing_keeps_the_rows_of_the_env_list_and_the_granted_teams() {
        for (env, granted, kept) in [
            (TeamAllowlist::Only(HashSet::from([2])), vec![5], vec![2, 5]),
            (TeamAllowlist::All, vec![], vec![2, 5, 7]),
            (TeamAllowlist::Only(HashSet::new()), vec![], vec![]),
        ] {
            let mut rows = vec![cohort_row(1, 2), cohort_row(2, 5), cohort_row(3, 7)];
            retain_processing(&mut rows, &processing(env.clone(), &granted));
            let kept_teams: Vec<i32> = rows.iter().map(|row| row.team_id).collect();
            assert_eq!(kept_teams, kept, "env {env:?}, granted {granted:?}");
        }
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

        let (handle, mut refresher) = CatalogHandle::with_refresher(
            TeamAllowlist::All,
            pool.clone(),
            Duration::from_secs(300),
            Duration::ZERO,
            false,
        );
        assert!(!handle.is_loaded());

        let stats = refresher
            .refresh()
            .await
            .expect("refresh against live posthog_cohort and cohort_realtime_team_access");

        assert!(handle.is_loaded());
        assert_eq!(handle.load().team_count(), stats.teams);

        // Bypass `retain_processing`, which would hide a missing SQL filter.
        let keys = |rows: &[CohortRow]| -> BTreeSet<(i32, i32)> {
            rows.iter().map(|row| (row.team_id, row.id)).collect()
        };
        let unscoped = load_processing(&pool, &processing(TeamAllowlist::All, &[]))
            .await
            .expect("unscoped load against live posthog_cohort");
        if let Some(team_id) = unscoped.first().map(|row| row.team_id) {
            let only_team = processing(TeamAllowlist::Only(HashSet::from([team_id])), &[]);
            let scoped = load_processing(&pool, &only_team)
                .await
                .expect("team-scoped load against live posthog_cohort");
            let expected: BTreeSet<_> = keys(&unscoped)
                .into_iter()
                .filter(|(team, _)| *team == team_id)
                .collect();
            assert_eq!(keys(&scoped), expected);
        }
        let none = load_processing(&pool, &processing(TeamAllowlist::Only(HashSet::new()), &[]))
            .await
            .expect("empty-scope load against live posthog_cohort");
        assert!(none.is_empty());
    }
}
