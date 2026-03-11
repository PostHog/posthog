use axum::async_trait;
use moka::future::Cache;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use uuid::Uuid;

use crate::cohorts::cohort_models::CohortId;
use common_types::TeamId;

use super::provider::{CohortMembershipError, CohortMembershipProvider};

type MembershipCacheKey = (TeamId, Uuid);

/// Wraps a CohortMembershipProvider with a Moka cache layer.
///
/// Caches explicit membership results (cohort_id -> bool) keyed by (team_id, person_uuid).
/// If any requested cohort ID is missing from the cache, only the uncached IDs are
/// fetched from the inner provider and merged into the cache entry.
pub struct CachedCohortMembershipProvider<
    P: CohortMembershipProvider = super::realtime_provider::RealtimeCohortMembershipProvider,
> {
    inner: Arc<P>,
    cache: Cache<MembershipCacheKey, HashMap<CohortId, bool>>,
}

impl<P: CohortMembershipProvider> CachedCohortMembershipProvider<P> {
    const DEFAULT_TTL_SECONDS: u64 = 60;
    const DEFAULT_MAX_ENTRIES: u64 = 500_000;

    pub fn new(inner: P, ttl_seconds: Option<u64>, max_entries: Option<u64>) -> Self {
        let cache = Cache::builder()
            .time_to_live(Duration::from_secs(
                ttl_seconds.unwrap_or(Self::DEFAULT_TTL_SECONDS),
            ))
            .max_capacity(max_entries.unwrap_or(Self::DEFAULT_MAX_ENTRIES))
            .build();

        Self {
            inner: Arc::new(inner),
            cache,
        }
    }
}

#[async_trait]
impl<P: CohortMembershipProvider> CohortMembershipProvider for CachedCohortMembershipProvider<P> {
    async fn check_memberships(
        &self,
        team_id: TeamId,
        person_uuid: Uuid,
        cohort_ids: &[CohortId],
    ) -> Result<HashMap<CohortId, bool>, CohortMembershipError> {
        if cohort_ids.is_empty() {
            return Ok(HashMap::new());
        }

        let cache_key = (team_id, person_uuid);

        // Check for a partial cache hit: if some cohort IDs are already cached,
        // only fetch the missing ones from the inner provider.
        if let Some(cached) = self.cache.get(&cache_key).await {
            let uncached_ids: Vec<CohortId> = cohort_ids
                .iter()
                .filter(|id| !cached.contains_key(id))
                .copied()
                .collect();

            if uncached_ids.is_empty() {
                return Ok(cohort_ids
                    .iter()
                    .map(|id| (*id, cached.get(id).copied().unwrap_or(false)))
                    .collect());
            }

            let fresh = self
                .inner
                .check_memberships(team_id, person_uuid, &uncached_ids)
                .await?;

            let mut merged = cached;
            merged.extend(fresh);
            self.cache.insert(cache_key, merged.clone()).await;

            return Ok(cohort_ids
                .iter()
                .map(|id| (*id, merged.get(id).copied().unwrap_or(false)))
                .collect());
        }

        let result = self
            .inner
            .check_memberships(team_id, person_uuid, cohort_ids)
            .await?;

        self.cache.insert(cache_key, result.clone()).await;

        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU32, Ordering};

    struct MockProvider {
        call_count: AtomicU32,
        memberships: HashMap<CohortId, bool>,
    }

    impl MockProvider {
        fn new(memberships: HashMap<CohortId, bool>) -> Self {
            Self {
                call_count: AtomicU32::new(0),
                memberships,
            }
        }

        fn call_count(&self) -> u32 {
            self.call_count.load(Ordering::SeqCst)
        }
    }

    #[async_trait]
    impl CohortMembershipProvider for MockProvider {
        async fn check_memberships(
            &self,
            _team_id: TeamId,
            _person_uuid: Uuid,
            cohort_ids: &[CohortId],
        ) -> Result<HashMap<CohortId, bool>, CohortMembershipError> {
            self.call_count.fetch_add(1, Ordering::SeqCst);
            Ok(cohort_ids
                .iter()
                .map(|id| (*id, self.memberships.get(id).copied().unwrap_or(false)))
                .collect())
        }
    }

