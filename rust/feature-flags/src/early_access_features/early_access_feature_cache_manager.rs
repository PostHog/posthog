use crate::api::errors::FlagError;
use crate::early_access_features::early_access_feature_models::EarlyAccessFeature;
use crate::metrics::consts::{
    DB_EARLY_ACCESS_FEATURE_ERRORS_COUNTER, DB_EARLY_ACCESS_FEATURE_READS_COUNTER,
    EARLY_ACCESS_FEATURE_CACHE_HIT_COUNTER, EARLY_ACCESS_FEATURE_CACHE_MISS_COUNTER,
};
use common_database::PostgresReader;
use common_types::ProjectId;
use moka::future::Cache;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;

#[derive(Clone)]
pub struct EarlyAccessFeatureCacheManager {
    reader: PostgresReader,
    cache: Cache<ProjectId, Vec<EarlyAccessFeature>>,
    fetch_lock: Arc<Mutex<()>>,
}

impl EarlyAccessFeatureCacheManager {
    pub fn new(
        reader: PostgresReader,
        max_capacity: Option<u64>,
        ttl_seconds: Option<u64>,
    ) -> Self {
        let cache = Cache::builder()
            .time_to_live(Duration::from_secs(ttl_seconds.unwrap_or(300)))
            .max_capacity(max_capacity.unwrap_or(100_000))
            .build();

        Self {
            reader,
            cache,
            fetch_lock: Arc::new(Mutex::new(())),
        }
    }
    pub async fn get_early_access_features(
        &self,
        project_id: ProjectId,
    ) -> Result<Vec<EarlyAccessFeature>, FlagError> {
        if let Some(cached_early_access_features) = self.cache.get(&project_id).await {
            common_metrics::inc(EARLY_ACCESS_FEATURE_CACHE_HIT_COUNTER, &[], 1);
            return Ok(cached_early_access_features.clone());
        }

        let _lock = self.fetch_lock.lock().await;

        // Double-check the cache after acquiring lock
        if let Some(cached_early_access_features) = self.cache.get(&project_id).await {
            common_metrics::inc(EARLY_ACCESS_FEATURE_CACHE_HIT_COUNTER, &[], 1);
            return Ok(cached_early_access_features.clone());
        }

        // If we get here, we have a cache miss
        common_metrics::inc(EARLY_ACCESS_FEATURE_CACHE_MISS_COUNTER, &[], 1);

        // Attempt to fetch from DB
        match EarlyAccessFeature::list_from_pg(self.reader.clone(), project_id).await {
            Ok(fetched_early_access_features) => {
                common_metrics::inc(DB_EARLY_ACCESS_FEATURE_READS_COUNTER, &[], 1);
                self.cache
                    .insert(project_id, fetched_early_access_features.clone())
                    .await;
                Ok(fetched_early_access_features)
            }
            Err(e) => {
                common_metrics::inc(DB_EARLY_ACCESS_FEATURE_ERRORS_COUNTER, &[], 1);
                Err(e)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::TestContext;
    use tokio::time::{sleep, Duration};

    #[tokio::test]
    async fn test_cache_expiry() -> Result<(), anyhow::Error> {
        let context = TestContext::new(None).await;
        let team = context.insert_new_team(None).await?;

        let _early_access_feature = context
            .insert_early_access_feature(team.id, None, None)
            .await?;

        // Initialize Cache with a short TTL for testing
        let early_access_feature_cache = EarlyAccessFeatureCacheManager::new(
            context.non_persons_reader.clone(),
            Some(100),
            Some(1),
        );

        let early_access_features = early_access_feature_cache
            .get_early_access_features(team.project_id)
            .await?;
        assert_eq!(early_access_features.len(), 1);
        assert_eq!(early_access_features[0].team_id, Some(team.id));

        let cached_early_access_features =
            early_access_feature_cache.cache.get(&team.project_id).await;

        assert!(cached_early_access_features.is_some());

        // Wait for TTL to expire
        sleep(Duration::from_secs(2)).await;

        let cached_early_access_features =
            early_access_feature_cache.cache.get(&team.project_id).await;

        assert!(cached_early_access_features.is_none(), "Cache entry should have expired");

        Ok(())
    }

    #[tokio::test]
    async fn test_get_early_access_features() -> Result<(), anyhow::Error> {
        let context = TestContext::new(None).await;
        let team = context.insert_new_team(None).await?;
        let project_id = team.project_id;
        let team_id = team.id;

        let _early_access_feature = context
            .insert_early_access_feature(team_id, None, None)
            .await;

        let cache =
            EarlyAccessFeatureCacheManager::new(context.non_persons_reader.clone(), None, None);
        let cached_early_access_features = cache.cache.get(&project_id).await;
        assert!(
            cached_early_access_features.is_none(),
            "Cache should initially be empty"
        );

        let early_access_features = cache.get_early_access_features(project_id).await?;
        assert_eq!(early_access_features.len(), 1);
        assert_eq!(early_access_features[0].team_id, Some(team_id));

        let cached_early_access_features = cache.cache.get(&project_id).await.unwrap();
        assert_eq!(cached_early_access_features.len(), 1);
        assert_eq!(cached_early_access_features[0].team_id, Some(team_id));

        Ok(())
    }
}
