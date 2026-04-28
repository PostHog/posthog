use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common_database::PostgresReader;
use common_types::TeamId;
use moka::future::Cache;
use sqlx::FromRow;
use tracing::error;

use crate::{
    api::errors::FlagError,
    database::get_connection_with_metrics,
    metrics::consts::{
        DB_GROUP_TYPE_ERRORS_COUNTER, DB_GROUP_TYPE_READS_COUNTER, GROUP_TYPE_CACHE_ENTRIES_GAUGE,
        GROUP_TYPE_CACHE_HIT_COUNTER, GROUP_TYPE_CACHE_MISS_COUNTER,
    },
};

pub type GroupTypeIndex = i32;

/// DB row struct for the posthog_grouptypemapping table.
#[derive(Debug, FromRow)]
struct GroupTypeMappingRow {
    pub group_type: String,
    pub group_type_index: GroupTypeIndex,
}

/// Holds the bidirectional mapping between group type names and their indices.
///
/// Typically, the mappings look like this:
///
/// ```text
/// ("project", 0), ("organization", 1), ("instance", 2), ("customer", 3), ("team", 4)
/// ```
///
/// These mappings are ingested via the plugin server.
#[derive(Clone, Debug)]
pub struct GroupTypeMapping {
    group_types_to_indexes: HashMap<String, GroupTypeIndex>,
    group_indexes_to_types: HashMap<GroupTypeIndex, String>,
}

impl GroupTypeMapping {
    pub fn new(types_to_indexes: HashMap<String, GroupTypeIndex>) -> Self {
        let group_indexes_to_types: HashMap<GroupTypeIndex, String> = types_to_indexes
            .iter()
            .map(|(k, v)| (*v, k.clone()))
            .collect();
        Self {
            group_types_to_indexes: types_to_indexes,
            group_indexes_to_types,
        }
    }

    pub fn group_types_to_indexes(&self) -> &HashMap<String, GroupTypeIndex> {
        &self.group_types_to_indexes
    }

    pub fn group_indexes_to_types(&self) -> &HashMap<GroupTypeIndex, String> {
        &self.group_indexes_to_types
    }

    pub fn is_empty(&self) -> bool {
        self.group_types_to_indexes.is_empty()
    }
}

#[derive(Clone, Debug)]
pub enum GroupTypeFetchError {
    DatabaseUnavailable,
    QueryFailed(String),
}

impl From<GroupTypeFetchError> for FlagError {
    fn from(value: GroupTypeFetchError) -> Self {
        match value {
            GroupTypeFetchError::DatabaseUnavailable => FlagError::DatabaseUnavailable,
            GroupTypeFetchError::QueryFailed(msg) => FlagError::Internal(msg),
        }
    }
}

#[async_trait]
pub trait GroupTypeMappingFetcher: Send + Sync + 'static {
    async fn fetch(&self, team_id: TeamId) -> Result<GroupTypeMapping, GroupTypeFetchError>;
}

#[derive(Clone)]
pub struct PostgresGroupTypeMappingFetcher {
    reader: PostgresReader,
}

impl PostgresGroupTypeMappingFetcher {
    pub fn new(reader: PostgresReader) -> Self {
        Self { reader }
    }
}

#[async_trait]
impl GroupTypeMappingFetcher for PostgresGroupTypeMappingFetcher {
    async fn fetch(&self, team_id: TeamId) -> Result<GroupTypeMapping, GroupTypeFetchError> {
        let mut conn =
            get_connection_with_metrics(&self.reader, "persons_reader", "fetch_group_type_mapping")
                .await
                .map_err(|_| GroupTypeFetchError::DatabaseUnavailable)?;

        let query = r#"
            SELECT group_type, group_type_index
            FROM posthog_grouptypemapping
            WHERE team_id = $1
        "#;

        let rows = sqlx::query_as::<_, GroupTypeMappingRow>(query)
            .bind(team_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| GroupTypeFetchError::QueryFailed(e.to_string()))?;

        let types_to_indexes: HashMap<String, GroupTypeIndex> = rows
            .into_iter()
            .map(|row| (row.group_type, row.group_type_index))
            .collect();

        Ok(GroupTypeMapping::new(types_to_indexes))
    }
}

/// In-process Moka cache for group type mappings, keyed by TeamId.
pub struct GroupTypeCacheManager {
    fetcher: Arc<dyn GroupTypeMappingFetcher>,
    cache: Cache<TeamId, GroupTypeMapping>,
}

impl GroupTypeCacheManager {
    const DEFAULT_MAX_ENTRIES: u64 = 50_000;

    pub fn new(reader: PostgresReader, max_entries: Option<u64>, ttl_seconds: Option<u64>) -> Self {
        let fetcher = PostgresGroupTypeMappingFetcher::new(reader);
        Self::new_with_fetcher(fetcher, max_entries, ttl_seconds)
    }

