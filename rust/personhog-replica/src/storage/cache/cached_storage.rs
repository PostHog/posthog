use std::sync::Arc;

use async_trait::async_trait;
use uuid::Uuid;

use super::traits::PersonCache;
use crate::storage::{
    CohortMembership, CohortStorage, DistinctIdLookup, DistinctIdMapping, DistinctIdWithVersion,
    FeatureFlagStorage, Group, GroupIdentifier, GroupKey, GroupStorage, GroupTypeMapping, Person,
    PersonIdWithOverrideKeys, PersonIdWithOverrides, PersonLookup, StorageResult,
};

/// Storage wrapper that routes person lookups through a cache layer while
/// delegating all other operations directly to the underlying storage.
///
/// This enables caching for person data (the highest-volume lookups) while
/// keeping the implementation simple for other data types that don't benefit
/// as much from caching.
///
pub struct CachedStorage<S, C>
where
    S: DistinctIdLookup + GroupStorage + CohortStorage + FeatureFlagStorage,
    C: PersonCache,
{
    /// Underlying storage for non-person operations.
    /// Also used by the person cache on cache misses.
    inner: Arc<S>,

    /// Cache layer for person lookups.
    /// Can be NoopPersonCache (passthrough) or a real cache implementation.
    person_cache: Arc<C>,
}

impl<S, C> CachedStorage<S, C>
where
    S: DistinctIdLookup + GroupStorage + CohortStorage + FeatureFlagStorage,
    C: PersonCache,
{
    pub fn new(inner: Arc<S>, person_cache: Arc<C>) -> Self {
        Self {
            inner,
            person_cache,
        }
    }
}

