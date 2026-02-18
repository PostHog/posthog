use std::sync::Mutex;

use async_trait::async_trait;
use uuid::Uuid;

use crate::storage;

/// Mock storage that returns configurable errors for unit testing error handling
pub struct FailingStorage {
    error: storage::StorageError,
}

impl FailingStorage {
    pub fn with_connection_error() -> Self {
        Self {
            error: storage::StorageError::Connection("connection refused".to_string()),
        }
    }

    pub fn with_pool_exhausted() -> Self {
        Self {
            error: storage::StorageError::PoolExhausted,
        }
    }

    pub fn with_query_error() -> Self {
        Self {
            error: storage::StorageError::Query("syntax error at position 42".to_string()),
        }
    }
}

#[async_trait]
impl storage::PersonLookup for FailingStorage {
    async fn get_person_by_id(
        &self,
        _team_id: i64,
        _person_id: i64,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Err(self.error.clone())
    }

    async fn get_person_by_uuid(
        &self,
        _team_id: i64,
        _uuid: Uuid,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Err(self.error.clone())
    }

    async fn get_persons_by_ids(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
    ) -> storage::StorageResult<Vec<storage::Person>> {
        Err(self.error.clone())
    }

    async fn get_persons_by_uuids(
        &self,
        _team_id: i64,
        _uuids: &[Uuid],
    ) -> storage::StorageResult<Vec<storage::Person>> {
        Err(self.error.clone())
    }

    async fn get_person_by_distinct_id(
        &self,
        _team_id: i64,
        _distinct_id: &str,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Err(self.error.clone())
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        _team_id: i64,
        _distinct_ids: &[String],
    ) -> storage::StorageResult<Vec<(String, Option<storage::Person>)>> {
        Err(self.error.clone())
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        _team_distinct_ids: &[(i64, String)],
    ) -> storage::StorageResult<Vec<((i64, String), Option<storage::Person>)>> {
        Err(self.error.clone())
    }
}