    pub fn new_with_fetcher(
        fetcher: impl GroupTypeMappingFetcher,
        max_entries: Option<u64>,
        ttl_seconds: Option<u64>,
    ) -> Self {
        let cache = Cache::builder()
            .time_to_live(Duration::from_secs(ttl_seconds.unwrap_or(300)))
            .max_capacity(max_entries.unwrap_or(Self::DEFAULT_MAX_ENTRIES))
            .build();

        Self {
            fetcher: Arc::new(fetcher),
            cache,
        }
    }

    /// Retrieves group type mappings for a given team.
    ///
    /// Uses moka's `try_get_with` for per-key coalescing:
    /// - If cached: returns immediately (cache hit)
    /// - If not cached: only one caller fetches from DB, others wait for the result
    /// - Different teams fetch in parallel (no cross-team blocking)
    pub async fn get_mappings(&self, team_id: TeamId) -> Result<GroupTypeMapping, FlagError> {
        let was_cached = self.cache.contains_key(&team_id);
        let fetcher = self.fetcher.clone();

        let result = self
            .cache
            .try_get_with(team_id, async move {
                match fetcher.fetch(team_id).await {
                    Ok(mapping) => {
                        common_metrics::inc(DB_GROUP_TYPE_READS_COUNTER, &[], 1);
                        Ok(mapping)
                    }
                    Err(e) => {
                        common_metrics::inc(DB_GROUP_TYPE_ERRORS_COUNTER, &[], 1);
                        error!(
                            team_id = team_id,
                            error = ?e,
                            "Failed to fetch group type mappings"
                        );
                        Err(e)
                    }
                }
            })
            .await
            .map_err(|arc_err| FlagError::from((*arc_err).clone()));

        // NB: Under coalescing, concurrent cold-key callers all see was_cached=false,
        // inflating misses. This only happens on cold start / TTL expiry and is acceptable.
        if was_cached {
            common_metrics::inc(GROUP_TYPE_CACHE_HIT_COUNTER, &[], 1);
        } else {
            common_metrics::inc(GROUP_TYPE_CACHE_MISS_COUNTER, &[], 1);
        }

        self.report_cache_metrics();

        result
    }

    fn report_cache_metrics(&self) {
        common_metrics::gauge(
            GROUP_TYPE_CACHE_ENTRIES_GAUGE,
            &[],
            self.cache.entry_count() as f64,
        );
    }
}

