use crate::api::errors::FlagError;
use crate::cohorts::cohort_models::Cohort;
use crate::metrics::consts::{
    COHORT_CACHE_ENTRIES_GAUGE, COHORT_CACHE_HIT_COUNTER, COHORT_CACHE_MISS_COUNTER,
    COHORT_CACHE_SIZE_BYTES_GAUGE, DB_COHORT_ERRORS_COUNTER, DB_COHORT_READS_COUNTER,
};
use axum::async_trait;
use common_database::PostgresReader;
use common_types::TeamId;
use moka::future::Cache;
use std::sync::Arc;
use std::time::Duration;

/// CohortCacheManager manages the in-memory cache of cohorts using `moka` for caching.
///
/// Features:
/// - **TTL**: Each cache entry expires after 5 minutes.
/// - **Memory-based eviction**: The cache estimates memory usage per entry and evicts
///   least recently used entries when the total estimated memory exceeds the configured limit.
///   This prevents unbounded memory growth from large cohort filter definitions.
/// - **Per-key coalescing**: Uses moka's `try_get_with` to ensure that concurrent requests
///   for the same team coalesce into a single database fetch, while requests for different
///   teams proceed in parallel. This prevents thundering herd on cache miss without
///   introducing cross-team blocking.
///
/// The manager is generic over the fetcher type `F` to allow dependency injection
/// for testing while maintaining static dispatch
///
/// ```text
/// CohortCacheManager {
///     fetcher: PostgresCohortFetcher { reader },
///     cache: Cache<TeamId, Vec<Cohort>> {
///         // Example:
///         2: [
///             Cohort { id: 1, name: "Power Users", filters: {...} },
///             Cohort { id: 2, name: "Churned", filters: {...} }
///         ],
///         5: [
///             Cohort { id: 3, name: "Beta Users", filters: {...} }
///         ]
///     }
/// }
/// ```
///
pub struct CohortCacheManager<F: CohortFetcher = PostgresCohortFetcher> {
    fetcher: Arc<F>,
    cache: Cache<TeamId, Vec<Cohort>>,
}

#[derive(Clone, Debug)]
pub enum CohortFetchError {
    DatabaseUnavailable,
    QueryFailed(String),
}

/// Trait for fetching cohorts from a data source.
/// This abstraction allows for dependency injection and testing.
#[async_trait]
pub trait CohortFetcher: Send + Sync + 'static {
    async fn fetch(&self, team_id: TeamId) -> Result<Vec<Cohort>, CohortFetchError>;
}

/// Default implementation that fetches cohorts from PostgreSQL.
#[derive(Clone)]
pub struct PostgresCohortFetcher {
    reader: PostgresReader,
}

impl PostgresCohortFetcher {
    pub fn new(reader: PostgresReader) -> Self {
        Self { reader }
    }
}

#[async_trait]
impl CohortFetcher for PostgresCohortFetcher {
    async fn fetch(&self, team_id: TeamId) -> Result<Vec<Cohort>, CohortFetchError> {
        Cohort::list_from_pg(self.reader.clone(), team_id).await
    }
}

/// Calculates the total estimated memory weight of a slice of cohorts.
///
/// Returns a u32 suitable for use as a moka cache weight. Uses saturating arithmetic
/// to handle edge cases where sizes exceed u32::MAX.
fn cohorts_weight(cohorts: &[Cohort]) -> u32 {
    cohorts
        .iter()
        .map(|c| u32::try_from(c.estimated_size_bytes()).unwrap_or(u32::MAX))
        .fold(0u32, u32::saturating_add)
}

impl CohortCacheManager<PostgresCohortFetcher> {
    /// Creates a new CohortCacheManager with the default PostgreSQL fetcher.
    pub fn new(
        reader: PostgresReader,
        capacity_bytes: Option<u64>,
        ttl_seconds: Option<u64>,
    ) -> Self {
        let fetcher = PostgresCohortFetcher::new(reader);
        Self::new_with_fetcher(fetcher, capacity_bytes, ttl_seconds)
    }
}

impl<F: CohortFetcher> CohortCacheManager<F> {
    /// Default cache capacity: 256 MB
    const DEFAULT_CAPACITY_BYTES: u64 = 268_435_456;

    /// Creates a new CohortCacheManager with a custom fetcher.
    /// This allows dependency injection for testing.
    pub fn new_with_fetcher(
        fetcher: F,
        capacity_bytes: Option<u64>,
        ttl_seconds: Option<u64>,
    ) -> Self {
        // Use memory-based weighing: estimate the actual memory footprint of each entry.
        // This prevents unbounded memory growth from teams with large cohort filter definitions.
        let weigher = |_: &TeamId, cohorts: &Vec<Cohort>| cohorts_weight(cohorts);

        let cache = Cache::builder()
            .time_to_live(Duration::from_secs(ttl_seconds.unwrap_or(300))) // Default to 5 minutes
            .weigher(weigher)
            // Note: max_capacity is u64 while weigher returns u32. This is correct because
            // max_capacity is the sum of all entry weights, which can exceed u32::MAX with
            // many entries. Individual entries can't exceed u32::MAX (~4GB) in practice.
            .max_capacity(capacity_bytes.unwrap_or(Self::DEFAULT_CAPACITY_BYTES))
            .build();

        Self {
            fetcher: Arc::new(fetcher),
            cache,
        }
    }