#[async_trait]
impl storage::DistinctIdLookup for FailingStorage {
    async fn get_distinct_ids_for_person(
        &self,
        _team_id: i64,
        _person_id: i64,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::DistinctIdWithVersion>> {
        Err(self.error.clone())
    }

    async fn get_distinct_ids_for_persons(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::DistinctIdMapping>> {
        Err(self.error.clone())
    }
}

#[async_trait]
impl storage::FeatureFlagStorage for FailingStorage {
    async fn get_hash_key_override_context(
        &self,
        _team_id: i64,
        _distinct_ids: &[String],
        _check_person_exists: bool,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::HashKeyOverrideContext>> {
        Err(self.error.clone())
    }

    async fn upsert_hash_key_overrides(
        &self,
        _team_id: i64,
        _overrides: &[storage::HashKeyOverrideInput],
        _hash_key: &str,
    ) -> storage::StorageResult<i64> {
        Err(self.error.clone())
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        _team_ids: &[i64],
    ) -> storage::StorageResult<i64> {
        Err(self.error.clone())
    }
}

#[async_trait]
impl storage::CohortStorage for FailingStorage {
    async fn check_cohort_membership(
        &self,
        _person_id: i64,
        _cohort_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::CohortMembership>> {
        Err(self.error.clone())
    }
}

#[async_trait]
impl storage::GroupStorage for FailingStorage {
    async fn get_group(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key: &str,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Option<storage::Group>> {
        Err(self.error.clone())
    }

    async fn get_groups(
        &self,
        _team_id: i64,
        _identifiers: &[storage::GroupIdentifier],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::Group>> {
        Err(self.error.clone())
    }

    async fn get_groups_batch(
        &self,
        _keys: &[storage::GroupKey],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<(storage::GroupKey, storage::Group)>> {
        Err(self.error.clone())
    }

    async fn get_group_type_mappings_by_team_id(
        &self,
        _team_id: i64,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        Err(self.error.clone())
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        _team_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        Err(self.error.clone())
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        _project_id: i64,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        Err(self.error.clone())
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        _project_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        Err(self.error.clone())
    }
}

/// Mock storage that returns successful empty results for testing consistency validation
pub struct SuccessStorage;

#[async_trait]
impl storage::PersonLookup for SuccessStorage {
    async fn get_person_by_id(
        &self,
        _team_id: i64,
        _person_id: i64,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(None)
    }

    async fn get_person_by_uuid(
        &self,
        _team_id: i64,
        _uuid: Uuid,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(None)
    }

    async fn get_persons_by_ids(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
    ) -> storage::StorageResult<Vec<storage::Person>> {
        Ok(Vec::new())
    }

    async fn get_persons_by_uuids(
        &self,
        _team_id: i64,
        _uuids: &[Uuid],
    ) -> storage::StorageResult<Vec<storage::Person>> {
        Ok(Vec::new())
    }

    async fn get_person_by_distinct_id(
        &self,
        _team_id: i64,
        _distinct_id: &str,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(None)
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        _team_id: i64,
        distinct_ids: &[String],
    ) -> storage::StorageResult<Vec<(String, Option<storage::Person>)>> {
        Ok(distinct_ids.iter().map(|d| (d.clone(), None)).collect())
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
    ) -> storage::StorageResult<Vec<((i64, String), Option<storage::Person>)>> {
        Ok(team_distinct_ids
            .iter()
            .map(|(t, d)| ((*t, d.clone()), None))
            .collect())
    }
}

#[async_trait]
impl storage::DistinctIdLookup for SuccessStorage {
    async fn get_distinct_ids_for_person(
        &self,
        _team_id: i64,
        _person_id: i64,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::DistinctIdWithVersion>> {
        Ok(Vec::new())
    }

    async fn get_distinct_ids_for_persons(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::DistinctIdMapping>> {
        Ok(Vec::new())
    }
}

#[async_trait]
impl storage::FeatureFlagStorage for SuccessStorage {
    async fn get_hash_key_override_context(
        &self,
        _team_id: i64,
        _distinct_ids: &[String],
        _check_person_exists: bool,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::HashKeyOverrideContext>> {
        Ok(Vec::new())
    }

    async fn upsert_hash_key_overrides(
        &self,
        _team_id: i64,
        _overrides: &[storage::HashKeyOverrideInput],
        _hash_key: &str,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        _team_ids: &[i64],
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }
}

#[async_trait]
impl storage::CohortStorage for SuccessStorage {
    async fn check_cohort_membership(
        &self,
        _person_id: i64,
        cohort_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::CohortMembership>> {
        Ok(cohort_ids
            .iter()
            .map(|&id| storage::CohortMembership {
                cohort_id: id,
                is_member: false,
            })
            .collect())
    }
}

#[async_trait]
impl storage::GroupStorage for SuccessStorage {
    async fn get_group(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key: &str,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Option<storage::Group>> {
        Ok(None)
    }

    async fn get_groups(
        &self,
        _team_id: i64,
        _identifiers: &[storage::GroupIdentifier],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::Group>> {
        Ok(Vec::new())
    }

    async fn get_groups_batch(
        &self,
        _keys: &[storage::GroupKey],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<(storage::GroupKey, storage::Group)>> {
        Ok(Vec::new())
    }

    async fn get_group_type_mappings_by_team_id(
        &self,
        _team_id: i64,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        Ok(Vec::new())
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        _team_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        Ok(Vec::new())
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        _project_id: i64,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        Ok(Vec::new())
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        _project_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        Ok(Vec::new())
    }
}

/// Mock storage that tracks which consistency level was passed to each method.
/// Used to verify that the service correctly routes requests based on read_options.
pub struct ConsistencyTrackingStorage {
    last_consistency: Mutex<Option<storage::postgres::ConsistencyLevel>>,
}

impl ConsistencyTrackingStorage {
    pub fn new() -> Self {
        Self {
            last_consistency: Mutex::new(None),
        }
    }

    fn record(&self, consistency: storage::postgres::ConsistencyLevel) {
        *self.last_consistency.lock().unwrap() = Some(consistency);
    }

    pub fn last_consistency(&self) -> Option<storage::postgres::ConsistencyLevel> {
        *self.last_consistency.lock().unwrap()
    }
}

#[async_trait]
impl storage::PersonLookup for ConsistencyTrackingStorage {
    async fn get_person_by_id(
        &self,
        _team_id: i64,
        _person_id: i64,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(None)
    }

    async fn get_person_by_uuid(
        &self,
        _team_id: i64,
        _uuid: Uuid,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(None)
    }

    async fn get_persons_by_ids(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
    ) -> storage::StorageResult<Vec<storage::Person>> {
        Ok(Vec::new())
    }

    async fn get_persons_by_uuids(
        &self,
        _team_id: i64,
        _uuids: &[Uuid],
    ) -> storage::StorageResult<Vec<storage::Person>> {
        Ok(Vec::new())
    }

    async fn get_person_by_distinct_id(
        &self,
        _team_id: i64,
        _distinct_id: &str,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(None)
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        _team_id: i64,
        distinct_ids: &[String],
    ) -> storage::StorageResult<Vec<(String, Option<storage::Person>)>> {
        Ok(distinct_ids.iter().map(|d| (d.clone(), None)).collect())
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
    ) -> storage::StorageResult<Vec<((i64, String), Option<storage::Person>)>> {
        Ok(team_distinct_ids
            .iter()
            .map(|(t, d)| ((*t, d.clone()), None))
            .collect())
    }
}

#[async_trait]
impl storage::DistinctIdLookup for ConsistencyTrackingStorage {
    async fn get_distinct_ids_for_person(
        &self,
        _team_id: i64,
        _person_id: i64,
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::DistinctIdWithVersion>> {
        self.record(consistency);
        Ok(Vec::new())
    }

    async fn get_distinct_ids_for_persons(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::DistinctIdMapping>> {
        self.record(consistency);
        Ok(Vec::new())
    }
}

#[async_trait]
impl storage::FeatureFlagStorage for ConsistencyTrackingStorage {
    async fn get_hash_key_override_context(
        &self,
        _team_id: i64,
        _distinct_ids: &[String],
        _check_person_exists: bool,
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::HashKeyOverrideContext>> {
        self.record(consistency);
        Ok(Vec::new())
    }

    async fn upsert_hash_key_overrides(
        &self,
        _team_id: i64,
        _overrides: &[storage::HashKeyOverrideInput],
        _hash_key: &str,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        _team_ids: &[i64],
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }
}

#[async_trait]
impl storage::CohortStorage for ConsistencyTrackingStorage {
    async fn check_cohort_membership(
        &self,
        _person_id: i64,
        cohort_ids: &[i64],
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::CohortMembership>> {
        self.record(consistency);
        Ok(cohort_ids
            .iter()
            .map(|&id| storage::CohortMembership {
                cohort_id: id,
                is_member: false,
            })
            .collect())
    }
}

#[async_trait]
impl storage::GroupStorage for ConsistencyTrackingStorage {
    async fn get_group(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key: &str,
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Option<storage::Group>> {
        self.record(consistency);
        Ok(None)
    }

    async fn get_groups(
        &self,
        _team_id: i64,
        _identifiers: &[storage::GroupIdentifier],
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::Group>> {
        self.record(consistency);
        Ok(Vec::new())
    }

    async fn get_groups_batch(
        &self,
        _keys: &[storage::GroupKey],
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<(storage::GroupKey, storage::Group)>> {
        self.record(consistency);
        Ok(Vec::new())
    }

    async fn get_group_type_mappings_by_team_id(
        &self,
        _team_id: i64,
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        self.record(consistency);
        Ok(Vec::new())
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        _team_ids: &[i64],
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        self.record(consistency);
        Ok(Vec::new())
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        _project_id: i64,
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        self.record(consistency);
        Ok(Vec::new())
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        _project_ids: &[i64],
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<storage::GroupTypeMapping>> {
        self.record(consistency);
        Ok(Vec::new())
    }
}
