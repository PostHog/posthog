use crate::api::FlagError;
use crate::cohort_models::Cohort;
use crate::flag_matching::{PostgresReader, TeamId};
use moka::future::Cache;
use std::time::Duration;

/// CohortCacheManager manages the in-memory cache of cohorts using `moka` for caching.
///
/// Features:
/// - **TTL**: Each cache entry expires after 5 minutes.
/// - **Size-based eviction**: The cache evicts least recently used entries when the maximum capacity is reached.
///
/// ```text
/// CohortCacheManager {
///     postgres_reader: PostgresReader,
///     per_team_cohorts: Cache<TeamId, Vec<Cohort>> {
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
#[derive(Clone)]
pub struct CohortCacheManager {
    postgres_reader: PostgresReader,
    per_team_cohort_cache: Cache<TeamId, Vec<Cohort>>,
}

impl CohortCacheManager {
    pub fn new(
        postgres_reader: PostgresReader,
        max_capacity: Option<u64>,
        ttl_seconds: Option<u64>,
    ) -> Self {
        // We use the size of the cohort list (i.e., the number of cohorts for a given team)as the weight of the entry
        let weigher =
            |_: &TeamId, value: &Vec<Cohort>| -> u32 { value.len().try_into().unwrap_or(u32::MAX) };

        let cache = Cache::builder()
            .time_to_live(Duration::from_secs(ttl_seconds.unwrap_or(300))) // Default to 5 minutes
            .weigher(weigher)
            .max_capacity(max_capacity.unwrap_or(10_000)) // Default to 10,000 cohorts
            .build();

        Self {
            postgres_reader,
            per_team_cohort_cache: cache,
        }
    }