    /// Retrieves cohorts for a given team.
    ///
    /// Uses moka's `try_get_with` for per-key coalescing:
    /// - If cached: returns immediately (cache hit)
    /// - If not cached: only one caller fetches from DB, others wait for the result
    /// - Different teams fetch in parallel (no cross-team blocking)
    pub async fn get_cohorts(&self, team_id: TeamId) -> Result<Vec<Cohort>, FlagError> {
        if let Some(cached) = self.cache.get(&team_id).await {
            common_metrics::inc(COHORT_CACHE_HIT_COUNTER, &[], 1);
            return Ok(cached);
        }

        let fetcher = self.fetcher.clone();

        common_metrics::inc(COHORT_CACHE_MISS_COUNTER, &[], 1);

        self.cache
            .try_get_with(team_id, async move {
                match fetcher.fetch(team_id).await {
                    Ok(cohorts) => {
                        common_metrics::inc(DB_COHORT_READS_COUNTER, &[], 1);
                        Ok(cohorts)
                    }
                    Err(e) => {
                        common_metrics::inc(DB_COHORT_ERRORS_COUNTER, &[], 1);
                        Err(e)
                    }
                }
            })
            .await
            .map_err(|arc_err| FlagError::from((*arc_err).clone()))
            .inspect(|_| {
                // Report cache metrics after successful fetch
                // Note: This runs for all callers (fetcher + coalesced waiters),
                // but that's fine - it just reports current cache state
                self.report_cache_metrics();
            })
    }

    /// Starts periodic monitoring of cache metrics.
    ///
    /// Reports `flags_cohort_cache_size_bytes` and `flags_cohort_cache_entries` gauges
    /// at the specified interval. This ensures metrics stay fresh regardless of cache
    /// hit/miss patterns, since `report_cache_metrics()` is otherwise only called on
    /// cache misses.
    pub async fn start_monitoring(&self, interval_secs: u64) {
        let mut ticker = tokio::time::interval(Duration::from_secs(interval_secs));

        tracing::info!(
            "Starting cohort cache monitoring (interval: {}s)",
            interval_secs
        );

        loop {
            ticker.tick().await;
            self.report_cache_metrics();

            tracing::debug!(
                "Cohort cache metrics - size: {} bytes, entries: {}",
                self.cache.weighted_size(),
                self.cache.entry_count()
            );
        }
    }

    /// Reports cache size metrics for observability.
    ///
    /// Called after cache insertions and periodically by `start_monitoring()`.
    fn report_cache_metrics(&self) {
        common_metrics::gauge(
            COHORT_CACHE_SIZE_BYTES_GAUGE,
            &[],
            self.cache.weighted_size() as f64,
        );
        common_metrics::gauge(
            COHORT_CACHE_ENTRIES_GAUGE,
            &[],
            self.cache.entry_count() as f64,
        );
    }
}

impl<F: CohortFetcher> Clone for CohortCacheManager<F> {
    fn clone(&self) -> Self {
        Self {
            fetcher: Arc::clone(&self.fetcher),
            cache: self.cache.clone(),
        }
    }
}