impl Clone for GroupTypeCacheManager {
    fn clone(&self) -> Self {
        Self {
            fetcher: Arc::clone(&self.fetcher),
            cache: self.cache.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use std::sync::atomic::{AtomicU32, Ordering};
    use tokio::sync::Barrier;
    use tokio::time::{sleep, Duration};

    struct MockGroupTypeFetcher {
        fetch_count: Arc<AtomicU32>,
        mapping: GroupTypeMapping,
        barrier: Option<Arc<Barrier>>,
    }

    impl MockGroupTypeFetcher {
        fn new(
            types_to_indexes: HashMap<String, GroupTypeIndex>,
            fetch_count: Arc<AtomicU32>,
        ) -> Self {
            Self {
                fetch_count,
                mapping: GroupTypeMapping::new(types_to_indexes),
                barrier: None,
            }
        }

        fn with_barrier(mut self, barrier: Arc<Barrier>) -> Self {
            self.barrier = Some(barrier);
            self
        }
    }

    #[async_trait]
    impl GroupTypeMappingFetcher for MockGroupTypeFetcher {
        async fn fetch(&self, _team_id: TeamId) -> Result<GroupTypeMapping, GroupTypeFetchError> {
            self.fetch_count.fetch_add(1, Ordering::SeqCst);

            if let Some(barrier) = &self.barrier {
                barrier.wait().await;
            }

            Ok(self.mapping.clone())
        }
    }

    struct CoalescingTestFetcher {
        fetch_count: Arc<AtomicU32>,
        fetch_started: Arc<tokio::sync::Notify>,
        may_complete: Arc<tokio::sync::Notify>,
        error: Option<GroupTypeFetchError>,
        mapping: GroupTypeMapping,
    }

    impl CoalescingTestFetcher {
        fn new(
            mapping: GroupTypeMapping,
            fetch_count: Arc<AtomicU32>,
            fetch_started: Arc<tokio::sync::Notify>,
            may_complete: Arc<tokio::sync::Notify>,
        ) -> Self {
            Self {
                fetch_count,
                fetch_started,
                may_complete,
                error: None,
                mapping,
            }
        }
    }

    #[async_trait]
    impl GroupTypeMappingFetcher for CoalescingTestFetcher {
        async fn fetch(&self, _team_id: TeamId) -> Result<GroupTypeMapping, GroupTypeFetchError> {
            self.fetch_count.fetch_add(1, Ordering::SeqCst);
            self.fetch_started.notify_one();
            self.may_complete.notified().await;

            if let Some(ref error) = self.error {
                Err(error.clone())
            } else {
                Ok(self.mapping.clone())
            }
        }
    }

    fn test_mapping() -> HashMap<String, GroupTypeIndex> {
        [("project".to_string(), 0), ("organization".to_string(), 1)]
            .into_iter()
            .collect()
    }

    #[tokio::test]
    async fn test_cache_hit_path() {
        const TEAM_ID: TeamId = 42;

        let fetch_count = Arc::new(AtomicU32::new(0));
        let fetcher = MockGroupTypeFetcher::new(test_mapping(), fetch_count.clone());
        let cache = GroupTypeCacheManager::new_with_fetcher(fetcher, None, None);

        // First request - cache miss
        let result1 = cache.get_mappings(TEAM_ID).await;
        assert!(result1.is_ok());
        assert_eq!(fetch_count.load(Ordering::SeqCst), 1);

        // Second request - cache hit
        let result2 = cache.get_mappings(TEAM_ID).await;
        assert!(result2.is_ok());
        assert_eq!(fetch_count.load(Ordering::SeqCst), 1);

        // Both should return the same data
        let m1 = result1.unwrap();
        let m2 = result2.unwrap();
        assert_eq!(
            m1.group_types_to_indexes().len(),
            m2.group_types_to_indexes().len()
        );
    }

    #[tokio::test]
    async fn test_cache_expiry() {
        const TEAM_ID: TeamId = 42;

        let fetch_count = Arc::new(AtomicU32::new(0));
        let fetcher = MockGroupTypeFetcher::new(test_mapping(), fetch_count.clone());
        let cache = GroupTypeCacheManager::new_with_fetcher(fetcher, None, Some(1));

        let result = cache.get_mappings(TEAM_ID).await;
        assert!(result.is_ok());
        assert_eq!(fetch_count.load(Ordering::SeqCst), 1);

        // Wait for TTL to expire
        sleep(Duration::from_secs(2)).await;

        // Cache entry should have expired
        let cached = cache.cache.get(&TEAM_ID).await;
        assert!(cached.is_none(), "Cache entry should have expired");

        // Next request should fetch again
        let result2 = cache.get_mappings(TEAM_ID).await;
        assert!(result2.is_ok());
        assert_eq!(fetch_count.load(Ordering::SeqCst), 2);
    }

    #[tokio::test]
    async fn test_same_team_coalescing() {
        const NUM_CONCURRENT_REQUESTS: usize = 10;
        const TEAM_ID: TeamId = 42;

        let fetch_count = Arc::new(AtomicU32::new(0));
        let fetch_started = Arc::new(tokio::sync::Notify::new());
        let may_complete = Arc::new(tokio::sync::Notify::new());

        let fetcher = CoalescingTestFetcher::new(
            GroupTypeMapping::new(test_mapping()),
            fetch_count.clone(),
            Arc::clone(&fetch_started),
            Arc::clone(&may_complete),
        );

        let cache = GroupTypeCacheManager::new_with_fetcher(fetcher, None, None);

        let handles: Vec<_> = (0..NUM_CONCURRENT_REQUESTS)
            .map(|_| {
                let cache = cache.clone();
                tokio::spawn(async move { cache.get_mappings(TEAM_ID).await })
            })
            .collect();

        tokio::time::timeout(Duration::from_secs(5), fetch_started.notified())
            .await
            .expect("Fetch should have started");

        for _ in 0..NUM_CONCURRENT_REQUESTS {
            tokio::task::yield_now().await;
        }

        may_complete.notify_one();

        let results =
            tokio::time::timeout(Duration::from_secs(5), futures::future::join_all(handles))
                .await
                .expect("All requests should complete");

        for result in &results {
            assert!(result.as_ref().unwrap().is_ok());
        }

        assert_eq!(
            fetch_count.load(Ordering::SeqCst),
            1,
            "Only 1 DB fetch should occur for {} concurrent requests to the same team",
            NUM_CONCURRENT_REQUESTS
        );
    }

    #[tokio::test]
    async fn test_cross_team_parallelism() {
        const NUM_TEAMS: usize = 5;

        let fetch_count = Arc::new(AtomicU32::new(0));
        let barrier = Arc::new(Barrier::new(NUM_TEAMS));
        let fetcher =
            MockGroupTypeFetcher::new(test_mapping(), fetch_count.clone()).with_barrier(barrier);
        let cache = GroupTypeCacheManager::new_with_fetcher(fetcher, None, None);

        let handles: Vec<_> = (0..NUM_TEAMS)
            .map(|i| {
                let cache = cache.clone();
                let team_id = (i + 1) as TeamId;
                tokio::spawn(async move { cache.get_mappings(team_id).await })
            })
            .collect();

        let results =
            tokio::time::timeout(Duration::from_secs(5), futures::future::join_all(handles))
                .await
                .expect("Deadlock detected: cross-team requests should execute in parallel");

        for result in &results {
            assert!(result.as_ref().unwrap().is_ok());
        }

        assert_eq!(fetch_count.load(Ordering::SeqCst), NUM_TEAMS as u32);
    }

    #[tokio::test]
    async fn test_error_not_cached() {
        const TEAM_ID: TeamId = 42;

        let should_fail = Arc::new(std::sync::atomic::AtomicBool::new(true));
        let fetch_count = Arc::new(AtomicU32::new(0));

        struct ConditionalFetcher {
            should_fail: Arc<std::sync::atomic::AtomicBool>,
            fetch_count: Arc<AtomicU32>,
        }

        #[async_trait]
        impl GroupTypeMappingFetcher for ConditionalFetcher {
            async fn fetch(
                &self,
                _team_id: TeamId,
            ) -> Result<GroupTypeMapping, GroupTypeFetchError> {
                self.fetch_count.fetch_add(1, Ordering::SeqCst);

                if self.should_fail.load(Ordering::SeqCst) {
                    Err(GroupTypeFetchError::DatabaseUnavailable)
                } else {
                    Ok(GroupTypeMapping::new(
                        [("project".to_string(), 0)].into_iter().collect(),
                    ))
                }
            }
        }

        let fetcher = ConditionalFetcher {
            should_fail: Arc::clone(&should_fail),
            fetch_count: Arc::clone(&fetch_count),
        };

        let cache = GroupTypeCacheManager::new_with_fetcher(fetcher, None, None);

        let result1 = cache.get_mappings(TEAM_ID).await;
        assert!(result1.is_err());
        assert_eq!(fetch_count.load(Ordering::SeqCst), 1);

        should_fail.store(false, Ordering::SeqCst);

        let result2 = cache.get_mappings(TEAM_ID).await;
        assert!(result2.is_ok());
        assert_eq!(fetch_count.load(Ordering::SeqCst), 2);

        // Third request should hit cache
        let result3 = cache.get_mappings(TEAM_ID).await;
        assert!(result3.is_ok());
        assert_eq!(fetch_count.load(Ordering::SeqCst), 2);
    }

    #[tokio::test]
    async fn test_empty_mapping_not_treated_as_error() {
        const TEAM_ID: TeamId = 42;

        let fetch_count = Arc::new(AtomicU32::new(0));
        let fetcher = MockGroupTypeFetcher::new(HashMap::new(), fetch_count.clone());
        let cache = GroupTypeCacheManager::new_with_fetcher(fetcher, None, None);

        // Empty mappings should be cached successfully (not treated as an error)
        let result = cache.get_mappings(TEAM_ID).await;
        assert!(result.is_ok());
        let mapping = result.unwrap();
        assert!(mapping.is_empty());
        assert_eq!(fetch_count.load(Ordering::SeqCst), 1);

        // Second request should hit cache (empty mapping was cached)
        let result2 = cache.get_mappings(TEAM_ID).await;
        assert!(result2.is_ok());
        assert_eq!(fetch_count.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn test_group_type_fetch_error_conversion() {
        let db_unavailable = GroupTypeFetchError::DatabaseUnavailable;
        let flag_error: FlagError = db_unavailable.into();
        assert!(matches!(flag_error, FlagError::DatabaseUnavailable));

        let query_failed = GroupTypeFetchError::QueryFailed("test error".to_string());
        let flag_error: FlagError = query_failed.into();
        assert!(matches!(flag_error, FlagError::Internal(msg) if msg == "test error"));
    }

    #[test]
    fn test_group_type_mapping_new() {
        let types_to_indexes: HashMap<String, GroupTypeIndex> =
            [("project".to_string(), 0), ("organization".to_string(), 1)]
                .into_iter()
                .collect();

        let mapping = GroupTypeMapping::new(types_to_indexes);

        assert_eq!(mapping.group_types_to_indexes().len(), 2);
        assert_eq!(mapping.group_indexes_to_types().len(), 2);
        assert_eq!(mapping.group_types_to_indexes().get("project"), Some(&0));
        assert_eq!(
            mapping.group_indexes_to_types().get(&1),
            Some(&"organization".to_string())
        );
        assert!(!mapping.is_empty());
    }

    #[test]
    fn test_group_type_mapping_empty() {
        let mapping = GroupTypeMapping::new(HashMap::new());
        assert!(mapping.is_empty());
        assert_eq!(mapping.group_types_to_indexes().len(), 0);
        assert_eq!(mapping.group_indexes_to_types().len(), 0);
    }
}