    #[tokio::test]
    async fn test_cache_miss_queries_inner() {
        let inner = MockProvider::new(HashMap::from([(1, true), (2, false), (3, true)]));
        let cached = CachedCohortMembershipProvider::new(inner, Some(60), Some(100));
        let person = Uuid::new_v4();

        let result = cached
            .check_memberships(1, person, &[1, 2, 3])
            .await
            .unwrap();

        assert!(result[&1]);
        assert!(!result[&2]);
        assert!(result[&3]);
        assert_eq!(cached.inner.call_count(), 1);
    }

    #[tokio::test]
    async fn test_cache_hit_skips_inner() {
        let inner = MockProvider::new(HashMap::from([(1, true), (2, false)]));
        let cached = CachedCohortMembershipProvider::new(inner, Some(60), Some(100));
        let person = Uuid::new_v4();

        cached.check_memberships(1, person, &[1, 2]).await.unwrap();
        assert_eq!(cached.inner.call_count(), 1);

        let result = cached.check_memberships(1, person, &[1, 2]).await.unwrap();
        assert!(result[&1]);
        assert!(!result[&2]);
        assert_eq!(cached.inner.call_count(), 1);
    }

    #[tokio::test]
    async fn test_different_persons_have_separate_cache_entries() {
        let inner = MockProvider::new(HashMap::from([(1, true)]));
        let cached = CachedCohortMembershipProvider::new(inner, Some(60), Some(100));

        let person_a = Uuid::new_v4();
        let person_b = Uuid::new_v4();

        cached.check_memberships(1, person_a, &[1]).await.unwrap();
        cached.check_memberships(1, person_b, &[1]).await.unwrap();

        assert_eq!(cached.inner.call_count(), 2);
    }

    #[tokio::test]
    async fn test_cache_hit_answers_subset_of_cohorts() {
        let inner = MockProvider::new(HashMap::from([(1, true), (2, true), (3, false)]));
        let cached = CachedCohortMembershipProvider::new(inner, Some(60), Some(100));
        let person = Uuid::new_v4();

        cached
            .check_memberships(1, person, &[1, 2, 3])
            .await
            .unwrap();

        let result = cached.check_memberships(1, person, &[1]).await.unwrap();
        assert!(result[&1]);
        assert_eq!(cached.inner.call_count(), 1);
    }

    #[tokio::test]
    async fn test_previously_unqueried_cohort_fetches_from_inner() {
        let inner = MockProvider::new(HashMap::from([(1, true), (2, false), (4, true)]));
        let cached = CachedCohortMembershipProvider::new(inner, Some(60), Some(100));
        let person = Uuid::new_v4();

        // Populate cache with cohorts 1 and 2
        cached.check_memberships(1, person, &[1, 2]).await.unwrap();
        assert_eq!(cached.inner.call_count(), 1);

        // Ask for cohort 4 which was never queried — must hit the inner provider
        let result = cached.check_memberships(1, person, &[1, 4]).await.unwrap();
        assert!(result[&1]);
        assert!(result[&4]);
        assert_eq!(cached.inner.call_count(), 2);

        // Now cohort 4 is cached too — no further inner call needed
        let result = cached
            .check_memberships(1, person, &[1, 2, 4])
            .await
            .unwrap();
        assert!(result[&1]);
        assert!(!result[&2]);
        assert!(result[&4]);
        assert_eq!(cached.inner.call_count(), 2);
    }

    #[tokio::test]
    async fn test_empty_cohort_ids_returns_empty() {
        let inner = MockProvider::new(HashMap::new());
        let cached = CachedCohortMembershipProvider::new(inner, Some(60), Some(100));

        let result = cached
            .check_memberships(1, Uuid::new_v4(), &[])
            .await
            .unwrap();

        assert!(result.is_empty());
        assert_eq!(cached.inner.call_count(), 0);
    }
}