impl From<CohortFetchError> for FlagError {
    fn from(value: CohortFetchError) -> Self {
        match value {
            CohortFetchError::DatabaseUnavailable => FlagError::DatabaseUnavailable,
            CohortFetchError::QueryFailed(msg) => FlagError::Internal(msg),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::TestContext;
    use axum::async_trait;
    use std::sync::atomic::{AtomicU32, Ordering};
    use std::sync::Arc;
    use tokio::sync::Barrier;
    use tokio::time::{sleep, Duration};

    fn create_test_cohort(filters: Option<serde_json::Value>) -> Cohort {
        Cohort {
            id: 1,
            name: Some("Test".to_string()),
            description: None,
            team_id: 1,
            deleted: false,
            filters,
            query: None,
            version: Some(1),
            pending_version: None,
            count: None,
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups: serde_json::json!({}),
            created_by_id: None,
        }
    }

    #[test]
    fn test_cohorts_weight_empty_slice() {
        let cohorts: Vec<Cohort> = vec![];
        assert_eq!(cohorts_weight(&cohorts), 0);
    }

    #[test]
    fn test_cohorts_weight_single_cohort() {
        let cohort = create_test_cohort(Some(serde_json::json!({"key": "value"})));
        let weight = cohorts_weight(std::slice::from_ref(&cohort));

        assert!(weight > 0, "Single cohort should have non-zero weight");
        assert_eq!(
            weight,
            cohort.estimated_size_bytes() as u32,
            "Weight should match estimated_size_bytes"
        );
    }

    #[test]
    fn test_cohorts_weight_multiple_cohorts_sums() {
        let small = create_test_cohort(Some(serde_json::json!({})));
        let large = create_test_cohort(Some(serde_json::json!({
            "nested": {"deep": {"values": ["a", "b", "c", "d", "e"]}}
        })));

        let small_weight = cohorts_weight(std::slice::from_ref(&small));
        let large_weight = cohorts_weight(std::slice::from_ref(&large));
        let combined_weight = cohorts_weight(&[small, large]);

        assert_eq!(
            combined_weight,
            small_weight + large_weight,
            "Combined weight should equal sum of individual weights"
        );
    }

    #[test]
    fn test_cohorts_weight_saturates_on_overflow() {
        // Individual cohorts can't realistically exceed u32::MAX (~4GB of JSON data),
        // but we can verify saturating behavior when summing multiple large cohorts.
        let large_filters = serde_json::json!({
            "properties": (0..1000).map(|i| {
                serde_json::json!({"key": format!("prop_{}", i), "value": format!("val_{}", i)})
            }).collect::<Vec<_>>()
        });

        let large_cohort = create_test_cohort(Some(large_filters));
        let single_weight = cohorts_weight(std::slice::from_ref(&large_cohort));

        // Create many cohorts - weight should not overflow
        let many_cohorts: Vec<Cohort> = (0..10000).map(|_| large_cohort.clone()).collect();
        let total_weight = cohorts_weight(&many_cohorts);

        // If no overflow, total should be sum (or saturated at u32::MAX)
        let expected = (single_weight as u64 * 10000).min(u32::MAX as u64) as u32;
        assert_eq!(
            total_weight, expected,
            "Weight should saturate correctly without overflow"
        );
    }

    /// Tests that cache entries expire after the specified TTL.
    #[tokio::test]
    async fn test_cache_expiry() -> Result<(), anyhow::Error> {
        let context = TestContext::new(None).await;
        let team = context.insert_new_team(None).await?;

        let filters = serde_json::json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$active", "type": "person", "value": [true], "negation": false, "operator": "exact"}]}]}});
        let _cohort = context.insert_cohort(team.id, None, filters, false).await?;

        // Initialize CohortCacheManager with a short TTL for testing.
        // Use 10KB capacity - plenty of room for test cohorts.
        let cohort_cache = CohortCacheManager::new(
            context.non_persons_reader.clone(),
            Some(10 * 1024), // 10 KB
            Some(1),         // 1-second TTL
        );

        let cohorts = cohort_cache.get_cohorts(team.id).await?;
        assert_eq!(cohorts.len(), 1);
        assert_eq!(cohorts[0].team_id, team.id);

        let cached_cohorts = cohort_cache.cache.get(&team.id).await;
        assert!(cached_cohorts.is_some());

        // Wait for TTL to expire
        sleep(Duration::from_secs(2)).await;

        // Attempt to retrieve from cache again
        let cached_cohorts = cohort_cache.cache.get(&team.id).await;
        assert!(cached_cohorts.is_none(), "Cache entry should have expired");

        Ok(())
    }

    /// Tests that the cache correctly evicts least recently used entries when memory limit is exceeded.
    #[tokio::test]
    async fn test_cache_memory_based_eviction() -> Result<(), anyhow::Error> {
        let context = TestContext::new(None).await;

        // Create a cohort with a known filter size to estimate memory usage
        let filters = serde_json::json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$active", "type": "person", "value": [true], "negation": false, "operator": "exact"}]}]}});

        // First, insert one cohort to measure its approximate size
        let test_team = context.insert_new_team(None).await?;
        context
            .insert_cohort(test_team.id, None, filters.clone(), false)
            .await?;

        // Create a cache with very large capacity to measure cohort size
        let measure_cache =
            CohortCacheManager::new(context.non_persons_reader.clone(), Some(1024 * 1024), None);
        measure_cache.get_cohorts(test_team.id).await?;
        measure_cache.cache.run_pending_tasks().await;
        let single_cohort_size = measure_cache.cache.weighted_size();

        // Set capacity to hold exactly 3 cohorts (with small buffer for rounding)
        let max_capacity_bytes = single_cohort_size * 3 + 100;

        let cohort_cache = CohortCacheManager::new(
            context.non_persons_reader.clone(),
            Some(max_capacity_bytes),
            None,
        );

        let mut inserted_project_ids = Vec::new();

        // Insert 3 teams with cohorts - should fit within capacity
        for _ in 0..3 {
            let team = context.insert_new_team(None).await?;
            let project_id = team.id;
            inserted_project_ids.push(project_id);
            context
                .insert_cohort(team.id, None, filters.clone(), false)
                .await?;
            cohort_cache.get_cohorts(project_id).await?;
        }

        cohort_cache.cache.run_pending_tasks().await;
        let cache_entry_count = cohort_cache.cache.entry_count();
        assert_eq!(
            cache_entry_count, 3,
            "Cache should hold 3 entries within capacity"
        );

        // Insert a 4th team - should trigger eviction of LRU entry
        let new_team = context.insert_new_team(None).await?;
        let new_project_id = new_team.id;
        context
            .insert_cohort(new_team.id, None, filters, false)
            .await?;
        cohort_cache.get_cohorts(new_project_id).await?;

        cohort_cache.cache.run_pending_tasks().await;
        let cache_entry_count_after = cohort_cache.cache.entry_count();
        assert_eq!(
            cache_entry_count_after, 3,
            "Cache should still hold 3 entries after eviction"
        );

        // Verify LRU entry was evicted (first inserted)
        let evicted_project_id = &inserted_project_ids[0];
        let cached_cohorts = cohort_cache.cache.get(evicted_project_id).await;
        assert!(
            cached_cohorts.is_none(),
            "Least recently used cache entry should have been evicted"
        );

        // Verify new entry is present
        let cached_new_team = cohort_cache.cache.get(&new_project_id).await;
        assert!(
            cached_new_team.is_some(),
            "Newly added cache entry should be present"
        );

        Ok(())
    }

    /// Tests that the weighted_size reflects actual memory usage, not just entry count.
    #[tokio::test]
    async fn test_cache_weighted_size_reflects_memory() -> Result<(), anyhow::Error> {
        let context = TestContext::new(None).await;

        // Create two cohorts with different filter sizes
        let small_filters = serde_json::json!({"properties": {"type": "AND", "values": []}});
        let large_filters = serde_json::json!({
            "properties": {
                "type": "OR",
                "values": [
                    {"type": "OR", "values": [
                        {"key": "property_1", "type": "person", "value": ["value1", "value2", "value3"], "negation": false, "operator": "exact"},
                        {"key": "property_2", "type": "person", "value": ["value4", "value5", "value6"], "negation": false, "operator": "exact"},
                        {"key": "property_3", "type": "person", "value": ["value7", "value8", "value9"], "negation": false, "operator": "exact"}
                    ]},
                    {"type": "OR", "values": [
                        {"key": "property_4", "type": "person", "value": ["value10", "value11", "value12"], "negation": false, "operator": "exact"}
                    ]}
                ]
            }
        });

        let cohort_cache =
            CohortCacheManager::new(context.non_persons_reader.clone(), Some(1024 * 1024), None);

        // Insert team with small filters
        let small_team = context.insert_new_team(None).await?;
        context
            .insert_cohort(small_team.id, None, small_filters, false)
            .await?;
        cohort_cache.get_cohorts(small_team.id).await?;
        cohort_cache.cache.run_pending_tasks().await;
        let size_after_small = cohort_cache.cache.weighted_size();

        // Insert team with large filters
        let large_team = context.insert_new_team(None).await?;
        context
            .insert_cohort(large_team.id, None, large_filters, false)
            .await?;
        cohort_cache.get_cohorts(large_team.id).await?;
        cohort_cache.cache.run_pending_tasks().await;
        let size_after_large = cohort_cache.cache.weighted_size();

        // The large filter entry should contribute more to weighted_size
        let large_entry_contribution = size_after_large - size_after_small;
        assert!(
            large_entry_contribution > size_after_small,
            "Large filter entry ({large_entry_contribution} bytes) should be larger than small filter entry ({size_after_small} bytes)"
        );

        Ok(())
    }

    #[tokio::test]
    async fn test_get_cohorts() -> Result<(), anyhow::Error> {
        let context = TestContext::new(None).await;
        let team = context.insert_new_team(None).await?;
        let project_id = team.id;
        let team_id = team.id;

        let filters = serde_json::json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$active", "type": "person", "value": [true], "negation": false, "operator": "exact"}]}]}});
        let _cohort = context.insert_cohort(team_id, None, filters, false).await?;
        let cohort_cache = CohortCacheManager::new(context.non_persons_reader.clone(), None, None);

        let cached_cohorts = cohort_cache.cache.get(&project_id).await;
        assert!(cached_cohorts.is_none(), "Cache should initially be empty");

        let cohorts = cohort_cache.get_cohorts(project_id).await?;
        assert_eq!(cohorts.len(), 1);
        assert_eq!(cohorts[0].team_id, team_id);

        let cached_cohorts = cohort_cache.cache.get(&project_id).await.unwrap();
        assert_eq!(cached_cohorts.len(), 1);
        assert_eq!(cached_cohorts[0].team_id, team_id);

        Ok(())
    }

    /// Tests that cohorts with empty filters are correctly sized and cached.
    #[tokio::test]
    async fn test_cache_empty_cohort_filters() -> Result<(), anyhow::Error> {
        let context = TestContext::new(None).await;
        let team = context.insert_new_team(None).await?;

        // Create cohort with minimal/empty filters
        let empty_filters = serde_json::json!({});
        context
            .insert_cohort(team.id, None, empty_filters, false)
            .await?;

        let cohort_cache =
            CohortCacheManager::new(context.non_persons_reader.clone(), Some(1024 * 1024), None);

        let cohorts = cohort_cache.get_cohorts(team.id).await?;
        assert_eq!(cohorts.len(), 1);

        cohort_cache.cache.run_pending_tasks().await;
        let weighted_size = cohort_cache.cache.weighted_size();

        // Empty cohorts should still have non-zero size (base struct overhead)
        assert!(
            weighted_size > 0,
            "Empty cohort should have non-zero weighted size"
        );

        // Size should be at least the base Cohort struct size
        assert!(
            weighted_size >= std::mem::size_of::<Cohort>() as u64,
            "Weighted size should be at least the base struct size"
        );

        Ok(())
    }

    /// Tests cache behavior when capacity is set to zero.
    /// With zero capacity, entries may still be inserted momentarily but evicted immediately.
    #[tokio::test]
    async fn test_cache_zero_capacity() -> Result<(), anyhow::Error> {
        let context = TestContext::new(None).await;
        let team = context.insert_new_team(None).await?;

        let filters = serde_json::json!({"key": "value"});
        context.insert_cohort(team.id, None, filters, false).await?;

        // Create cache with zero capacity
        let cohort_cache = CohortCacheManager::new(
            context.non_persons_reader.clone(),
            Some(0), // Zero capacity
            None,
        );

        // Should still successfully fetch from database
        let cohorts = cohort_cache.get_cohorts(team.id).await?;
        assert_eq!(cohorts.len(), 1, "Should still fetch cohorts from DB");

        // After maintenance runs, cache should be empty or near-empty due to zero capacity
        cohort_cache.cache.run_pending_tasks().await;

        // With zero capacity, Moka will evict entries immediately
        // The entry might exist briefly but should be evicted
        let entry_count = cohort_cache.cache.entry_count();
        assert!(
            entry_count <= 1,
            "With zero capacity, cache should have at most 1 entry (may be pending eviction)"
        );

        Ok(())
    }

    /// Tests that re-accessing an entry updates its LRU position and prevents eviction.
    #[tokio::test]
    async fn test_cache_lru_reaccess_prevents_eviction() -> Result<(), anyhow::Error> {
        let context = TestContext::new(None).await;

        let filters = serde_json::json!({"key": "value"});

        // Measure single cohort size using one team
        let measure_team = context.insert_new_team(None).await?;
        context
            .insert_cohort(measure_team.id, None, filters.clone(), false)
            .await?;
        let measure_cache =
            CohortCacheManager::new(context.non_persons_reader.clone(), Some(1024 * 1024), None);
        measure_cache.get_cohorts(measure_team.id).await?;
        measure_cache.cache.run_pending_tasks().await;
        let single_size = measure_cache.cache.weighted_size();

        // Create cache that holds exactly 3 entries
        let capacity = single_size * 3 + 100;
        let cohort_cache =
            CohortCacheManager::new(context.non_persons_reader.clone(), Some(capacity), None);

        // Insert 3 teams, running pending tasks after each to ensure deterministic behavior
        let mut team_ids = Vec::new();
        for _ in 0..3 {
            let team = context.insert_new_team(None).await?;
            context
                .insert_cohort(team.id, None, filters.clone(), false)
                .await?;
            cohort_cache.get_cohorts(team.id).await?;
            cohort_cache.cache.run_pending_tasks().await;
            team_ids.push(team.id);
        }

        // Re-access the first team to make it "recently used"
        cohort_cache.get_cohorts(team_ids[0]).await?;

        // Insert a 4th team - should evict team_ids[1] (second inserted, not re-accessed)
        let new_team = context.insert_new_team(None).await?;
        context
            .insert_cohort(new_team.id, None, filters, false)
            .await?;
        cohort_cache.get_cohorts(new_team.id).await?;

        cohort_cache.cache.run_pending_tasks().await;

        // First team should still be present (was re-accessed)
        assert!(
            cohort_cache.cache.get(&team_ids[0]).await.is_some(),
            "Re-accessed entry should not be evicted"
        );

        // New team should be present
        assert!(
            cohort_cache.cache.get(&new_team.id).await.is_some(),
            "New entry should be present"
        );

        // Second team should have been evicted (LRU victim - inserted after first, never re-accessed)
        assert!(
            cohort_cache.cache.get(&team_ids[1]).await.is_none(),
            "LRU victim should be evicted"
        );

        Ok(())
    }

    /// Tests that start_monitoring reports metrics at the configured interval.
    ///
    /// Uses tokio's test-util to pause time for deterministic testing.
    /// Uses metrics-util's DebuggingRecorder to verify actual metrics are reported.
    /// Inserts cache entries to verify metrics reflect actual cache state changes.
    #[tokio::test]
    async fn test_start_monitoring_reports_metrics_at_interval() -> Result<(), anyhow::Error> {
        use crate::cohorts::cohort_models::Cohort;
        use crate::metrics::consts::{COHORT_CACHE_ENTRIES_GAUGE, COHORT_CACHE_SIZE_BYTES_GAUGE};
        use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};
        use std::sync::OnceLock;

        // Install a global debugging recorder once per test process
        static SNAPSHOTTER: OnceLock<Snapshotter> = OnceLock::new();
        let snapshotter = SNAPSHOTTER.get_or_init(|| {
            let recorder = DebuggingRecorder::new();
            let snapshotter = recorder.snapshotter();
            drop(recorder.install());
            snapshotter
        });

        // Helper to get current gauge value for a metric
        let get_gauge_value = |metric_name: &str| -> Option<f64> {
            snapshotter
                .snapshot()
                .into_vec()
                .into_iter()
                .find(|(key, _, _, _)| key.key().name() == metric_name)
                .and_then(|(_, _, _, value)| {
                    if let DebugValue::Gauge(v) = value {
                        Some(v.into_inner())
                    } else {
                        None
                    }
                })
        };

        // Create context before pausing time (needs real time for DB connection)
        let context = TestContext::new(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(
            context.non_persons_reader.clone(),
            Some(1024 * 1024),
            None,
        ));

        // Pause time for deterministic testing
        tokio::time::pause();

        // Spawn the actual start_monitoring method
        let cohort_cache_clone = cohort_cache.clone();
        let monitor_handle = tokio::spawn(async move {
            cohort_cache_clone.start_monitoring(30).await;
        });

        // First tick is immediate - empty cache
        sleep(Duration::from_millis(1)).await;
        assert_eq!(
            get_gauge_value(COHORT_CACHE_SIZE_BYTES_GAUGE),
            Some(0.0),
            "Empty cache should report 0 bytes"
        );
        assert_eq!(
            get_gauge_value(COHORT_CACHE_ENTRIES_GAUGE),
            Some(0.0),
            "Empty cache should report 0 entries"
        );

        // Insert a cache entry directly
        let test_cohort = Cohort {
            id: 1,
            name: Some("Test Cohort".to_string()),
            description: None,
            team_id: 1,
            deleted: false,
            filters: Some(serde_json::json!({"properties": []})),
            query: None,
            version: Some(1),
            pending_version: None,
            count: None,
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups: serde_json::json!({}),
            created_by_id: None,
        };
        cohort_cache.cache.insert(1, vec![test_cohort]).await;
        // Moka caches update internal stats lazily - sync ensures stats are current
        cohort_cache.cache.run_pending_tasks().await;

        // Advance time by 30 seconds - should reflect the new cache entry
        sleep(Duration::from_secs(30)).await;
        assert!(
            get_gauge_value(COHORT_CACHE_SIZE_BYTES_GAUGE).unwrap() > 0.0,
            "Cache with entry should report non-zero bytes"
        );
        assert_eq!(
            get_gauge_value(COHORT_CACHE_ENTRIES_GAUGE),
            Some(1.0),
            "Cache with one entry should report 1 entry"
        );

        monitor_handle.abort();
        Ok(())
    }

    // ==================== Concurrency Tests ====================
    //
    // These tests verify the concurrency properties of CohortCacheManager:
    // - Same-team coalescing: concurrent requests for one team result in 1 DB fetch
    // - Cross-team parallelism: requests for different teams execute in parallel
    // - Error propagation: errors are propagated to all coalesced waiters
    // - Error not cached: failed fetches are retried on subsequent requests
    //
    // DESIGN NOTE: These tests use explicit synchronization (Notify, Barrier) instead
    // of timing delays to be deterministic regardless of OS scheduling or CI load.

    /// A mock fetcher that tracks call counts and supports synchronization primitives
    /// for testing concurrency behavior.
    struct MockFetcher {
        fetch_count: AtomicU32,
        /// Barrier to synchronize concurrent fetches - ensures they start together
        barrier: Option<Arc<Barrier>>,
        /// Cohorts to return on success
        cohorts: Vec<Cohort>,
    }

    impl MockFetcher {
        fn new(cohorts: Vec<Cohort>) -> Self {
            Self {
                fetch_count: AtomicU32::new(0),
                barrier: None,
                cohorts,
            }
        }

        fn with_barrier(mut self, barrier: Arc<Barrier>) -> Self {
            self.barrier = Some(barrier);
            self
        }

        fn fetch_count(&self) -> u32 {
            self.fetch_count.load(Ordering::SeqCst)
        }
    }

    #[async_trait]
    impl CohortFetcher for MockFetcher {
        async fn fetch(&self, _team_id: TeamId) -> Result<Vec<Cohort>, CohortFetchError> {
            self.fetch_count.fetch_add(1, Ordering::SeqCst);

            if let Some(barrier) = &self.barrier {
                barrier.wait().await;
            }

            Ok(self.cohorts.clone())
        }
    }

    /// A fetcher with explicit synchronization for testing coalescing behavior.
    ///
    /// Protocol:
    /// 1. Test spawns N tasks that call get_cohorts
    /// 2. First task enters fetch, signals `fetch_started`, waits on `may_complete`
    /// 3. Test receives `fetch_started`, yields to let other tasks queue, signals `may_complete`
    /// 4. Fetch completes, all coalesced tasks get the result
    /// 5. Assert only 1 fetch occurred
    struct CoalescingTestFetcher {
        fetch_count: AtomicU32,
        /// Signaled when fetch has started - test waits on this
        fetch_started: Arc<tokio::sync::Notify>,
        /// Fetcher waits on this before completing - test signals when ready
        may_complete: Arc<tokio::sync::Notify>,
        /// If set, return this error instead of success
        error: Option<CohortFetchError>,
        cohorts: Vec<Cohort>,
    }

    impl CoalescingTestFetcher {
        fn new(
            cohorts: Vec<Cohort>,
            fetch_started: Arc<tokio::sync::Notify>,
            may_complete: Arc<tokio::sync::Notify>,
        ) -> Self {
            Self {
                fetch_count: AtomicU32::new(0),
                fetch_started,
                may_complete,
                error: None,
                cohorts,
            }
        }

        fn with_error(mut self, error: CohortFetchError) -> Self {
            self.error = Some(error);
            self
        }

        fn fetch_count(&self) -> u32 {
            self.fetch_count.load(Ordering::SeqCst)
        }
    }

    #[async_trait]
    impl CohortFetcher for CoalescingTestFetcher {
        async fn fetch(&self, _team_id: TeamId) -> Result<Vec<Cohort>, CohortFetchError> {
            self.fetch_count.fetch_add(1, Ordering::SeqCst);

            // Signal that fetch has started
            self.fetch_started.notify_one();

            // Wait for permission to complete (test controls this)
            self.may_complete.notified().await;

            if let Some(ref error) = self.error {
                Err(error.clone())
            } else {
                Ok(self.cohorts.clone())
            }
        }
    }

    /// Tests that multiple concurrent requests for the same team result in exactly 1 DB fetch.
    ///
    /// This test is deterministic: it uses explicit synchronization to ensure all requests
    /// are queued before the fetch completes, regardless of OS scheduling.
    #[tokio::test]
    async fn test_same_team_coalescing() {
        const NUM_CONCURRENT_REQUESTS: usize = 10;
        const TEAM_ID: TeamId = 42;

        let fetch_started = Arc::new(tokio::sync::Notify::new());
        let may_complete = Arc::new(tokio::sync::Notify::new());

        let fetcher = CoalescingTestFetcher::new(
            vec![create_test_cohort(None)],
            Arc::clone(&fetch_started),
            Arc::clone(&may_complete),
        );

        let cache = CohortCacheManager::new_with_fetcher(fetcher, None, None);

        // Spawn concurrent requests for the same team
        let handles: Vec<_> = (0..NUM_CONCURRENT_REQUESTS)
            .map(|_| {
                let cache = cache.clone();
                tokio::spawn(async move { cache.get_cohorts(TEAM_ID).await })
            })
            .collect();

        // Wait for the fetch to start (with timeout for safety)
        tokio::time::timeout(Duration::from_secs(5), fetch_started.notified())
            .await
            .expect("Fetch should have started");

        // Yield to the executor multiple times to ensure all other tasks have
        // entered get_cohorts and are waiting on moka's internal coalescing.
        // This is deterministic: we're giving the executor explicit opportunities
        // to schedule all spawned tasks before we allow the fetch to complete.
        for _ in 0..NUM_CONCURRENT_REQUESTS {
            tokio::task::yield_now().await;
        }

        // Now allow the fetch to complete
        may_complete.notify_one();

        // Wait for all requests to complete
        let results =
            tokio::time::timeout(Duration::from_secs(5), futures::future::join_all(handles))
                .await
                .expect("All requests should complete");

        // All requests should succeed
        for result in &results {
            assert!(
                result.as_ref().unwrap().is_ok(),
                "All requests should succeed"
            );
        }

        // Only 1 fetch should have occurred due to coalescing
        assert_eq!(
            cache.fetcher.fetch_count(),
            1,
            "Only 1 DB fetch should occur for {} concurrent requests to the same team",
            NUM_CONCURRENT_REQUESTS
        );
    }

    /// Tests that concurrent requests for different teams execute in parallel.
    ///
    /// This test is deterministic: it uses a barrier inside the fetch that requires
    /// all N fetches to arrive before any can proceed. If fetches were serialized
    /// (as with the old global mutex), this would deadlock.
    #[tokio::test]
    async fn test_cross_team_parallelism() {
        const NUM_TEAMS: usize = 5;

        // Barrier requires all NUM_TEAMS fetches to arrive before any can proceed.
        // If fetches were serialized, this would deadlock.
        let barrier = Arc::new(Barrier::new(NUM_TEAMS));

        let fetcher = MockFetcher::new(vec![create_test_cohort(None)]).with_barrier(barrier);

        let cache = CohortCacheManager::new_with_fetcher(fetcher, None, None);

        // Spawn concurrent requests for different teams
        let handles: Vec<_> = (0..NUM_TEAMS)
            .map(|i| {
                let cache = cache.clone();
                let team_id = (i + 1) as TeamId;
                tokio::spawn(async move { cache.get_cohorts(team_id).await })
            })
            .collect();

        // Use a timeout to detect deadlock (would occur if fetches were serialized)
        let results =
            tokio::time::timeout(Duration::from_secs(5), futures::future::join_all(handles))
                .await
                .expect("Deadlock detected: cross-team requests should execute in parallel");

        // All requests should succeed
        for result in &results {
            assert!(
                result.as_ref().unwrap().is_ok(),
                "All requests should succeed"
            );
        }

        // Each team should have triggered exactly one fetch
        assert_eq!(
            cache.fetcher.fetch_count(),
            NUM_TEAMS as u32,
            "Each team should trigger exactly one fetch"
        );
    }

    /// Tests that when a fetch fails, all coalesced waiters receive the error.
    ///
    /// Uses the same deterministic synchronization as test_same_team_coalescing.
    #[tokio::test]
    async fn test_error_propagation_to_coalesced_waiters() {
        const NUM_CONCURRENT_REQUESTS: usize = 5;
        const TEAM_ID: TeamId = 42;

        let fetch_started = Arc::new(tokio::sync::Notify::new());
        let may_complete = Arc::new(tokio::sync::Notify::new());

        let fetcher = CoalescingTestFetcher::new(
            vec![],
            Arc::clone(&fetch_started),
            Arc::clone(&may_complete),
        )
        .with_error(CohortFetchError::DatabaseUnavailable);

        let cache = CohortCacheManager::new_with_fetcher(fetcher, None, None);

        // Spawn concurrent requests
        let handles: Vec<_> = (0..NUM_CONCURRENT_REQUESTS)
            .map(|_| {
                let cache = cache.clone();
                tokio::spawn(async move { cache.get_cohorts(TEAM_ID).await })
            })
            .collect();

        // Wait for the fetch to start
        tokio::time::timeout(Duration::from_secs(5), fetch_started.notified())
            .await
            .expect("Fetch should have started");

        // Yield to let all other tasks queue up
        for _ in 0..NUM_CONCURRENT_REQUESTS {
            tokio::task::yield_now().await;
        }

        // Allow the fetch to complete (with error)
        may_complete.notify_one();

        let results =
            tokio::time::timeout(Duration::from_secs(5), futures::future::join_all(handles))
                .await
                .expect("All requests should complete");

        // All requests should receive the error
        for (i, result) in results.iter().enumerate() {
            let inner = result.as_ref().unwrap();
            assert!(
                inner.is_err(),
                "Request {} should have received an error",
                i
            );
            assert!(
                matches!(inner, Err(FlagError::DatabaseUnavailable)),
                "Request {} should have received DatabaseUnavailable error",
                i
            );
        }

        // Only 1 fetch should have occurred
        assert_eq!(
            cache.fetcher.fetch_count(),
            1,
            "Only 1 DB fetch should occur even when it fails"
        );
    }

    /// Tests that errors are not cached - subsequent requests should retry the fetch.
    #[tokio::test]
    async fn test_error_not_cached() {
        const TEAM_ID: TeamId = 42;

        // Use an atomic to track whether we should return an error
        let should_fail = Arc::new(std::sync::atomic::AtomicBool::new(true));
        let fetch_count = Arc::new(AtomicU32::new(0));

        // Create a custom fetcher that fails on first call, succeeds on second
        struct ConditionalFetcher {
            should_fail: Arc<std::sync::atomic::AtomicBool>,
            fetch_count: Arc<AtomicU32>,
        }

        #[async_trait]
        impl CohortFetcher for ConditionalFetcher {
            async fn fetch(&self, team_id: TeamId) -> Result<Vec<Cohort>, CohortFetchError> {
                self.fetch_count.fetch_add(1, Ordering::SeqCst);

                if self.should_fail.load(Ordering::SeqCst) {
                    Err(CohortFetchError::DatabaseUnavailable)
                } else {
                    Ok(vec![Cohort {
                        id: 1,
                        name: Some("Test".to_string()),
                        description: None,
                        team_id,
                        deleted: false,
                        filters: None,
                        query: None,
                        version: Some(1),
                        pending_version: None,
                        count: None,
                        is_calculating: false,
                        is_static: false,
                        errors_calculating: 0,
                        groups: serde_json::json!({}),
                        created_by_id: None,
                    }])
                }
            }
        }

        let fetcher = ConditionalFetcher {
            should_fail: Arc::clone(&should_fail),
            fetch_count: Arc::clone(&fetch_count),
        };

        let cache = CohortCacheManager::new_with_fetcher(fetcher, None, None);

        // First request should fail
        let result1 = cache.get_cohorts(TEAM_ID).await;
        assert!(result1.is_err(), "First request should fail");
        assert_eq!(
            fetch_count.load(Ordering::SeqCst),
            1,
            "Should have fetched once"
        );

        // Disable failure mode
        should_fail.store(false, Ordering::SeqCst);

        // Second request should retry and succeed (error was not cached)
        let result2 = cache.get_cohorts(TEAM_ID).await;
        assert!(result2.is_ok(), "Second request should succeed after retry");
        assert_eq!(
            fetch_count.load(Ordering::SeqCst),
            2,
            "Should have fetched twice (error was not cached)"
        );

        // Third request should hit the cache
        let result3 = cache.get_cohorts(TEAM_ID).await;
        assert!(result3.is_ok(), "Third request should succeed from cache");
        assert_eq!(
            fetch_count.load(Ordering::SeqCst),
            2,
            "Should not fetch again (success was cached)"
        );
    }

    /// Tests that the second request for the same team hits the cache (no DB call).
    #[tokio::test]
    async fn test_cache_hit_path() {
        const TEAM_ID: TeamId = 42;

        let fetcher = MockFetcher::new(vec![create_test_cohort(None)]);

        let cache = CohortCacheManager::new_with_fetcher(fetcher, None, None);

        // First request - cache miss
        let result1 = cache.get_cohorts(TEAM_ID).await;
        assert!(result1.is_ok(), "First request should succeed");
        assert_eq!(cache.fetcher.fetch_count(), 1, "Should have fetched once");

        // Second request - cache hit
        let result2 = cache.get_cohorts(TEAM_ID).await;
        assert!(result2.is_ok(), "Second request should succeed");
        assert_eq!(
            cache.fetcher.fetch_count(),
            1,
            "Should not fetch again (cache hit)"
        );

        // Verify both requests returned the same data
        assert_eq!(
            result1.unwrap().len(),
            result2.unwrap().len(),
            "Both requests should return the same cohorts"
        );
    }

    /// Tests that CohortFetchError variants map correctly to FlagError.
    #[test]
    fn test_cohort_fetch_error_conversion() {
        // DatabaseUnavailable -> FlagError::DatabaseUnavailable
        let db_unavailable = CohortFetchError::DatabaseUnavailable;
        let flag_error: FlagError = db_unavailable.into();
        assert!(
            matches!(flag_error, FlagError::DatabaseUnavailable),
            "DatabaseUnavailable should map to FlagError::DatabaseUnavailable"
        );

        // QueryFailed -> FlagError::Internal
        let query_failed = CohortFetchError::QueryFailed("test error".to_string());
        let flag_error: FlagError = query_failed.into();
        assert!(
            matches!(flag_error, FlagError::Internal(msg) if msg == "test error"),
            "QueryFailed should map to FlagError::Internal with the message"
        );
    }
}