    /// Retrieves cohorts for a given team.
    ///
    /// If the cohorts are not present in the cache or have expired, it fetches them from the database,
    /// caches the result upon successful retrieval, and then returns it.
    pub async fn get_cohorts_for_team(&self, team_id: TeamId) -> Result<Vec<Cohort>, FlagError> {
        if let Some(cached_cohorts) = self.per_team_cohort_cache.get(&team_id).await {
            return Ok(cached_cohorts.clone());
        }
        let fetched_cohorts = Cohort::list_from_pg(self.postgres_reader.clone(), team_id).await?;
        self.per_team_cohort_cache
            .insert(team_id, fetched_cohorts.clone())
            .await;

        Ok(fetched_cohorts)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cohort_models::Cohort;
    use crate::test_utils::{
        insert_cohort_for_team_in_pg, insert_new_team_in_pg, setup_pg_reader_client,
        setup_pg_writer_client,
    };
    use std::sync::Arc;
    use tokio::time::{sleep, Duration};

    /// Helper function to setup a new team for testing.
    async fn setup_test_team(
        writer_client: Arc<dyn crate::database::Client + Send + Sync>,
    ) -> Result<TeamId, anyhow::Error> {
        let team = crate::test_utils::insert_new_team_in_pg(writer_client, None).await?;
        Ok(team.id)
    }

    /// Helper function to insert a cohort for a team.
    async fn setup_test_cohort(
        writer_client: Arc<dyn crate::database::Client + Send + Sync>,
        team_id: TeamId,
        name: Option<String>,
    ) -> Result<Cohort, anyhow::Error> {
        let filters = serde_json::json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$active", "type": "person", "value": [true], "negation": false, "operator": "exact"}]}]}});
        insert_cohort_for_team_in_pg(writer_client, team_id, name, filters, false).await
    }

    /// Tests that cache entries expire after the specified TTL.
    #[tokio::test]
    async fn test_cache_expiry() -> Result<(), anyhow::Error> {
        let writer_client = setup_pg_writer_client(None).await;
        let reader_client = setup_pg_reader_client(None).await;

        let team_id = setup_test_team(writer_client.clone()).await?;
        let _cohort = setup_test_cohort(writer_client.clone(), team_id, None).await?;

        // Initialize CohortCacheManager with a short TTL for testing
        let cohort_cache = CohortCacheManager::new(
            reader_client.clone(),
            Some(100),
            Some(1), // 1-second TTL
        );

        let cohorts = cohort_cache.get_cohorts_for_team(team_id).await?;
        assert_eq!(cohorts.len(), 1);
        assert_eq!(cohorts[0].team_id, team_id);

        let cached_cohorts = cohort_cache.per_team_cohort_cache.get(&team_id).await;
        assert!(cached_cohorts.is_some());

        // Wait for TTL to expire
        sleep(Duration::from_secs(2)).await;

        // Attempt to retrieve from cache again
        let cached_cohorts = cohort_cache.per_team_cohort_cache.get(&team_id).await;
        assert!(cached_cohorts.is_none(), "Cache entry should have expired");

        Ok(())
    }

    /// Tests that the cache correctly evicts least recently used entries based on the weigher.
    #[tokio::test]
    async fn test_cache_weigher() -> Result<(), anyhow::Error> {
        let writer_client = setup_pg_writer_client(None).await;
        let reader_client = setup_pg_reader_client(None).await;

        // Define a smaller max_capacity for testing
        let max_capacity: u64 = 3;

        let cohort_cache = CohortCacheManager::new(reader_client.clone(), Some(max_capacity), None);

        let mut inserted_team_ids = Vec::new();

        // Insert multiple teams and their cohorts
        for _ in 0..max_capacity {
            let team = insert_new_team_in_pg(writer_client.clone(), None).await?;
            let team_id = team.id;
            inserted_team_ids.push(team_id);
            setup_test_cohort(writer_client.clone(), team_id, None).await?;
            cohort_cache.get_cohorts_for_team(team_id).await?;
        }

        cohort_cache.per_team_cohort_cache.run_pending_tasks().await;
        let cache_size = cohort_cache.per_team_cohort_cache.entry_count();
        assert_eq!(
            cache_size, max_capacity,
            "Cache size should be equal to max_capacity"
        );

        let new_team = insert_new_team_in_pg(writer_client.clone(), None).await?;
        let new_team_id = new_team.id;
        setup_test_cohort(writer_client.clone(), new_team_id, None).await?;
        cohort_cache.get_cohorts_for_team(new_team_id).await?;

        cohort_cache.per_team_cohort_cache.run_pending_tasks().await;
        let cache_size_after = cohort_cache.per_team_cohort_cache.entry_count();
        assert_eq!(
            cache_size_after, max_capacity,
            "Cache size should remain equal to max_capacity after eviction"
        );

        let evicted_team_id = &inserted_team_ids[0];
        let cached_cohorts = cohort_cache
            .per_team_cohort_cache
            .get(evicted_team_id)
            .await;
        assert!(
            cached_cohorts.is_none(),
            "Least recently used cache entry should have been evicted"
        );

        let cached_new_team = cohort_cache.per_team_cohort_cache.get(&new_team_id).await;
        assert!(
            cached_new_team.is_some(),
            "Newly added cache entry should be present"
        );

        Ok(())
    }

    #[tokio::test]
    async fn test_get_cohorts_for_team() -> Result<(), anyhow::Error> {
        let writer_client = setup_pg_writer_client(None).await;
        let reader_client = setup_pg_reader_client(None).await;
        let team_id = setup_test_team(writer_client.clone()).await?;
        let _cohort = setup_test_cohort(writer_client.clone(), team_id, None).await?;
        let cohort_cache = CohortCacheManager::new(reader_client.clone(), None, None);

        let cached_cohorts = cohort_cache.per_team_cohort_cache.get(&team_id).await;
        assert!(cached_cohorts.is_none(), "Cache should initially be empty");

        let cohorts = cohort_cache.get_cohorts_for_team(team_id).await?;
        assert_eq!(cohorts.len(), 1);
        assert_eq!(cohorts[0].team_id, team_id);

        let cached_cohorts = cohort_cache
            .per_team_cohort_cache
            .get(&team_id)
            .await
            .unwrap();
        assert_eq!(cached_cohorts.len(), 1);
        assert_eq!(cached_cohorts[0].team_id, team_id);

        Ok(())
    }
}