// PersonLookup delegates to the person cache
#[async_trait]
impl<S, C> PersonLookup for CachedStorage<S, C>
where
    S: DistinctIdLookup + GroupStorage + CohortStorage + FeatureFlagStorage + Send + Sync + 'static,
    C: PersonCache + 'static,
{
    async fn get_person_by_id(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> StorageResult<Option<Person>> {
        self.person_cache.get_person_by_id(team_id, person_id).await
    }

    async fn get_person_by_uuid(&self, team_id: i64, uuid: Uuid) -> StorageResult<Option<Person>> {
        self.person_cache.get_person_by_uuid(team_id, uuid).await
    }

    async fn get_persons_by_ids(
        &self,
        team_id: i64,
        person_ids: &[i64],
    ) -> StorageResult<Vec<Person>> {
        self.person_cache
            .get_persons_by_ids(team_id, person_ids)
            .await
    }

    async fn get_persons_by_uuids(
        &self,
        team_id: i64,
        uuids: &[Uuid],
    ) -> StorageResult<Vec<Person>> {
        self.person_cache.get_persons_by_uuids(team_id, uuids).await
    }

    async fn get_person_by_distinct_id(
        &self,
        team_id: i64,
        distinct_id: &str,
    ) -> StorageResult<Option<Person>> {
        self.person_cache
            .get_person_by_distinct_id(team_id, distinct_id)
            .await
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<(String, Option<Person>)>> {
        self.person_cache
            .get_persons_by_distinct_ids_in_team(team_id, distinct_ids)
            .await
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
    ) -> StorageResult<Vec<((i64, String), Option<Person>)>> {
        self.person_cache
            .get_persons_by_distinct_ids_cross_team(team_distinct_ids)
            .await
    }
}

// DistinctIdLookup delegates to inner storage
#[async_trait]
impl<S, C> DistinctIdLookup for CachedStorage<S, C>
where
    S: DistinctIdLookup + GroupStorage + CohortStorage + FeatureFlagStorage + Send + Sync + 'static,
    C: PersonCache + 'static,
{
    async fn get_distinct_ids_for_person(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> StorageResult<Vec<DistinctIdWithVersion>> {
        self.inner
            .get_distinct_ids_for_person(team_id, person_id)
            .await
    }

    async fn get_distinct_ids_for_persons(
        &self,
        team_id: i64,
        person_ids: &[i64],
    ) -> StorageResult<Vec<DistinctIdMapping>> {
        self.inner
            .get_distinct_ids_for_persons(team_id, person_ids)
            .await
    }
}

// GroupStorage delegates to inner storage
#[async_trait]
impl<S, C> GroupStorage for CachedStorage<S, C>
where
    S: DistinctIdLookup + GroupStorage + CohortStorage + FeatureFlagStorage + Send + Sync + 'static,
    C: PersonCache + 'static,
{
    async fn get_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
    ) -> StorageResult<Option<Group>> {
        self.inner
            .get_group(team_id, group_type_index, group_key)
            .await
    }

    async fn get_groups(
        &self,
        team_id: i64,
        identifiers: &[GroupIdentifier],
    ) -> StorageResult<Vec<Group>> {
        self.inner.get_groups(team_id, identifiers).await
    }

    async fn get_groups_batch(&self, keys: &[GroupKey]) -> StorageResult<Vec<(GroupKey, Group)>> {
        self.inner.get_groups_batch(keys).await
    }

    async fn get_group_type_mappings_by_team_id(
        &self,
        team_id: i64,
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        self.inner.get_group_type_mappings_by_team_id(team_id).await
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        team_ids: &[i64],
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        self.inner
            .get_group_type_mappings_by_team_ids(team_ids)
            .await
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        project_id: i64,
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        self.inner
            .get_group_type_mappings_by_project_id(project_id)
            .await
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        project_ids: &[i64],
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        self.inner
            .get_group_type_mappings_by_project_ids(project_ids)
            .await
    }
}

// CohortStorage delegates to inner storage
#[async_trait]
impl<S, C> CohortStorage for CachedStorage<S, C>
where
    S: DistinctIdLookup + GroupStorage + CohortStorage + FeatureFlagStorage + Send + Sync + 'static,
    C: PersonCache + 'static,
{
    async fn check_cohort_membership(
        &self,
        person_id: i64,
        cohort_ids: &[i64],
    ) -> StorageResult<Vec<CohortMembership>> {
        self.inner
            .check_cohort_membership(person_id, cohort_ids)
            .await
    }
}

// FeatureFlagStorage delegates to inner storage
#[async_trait]
impl<S, C> FeatureFlagStorage for CachedStorage<S, C>
where
    S: DistinctIdLookup + GroupStorage + CohortStorage + FeatureFlagStorage + Send + Sync + 'static,
    C: PersonCache + 'static,
{
    async fn get_person_ids_and_hash_key_overrides(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<PersonIdWithOverrides>> {
        self.inner
            .get_person_ids_and_hash_key_overrides(team_id, distinct_ids)
            .await
    }

    async fn get_existing_person_ids_with_override_keys(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<PersonIdWithOverrideKeys>> {
        self.inner
            .get_existing_person_ids_with_override_keys(team_id, distinct_ids)
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    /// Mock storage that tracks which methods were called.
    /// Used to verify that CachedStorage routes calls correctly.
    struct MockInnerStorage {
        distinct_id_calls: AtomicUsize,
        group_calls: AtomicUsize,
        cohort_calls: AtomicUsize,
        feature_flag_calls: AtomicUsize,
    }

    impl MockInnerStorage {
        fn new() -> Self {
            Self {
                distinct_id_calls: AtomicUsize::new(0),
                group_calls: AtomicUsize::new(0),
                cohort_calls: AtomicUsize::new(0),
                feature_flag_calls: AtomicUsize::new(0),
            }
        }
    }

    #[async_trait]
    impl DistinctIdLookup for MockInnerStorage {
        async fn get_distinct_ids_for_person(
            &self,
            _team_id: i64,
            _person_id: i64,
        ) -> StorageResult<Vec<DistinctIdWithVersion>> {
            self.distinct_id_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }

        async fn get_distinct_ids_for_persons(
            &self,
            _team_id: i64,
            _person_ids: &[i64],
        ) -> StorageResult<Vec<DistinctIdMapping>> {
            self.distinct_id_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }
    }

    #[async_trait]
    impl GroupStorage for MockInnerStorage {
        async fn get_group(
            &self,
            _team_id: i64,
            _group_type_index: i32,
            _group_key: &str,
        ) -> StorageResult<Option<Group>> {
            self.group_calls.fetch_add(1, Ordering::SeqCst);
            Ok(None)
        }

        async fn get_groups(
            &self,
            _team_id: i64,
            _identifiers: &[GroupIdentifier],
        ) -> StorageResult<Vec<Group>> {
            self.group_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }

        async fn get_groups_batch(
            &self,
            _keys: &[GroupKey],
        ) -> StorageResult<Vec<(GroupKey, Group)>> {
            self.group_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }

        async fn get_group_type_mappings_by_team_id(
            &self,
            _team_id: i64,
        ) -> StorageResult<Vec<GroupTypeMapping>> {
            self.group_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }

        async fn get_group_type_mappings_by_team_ids(
            &self,
            _team_ids: &[i64],
        ) -> StorageResult<Vec<GroupTypeMapping>> {
            self.group_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }

        async fn get_group_type_mappings_by_project_id(
            &self,
            _project_id: i64,
        ) -> StorageResult<Vec<GroupTypeMapping>> {
            self.group_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }

        async fn get_group_type_mappings_by_project_ids(
            &self,
            _project_ids: &[i64],
        ) -> StorageResult<Vec<GroupTypeMapping>> {
            self.group_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }
    }

    #[async_trait]
    impl CohortStorage for MockInnerStorage {
        async fn check_cohort_membership(
            &self,
            _person_id: i64,
            _cohort_ids: &[i64],
        ) -> StorageResult<Vec<CohortMembership>> {
            self.cohort_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }
    }

    #[async_trait]
    impl FeatureFlagStorage for MockInnerStorage {
        async fn get_person_ids_and_hash_key_overrides(
            &self,
            _team_id: i64,
            _distinct_ids: &[String],
        ) -> StorageResult<Vec<PersonIdWithOverrides>> {
            self.feature_flag_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }

        async fn get_existing_person_ids_with_override_keys(
            &self,
            _team_id: i64,
            _distinct_ids: &[String],
        ) -> StorageResult<Vec<PersonIdWithOverrideKeys>> {
            self.feature_flag_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }
    }

    /// Mock person cache that tracks calls
    struct MockPersonCache {
        calls: AtomicUsize,
    }

    impl MockPersonCache {
        fn new() -> Self {
            Self {
                calls: AtomicUsize::new(0),
            }
        }
    }

    #[async_trait]
    impl PersonCache for MockPersonCache {
        async fn get_person_by_id(
            &self,
            _team_id: i64,
            _person_id: i64,
        ) -> StorageResult<Option<Person>> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(None)
        }

        async fn get_person_by_uuid(
            &self,
            _team_id: i64,
            _uuid: Uuid,
        ) -> StorageResult<Option<Person>> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(None)
        }

        async fn get_persons_by_ids(
            &self,
            _team_id: i64,
            _person_ids: &[i64],
        ) -> StorageResult<Vec<Person>> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }

        async fn get_persons_by_uuids(
            &self,
            _team_id: i64,
            _uuids: &[Uuid],
        ) -> StorageResult<Vec<Person>> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }

        async fn get_person_by_distinct_id(
            &self,
            _team_id: i64,
            _distinct_id: &str,
        ) -> StorageResult<Option<Person>> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(None)
        }

        async fn get_persons_by_distinct_ids_in_team(
            &self,
            _team_id: i64,
            _distinct_ids: &[String],
        ) -> StorageResult<Vec<(String, Option<Person>)>> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }

        async fn get_persons_by_distinct_ids_cross_team(
            &self,
            _team_distinct_ids: &[(i64, String)],
        ) -> StorageResult<Vec<((i64, String), Option<Person>)>> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![])
        }
    }

    #[tokio::test]
    async fn person_lookups_route_through_cache() {
        let inner = Arc::new(MockInnerStorage::new());
        let cache = Arc::new(MockPersonCache::new());
        let cached = CachedStorage::new(inner.clone(), cache.clone());

        // Call all person lookup methods
        cached.get_person_by_id(1, 1).await.unwrap();
        cached.get_person_by_uuid(1, Uuid::nil()).await.unwrap();
        cached.get_persons_by_ids(1, &[1, 2]).await.unwrap();
        cached
            .get_persons_by_uuids(1, &[Uuid::nil()])
            .await
            .unwrap();
        cached.get_person_by_distinct_id(1, "test").await.unwrap();
        cached
            .get_persons_by_distinct_ids_in_team(1, &["a".to_string()])
            .await
            .unwrap();
        cached
            .get_persons_by_distinct_ids_cross_team(&[(1, "a".to_string())])
            .await
            .unwrap();

        // All 7 calls should have gone through the cache
        assert_eq!(cache.calls.load(Ordering::SeqCst), 7);
    }

    #[tokio::test]
    async fn non_person_operations_route_to_inner_storage() {
        let inner = Arc::new(MockInnerStorage::new());
        let cache = Arc::new(MockPersonCache::new());
        let cached = CachedStorage::new(inner.clone(), cache.clone());

        // Call distinct ID methods
        cached.get_distinct_ids_for_person(1, 1).await.unwrap();
        cached.get_distinct_ids_for_persons(1, &[1]).await.unwrap();
        assert_eq!(inner.distinct_id_calls.load(Ordering::SeqCst), 2);

        // Call group methods
        cached.get_group(1, 0, "key").await.unwrap();
        cached.get_groups(1, &[]).await.unwrap();
        cached.get_groups_batch(&[]).await.unwrap();
        cached.get_group_type_mappings_by_team_id(1).await.unwrap();
        cached
            .get_group_type_mappings_by_team_ids(&[1])
            .await
            .unwrap();
        cached
            .get_group_type_mappings_by_project_id(1)
            .await
            .unwrap();
        cached
            .get_group_type_mappings_by_project_ids(&[1])
            .await
            .unwrap();
        assert_eq!(inner.group_calls.load(Ordering::SeqCst), 7);

        // Call cohort method
        cached.check_cohort_membership(1, &[1]).await.unwrap();
        assert_eq!(inner.cohort_calls.load(Ordering::SeqCst), 1);

        // Call feature flag methods
        cached
            .get_person_ids_and_hash_key_overrides(1, &["a".to_string()])
            .await
            .unwrap();
        cached
            .get_existing_person_ids_with_override_keys(1, &["a".to_string()])
            .await
            .unwrap();
        assert_eq!(inner.feature_flag_calls.load(Ordering::SeqCst), 2);

        // Person cache should not have been called
        assert_eq!(cache.calls.load(Ordering::SeqCst), 0);
    }
}
