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
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<storage::Person>> {
        Err(self.error.clone())
    }

    async fn get_persons_by_uuids(
        &self,
        _team_id: i64,
        _uuids: &[Uuid],
        _include_properties: bool,
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
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<(String, Option<storage::Person>)>> {
        Err(self.error.clone())
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        _team_distinct_ids: &[(i64, String)],
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<((i64, String), Option<storage::Person>)>> {
        Err(self.error.clone())
    }

    async fn delete_persons(&self, _team_id: i64, _uuids: &[Uuid]) -> storage::StorageResult<i64> {
        Err(self.error.clone())
    }

    async fn delete_persons_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Err(self.error.clone())
    }

    async fn delete_personless_distinct_ids_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Err(self.error.clone())
    }

    async fn split_person(
        &self,
        _team_id: i64,
        _person_id: i64,
        _distinct_ids_to_split: &[String],
    ) -> storage::StorageResult<Vec<storage::SplitResult>> {
        Err(self.error.clone())
    }

    async fn set_person_distinct_id_version_floor(
        &self,
        _team_id: i64,
        _distinct_id: &str,
        _version: i64,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Err(self.error.clone())
    }

    async fn set_person_version_floor(
        &self,
        _team_id: i64,
        _person_id: i64,
        _min_version: i64,
    ) -> storage::StorageResult<bool> {
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
        _limit: Option<i64>,
    ) -> storage::StorageResult<Vec<storage::DistinctIdWithVersion>> {
        Err(self.error.clone())
    }

    async fn get_distinct_ids_for_persons(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
        _limit_per_person: Option<i64>,
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
        _distinct_ids: &[String],
        _feature_flag_keys: &[String],
        _hash_key: &str,
    ) -> storage::StorageResult<i64> {
        Err(self.error.clone())
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        _team_ids: &[i64],
        _batch_size: i64,
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

    async fn count_cohort_members(
        &self,
        _cohort_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<i64> {
        Err(self.error.clone())
    }

    async fn delete_cohort_member(
        &self,
        _cohort_id: i64,
        _person_id: i64,
    ) -> storage::StorageResult<bool> {
        Err(self.error.clone())
    }

    async fn delete_cohort_members_bulk(
        &self,
        _cohort_ids: &[i64],
        _batch_size: i32,
    ) -> storage::StorageResult<i64> {
        Err(self.error.clone())
    }

    async fn insert_cohort_members(
        &self,
        _cohort_id: i64,
        _person_ids: &[i64],
        _version: Option<i32>,
    ) -> storage::StorageResult<i64> {
        Err(self.error.clone())
    }

    async fn list_cohort_member_ids(
        &self,
        _cohort_id: i64,
        _cursor: i64,
        _limit: i32,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<(Vec<i64>, Option<i64>)> {
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
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<storage::Group>> {
        Err(self.error.clone())
    }

    async fn get_groups_batch(
        &self,
        _keys: &[storage::GroupKey],
        _consistency: storage::postgres::ConsistencyLevel,
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<(storage::GroupKey, storage::Group)>> {
        Err(self.error.clone())
    }

    async fn list_groups(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key_contains: &str,
        _search: &str,
        _cursor_created_at: Option<chrono::DateTime<chrono::Utc>>,
        _cursor_id: i64,
        _limit: i32,
        _consistency: storage::postgres::ConsistencyLevel,
        _include_properties: bool,
    ) -> storage::StorageResult<(Vec<storage::Group>, bool)> {
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

    async fn count_group_type_mappings(
        &self,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<(i64, i64)>> {
        Err(self.error.clone())
    }

    async fn create_group(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key: &str,
        _group_properties: &serde_json::Value,
        _created_at: chrono::DateTime<chrono::Utc>,
    ) -> storage::StorageResult<storage::Group> {
        Err(self.error.clone())
    }

    async fn update_group(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key: &str,
        _update_mask: &[String],
        _group_properties: Option<&serde_json::Value>,
        _properties_last_updated_at: Option<&serde_json::Value>,
        _properties_last_operation: Option<&serde_json::Value>,
        _created_at: Option<chrono::DateTime<chrono::Utc>>,
    ) -> storage::StorageResult<Option<storage::Group>> {
        Err(self.error.clone())
    }

    async fn delete_groups_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Err(self.error.clone())
    }

    async fn get_group_type_mapping_by_dashboard_id(
        &self,
        _team_id: i64,
        _dashboard_id: i64,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Option<storage::GroupTypeMapping>> {
        Err(self.error.clone())
    }

    async fn update_group_type_mapping(
        &self,
        _project_id: i64,
        _group_type_index: i32,
        _update_mask: &[String],
        _name_singular: Option<&str>,
        _name_plural: Option<&str>,
        _detail_dashboard_id: Option<i64>,
        _default_columns: Option<&[String]>,
    ) -> storage::StorageResult<Option<storage::GroupTypeMapping>> {
        Err(self.error.clone())
    }

    async fn delete_group_type_mapping(
        &self,
        _project_id: i64,
        _group_type_index: i32,
    ) -> storage::StorageResult<bool> {
        Err(self.error.clone())
    }

    async fn delete_group_type_mappings_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
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
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<storage::Person>> {
        Ok(Vec::new())
    }

    async fn get_persons_by_uuids(
        &self,
        _team_id: i64,
        _uuids: &[Uuid],
        _include_properties: bool,
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
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<(String, Option<storage::Person>)>> {
        Ok(distinct_ids.iter().map(|d| (d.clone(), None)).collect())
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<((i64, String), Option<storage::Person>)>> {
        Ok(team_distinct_ids
            .iter()
            .map(|(t, d)| ((*t, d.clone()), None))
            .collect())
    }

    async fn delete_persons(&self, _team_id: i64, _uuids: &[Uuid]) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_persons_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_personless_distinct_ids_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn split_person(
        &self,
        _team_id: i64,
        _person_id: i64,
        _distinct_ids_to_split: &[String],
    ) -> storage::StorageResult<Vec<storage::SplitResult>> {
        Ok(vec![])
    }

    async fn set_person_distinct_id_version_floor(
        &self,
        _team_id: i64,
        _distinct_id: &str,
        _version: i64,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(None)
    }

    async fn set_person_version_floor(
        &self,
        _team_id: i64,
        _person_id: i64,
        _min_version: i64,
    ) -> storage::StorageResult<bool> {
        Ok(false)
    }
}

#[async_trait]
impl storage::DistinctIdLookup for SuccessStorage {
    async fn get_distinct_ids_for_person(
        &self,
        _team_id: i64,
        _person_id: i64,
        _consistency: storage::postgres::ConsistencyLevel,
        _limit: Option<i64>,
    ) -> storage::StorageResult<Vec<storage::DistinctIdWithVersion>> {
        Ok(Vec::new())
    }

    async fn get_distinct_ids_for_persons(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
        _limit_per_person: Option<i64>,
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
        _distinct_ids: &[String],
        _feature_flag_keys: &[String],
        _hash_key: &str,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        _team_ids: &[i64],
        _batch_size: i64,
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

    async fn count_cohort_members(
        &self,
        _cohort_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_cohort_member(
        &self,
        _cohort_id: i64,
        _person_id: i64,
    ) -> storage::StorageResult<bool> {
        Ok(false)
    }

    async fn delete_cohort_members_bulk(
        &self,
        _cohort_ids: &[i64],
        _batch_size: i32,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn insert_cohort_members(
        &self,
        _cohort_id: i64,
        person_ids: &[i64],
        _version: Option<i32>,
    ) -> storage::StorageResult<i64> {
        Ok(person_ids.len() as i64)
    }

    async fn list_cohort_member_ids(
        &self,
        _cohort_id: i64,
        _cursor: i64,
        _limit: i32,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<(Vec<i64>, Option<i64>)> {
        Ok((Vec::new(), None))
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
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<storage::Group>> {
        Ok(Vec::new())
    }

    async fn get_groups_batch(
        &self,
        _keys: &[storage::GroupKey],
        _consistency: storage::postgres::ConsistencyLevel,
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<(storage::GroupKey, storage::Group)>> {
        Ok(Vec::new())
    }

    async fn list_groups(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key_contains: &str,
        _search: &str,
        _cursor_created_at: Option<chrono::DateTime<chrono::Utc>>,
        _cursor_id: i64,
        _limit: i32,
        _consistency: storage::postgres::ConsistencyLevel,
        _include_properties: bool,
    ) -> storage::StorageResult<(Vec<storage::Group>, bool)> {
        Ok((Vec::new(), false))
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

    async fn count_group_type_mappings(
        &self,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<(i64, i64)>> {
        Ok(Vec::new())
    }

    async fn create_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
        group_properties: &serde_json::Value,
        created_at: chrono::DateTime<chrono::Utc>,
    ) -> storage::StorageResult<storage::Group> {
        Ok(storage::Group {
            id: 1,
            team_id,
            group_type_index,
            group_key: group_key.to_string(),
            group_properties: Some(group_properties.to_string()),
            created_at,
            properties_last_updated_at: None,
            properties_last_operation: None,
            version: 0,
        })
    }

    async fn update_group(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key: &str,
        _update_mask: &[String],
        _group_properties: Option<&serde_json::Value>,
        _properties_last_updated_at: Option<&serde_json::Value>,
        _properties_last_operation: Option<&serde_json::Value>,
        _created_at: Option<chrono::DateTime<chrono::Utc>>,
    ) -> storage::StorageResult<Option<storage::Group>> {
        Ok(None)
    }

    async fn delete_groups_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn get_group_type_mapping_by_dashboard_id(
        &self,
        _team_id: i64,
        _dashboard_id: i64,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Option<storage::GroupTypeMapping>> {
        Ok(None)
    }

    async fn update_group_type_mapping(
        &self,
        _project_id: i64,
        _group_type_index: i32,
        _update_mask: &[String],
        _name_singular: Option<&str>,
        _name_plural: Option<&str>,
        _detail_dashboard_id: Option<i64>,
        _default_columns: Option<&[String]>,
    ) -> storage::StorageResult<Option<storage::GroupTypeMapping>> {
        Ok(None)
    }

    async fn delete_group_type_mapping(
        &self,
        _project_id: i64,
        _group_type_index: i32,
    ) -> storage::StorageResult<bool> {
        Ok(false)
    }

    async fn delete_group_type_mappings_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }
}

/// Mock storage that returns pre-populated person and group data for field mask testing.
pub struct PopulatedStorage;

impl PopulatedStorage {
    pub fn person() -> storage::Person {
        storage::Person {
            id: 42,
            uuid: uuid::Uuid::parse_str("00000000-0000-0000-0000-000000000042").unwrap(),
            team_id: 1,
            properties: Some(r#"{"key":"value"}"#.to_string()),
            properties_last_updated_at: Some(r#"{"key":"2024-01-01"}"#.to_string()),
            properties_last_operation: Some(r#"{"key":"set"}"#.to_string()),
            created_at: chrono::DateTime::parse_from_rfc3339("2024-06-15T12:00:00Z")
                .unwrap()
                .with_timezone(&chrono::Utc),
            version: Some(5),
            is_identified: true,
            is_user_id: Some(true),
            last_seen_at: Some(
                chrono::DateTime::parse_from_rfc3339("2024-06-15T12:00:00Z")
                    .unwrap()
                    .with_timezone(&chrono::Utc),
            ),
        }
    }

    pub fn group() -> storage::Group {
        storage::Group {
            id: 100,
            team_id: 1,
            group_type_index: 0,
            group_key: "org-1".to_string(),
            group_properties: Some(r#"{"name":"Acme"}"#.to_string()),
            created_at: chrono::DateTime::parse_from_rfc3339("2024-06-15T12:00:00Z")
                .unwrap()
                .with_timezone(&chrono::Utc),
            properties_last_updated_at: Some(r#"{"name":"2024-01-01"}"#.to_string()),
            properties_last_operation: Some(r#"{"name":"set"}"#.to_string()),
            version: 3,
        }
    }
}

#[async_trait]
impl storage::PersonLookup for PopulatedStorage {
    async fn get_person_by_id(
        &self,
        _team_id: i64,
        _person_id: i64,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(Some(Self::person()))
    }

    async fn get_person_by_uuid(
        &self,
        _team_id: i64,
        _uuid: Uuid,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(Some(Self::person()))
    }

    async fn get_persons_by_ids(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<storage::Person>> {
        Ok(vec![Self::person()])
    }

    async fn get_persons_by_uuids(
        &self,
        _team_id: i64,
        _uuids: &[Uuid],
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<storage::Person>> {
        Ok(vec![Self::person()])
    }

    async fn get_person_by_distinct_id(
        &self,
        _team_id: i64,
        _distinct_id: &str,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(Some(Self::person()))
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        _team_id: i64,
        distinct_ids: &[String],
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<(String, Option<storage::Person>)>> {
        Ok(distinct_ids
            .iter()
            .map(|d| (d.clone(), Some(Self::person())))
            .collect())
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<((i64, String), Option<storage::Person>)>> {
        Ok(team_distinct_ids
            .iter()
            .map(|(t, d)| ((*t, d.clone()), Some(Self::person())))
            .collect())
    }

    async fn delete_persons(&self, _team_id: i64, _uuids: &[Uuid]) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_persons_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_personless_distinct_ids_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn split_person(
        &self,
        _team_id: i64,
        _person_id: i64,
        _distinct_ids_to_split: &[String],
    ) -> storage::StorageResult<Vec<storage::SplitResult>> {
        Ok(vec![])
    }

    async fn set_person_distinct_id_version_floor(
        &self,
        _team_id: i64,
        _distinct_id: &str,
        _version: i64,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(None)
    }

    async fn set_person_version_floor(
        &self,
        _team_id: i64,
        _person_id: i64,
        _min_version: i64,
    ) -> storage::StorageResult<bool> {
        Ok(false)
    }
}

#[async_trait]
impl storage::DistinctIdLookup for PopulatedStorage {
    async fn get_distinct_ids_for_person(
        &self,
        _team_id: i64,
        _person_id: i64,
        _consistency: storage::postgres::ConsistencyLevel,
        _limit: Option<i64>,
    ) -> storage::StorageResult<Vec<storage::DistinctIdWithVersion>> {
        Ok(Vec::new())
    }

    async fn get_distinct_ids_for_persons(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
        _limit_per_person: Option<i64>,
    ) -> storage::StorageResult<Vec<storage::DistinctIdMapping>> {
        Ok(Vec::new())
    }
}

#[async_trait]
impl storage::FeatureFlagStorage for PopulatedStorage {
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
        _distinct_ids: &[String],
        _feature_flag_keys: &[String],
        _hash_key: &str,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        _team_ids: &[i64],
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }
}

#[async_trait]
impl storage::CohortStorage for PopulatedStorage {
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

    async fn count_cohort_members(
        &self,
        _cohort_ids: &[i64],
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_cohort_member(
        &self,
        _cohort_id: i64,
        _person_id: i64,
    ) -> storage::StorageResult<bool> {
        Ok(false)
    }

    async fn delete_cohort_members_bulk(
        &self,
        _cohort_ids: &[i64],
        _batch_size: i32,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn insert_cohort_members(
        &self,
        _cohort_id: i64,
        person_ids: &[i64],
        _version: Option<i32>,
    ) -> storage::StorageResult<i64> {
        Ok(person_ids.len() as i64)
    }

    async fn list_cohort_member_ids(
        &self,
        _cohort_id: i64,
        _cursor: i64,
        _limit: i32,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<(Vec<i64>, Option<i64>)> {
        Ok((Vec::new(), None))
    }
}

#[async_trait]
impl storage::GroupStorage for PopulatedStorage {
    async fn get_group(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key: &str,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Option<storage::Group>> {
        Ok(Some(Self::group()))
    }

    async fn get_groups(
        &self,
        _team_id: i64,
        _identifiers: &[storage::GroupIdentifier],
        _consistency: storage::postgres::ConsistencyLevel,
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<storage::Group>> {
        Ok(vec![Self::group()])
    }

    async fn get_groups_batch(
        &self,
        keys: &[storage::GroupKey],
        _consistency: storage::postgres::ConsistencyLevel,
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<(storage::GroupKey, storage::Group)>> {
        Ok(keys.iter().map(|k| (k.clone(), Self::group())).collect())
    }

    async fn list_groups(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key_contains: &str,
        _search: &str,
        _cursor_created_at: Option<chrono::DateTime<chrono::Utc>>,
        _cursor_id: i64,
        _limit: i32,
        _consistency: storage::postgres::ConsistencyLevel,
        _include_properties: bool,
    ) -> storage::StorageResult<(Vec<storage::Group>, bool)> {
        Ok((vec![Self::group()], false))
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

    async fn count_group_type_mappings(
        &self,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<(i64, i64)>> {
        Ok(Vec::new())
    }

    async fn create_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
        group_properties: &serde_json::Value,
        created_at: chrono::DateTime<chrono::Utc>,
    ) -> storage::StorageResult<storage::Group> {
        Ok(storage::Group {
            id: 1,
            team_id,
            group_type_index,
            group_key: group_key.to_string(),
            group_properties: Some(group_properties.to_string()),
            created_at,
            properties_last_updated_at: None,
            properties_last_operation: None,
            version: 0,
        })
    }

    async fn update_group(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key: &str,
        _update_mask: &[String],
        _group_properties: Option<&serde_json::Value>,
        _properties_last_updated_at: Option<&serde_json::Value>,
        _properties_last_operation: Option<&serde_json::Value>,
        _created_at: Option<chrono::DateTime<chrono::Utc>>,
    ) -> storage::StorageResult<Option<storage::Group>> {
        Ok(None)
    }

    async fn delete_groups_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn get_group_type_mapping_by_dashboard_id(
        &self,
        _team_id: i64,
        _dashboard_id: i64,
        _consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Option<storage::GroupTypeMapping>> {
        Ok(None)
    }

    async fn update_group_type_mapping(
        &self,
        _project_id: i64,
        _group_type_index: i32,
        _update_mask: &[String],
        _name_singular: Option<&str>,
        _name_plural: Option<&str>,
        _detail_dashboard_id: Option<i64>,
        _default_columns: Option<&[String]>,
    ) -> storage::StorageResult<Option<storage::GroupTypeMapping>> {
        Ok(None)
    }

    async fn delete_group_type_mapping(
        &self,
        _project_id: i64,
        _group_type_index: i32,
    ) -> storage::StorageResult<bool> {
        Ok(false)
    }

    async fn delete_group_type_mappings_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
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
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<storage::Person>> {
        Ok(Vec::new())
    }

    async fn get_persons_by_uuids(
        &self,
        _team_id: i64,
        _uuids: &[Uuid],
        _include_properties: bool,
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
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<(String, Option<storage::Person>)>> {
        Ok(distinct_ids.iter().map(|d| (d.clone(), None)).collect())
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<((i64, String), Option<storage::Person>)>> {
        Ok(team_distinct_ids
            .iter()
            .map(|(t, d)| ((*t, d.clone()), None))
            .collect())
    }

    async fn delete_persons(&self, _team_id: i64, _uuids: &[Uuid]) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_persons_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_personless_distinct_ids_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn split_person(
        &self,
        _team_id: i64,
        _person_id: i64,
        _distinct_ids_to_split: &[String],
    ) -> storage::StorageResult<Vec<storage::SplitResult>> {
        Ok(vec![])
    }

    async fn set_person_distinct_id_version_floor(
        &self,
        _team_id: i64,
        _distinct_id: &str,
        _version: i64,
    ) -> storage::StorageResult<Option<storage::Person>> {
        Ok(None)
    }

    async fn set_person_version_floor(
        &self,
        _team_id: i64,
        _person_id: i64,
        _min_version: i64,
    ) -> storage::StorageResult<bool> {
        Ok(false)
    }
}

#[async_trait]
impl storage::DistinctIdLookup for ConsistencyTrackingStorage {
    async fn get_distinct_ids_for_person(
        &self,
        _team_id: i64,
        _person_id: i64,
        consistency: storage::postgres::ConsistencyLevel,
        _limit: Option<i64>,
    ) -> storage::StorageResult<Vec<storage::DistinctIdWithVersion>> {
        self.record(consistency);
        Ok(Vec::new())
    }

    async fn get_distinct_ids_for_persons(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
        consistency: storage::postgres::ConsistencyLevel,
        _limit_per_person: Option<i64>,
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
        _distinct_ids: &[String],
        _feature_flag_keys: &[String],
        _hash_key: &str,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        _team_ids: &[i64],
        _batch_size: i64,
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

    async fn count_cohort_members(
        &self,
        _cohort_ids: &[i64],
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<i64> {
        self.record(consistency);
        Ok(0)
    }

    async fn delete_cohort_member(
        &self,
        _cohort_id: i64,
        _person_id: i64,
    ) -> storage::StorageResult<bool> {
        Ok(false)
    }

    async fn delete_cohort_members_bulk(
        &self,
        _cohort_ids: &[i64],
        _batch_size: i32,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn insert_cohort_members(
        &self,
        _cohort_id: i64,
        person_ids: &[i64],
        _version: Option<i32>,
    ) -> storage::StorageResult<i64> {
        Ok(person_ids.len() as i64)
    }

    async fn list_cohort_member_ids(
        &self,
        _cohort_id: i64,
        _cursor: i64,
        _limit: i32,
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<(Vec<i64>, Option<i64>)> {
        self.record(consistency);
        Ok((Vec::new(), None))
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
        _include_properties: bool,
    ) -> storage::StorageResult<Vec<storage::Group>> {
        self.record(consistency);
        Ok(Vec::new())
    }

    async fn get_groups_batch(
        &self,
        _keys: &[storage::GroupKey],
        consistency: storage::postgres::ConsistencyLevel,
        _include_properties: bool,
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

    async fn count_group_type_mappings(
        &self,
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Vec<(i64, i64)>> {
        self.record(consistency);
        Ok(Vec::new())
    }

    async fn list_groups(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key_contains: &str,
        _search: &str,
        _cursor_created_at: Option<chrono::DateTime<chrono::Utc>>,
        _cursor_id: i64,
        _limit: i32,
        consistency: storage::postgres::ConsistencyLevel,
        _include_properties: bool,
    ) -> storage::StorageResult<(Vec<storage::Group>, bool)> {
        self.record(consistency);
        Ok((Vec::new(), false))
    }

    async fn create_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
        group_properties: &serde_json::Value,
        created_at: chrono::DateTime<chrono::Utc>,
    ) -> storage::StorageResult<storage::Group> {
        Ok(storage::Group {
            id: 1,
            team_id,
            group_type_index,
            group_key: group_key.to_string(),
            group_properties: Some(group_properties.to_string()),
            created_at,
            properties_last_updated_at: None,
            properties_last_operation: None,
            version: 0,
        })
    }

    async fn update_group(
        &self,
        _team_id: i64,
        _group_type_index: i32,
        _group_key: &str,
        _update_mask: &[String],
        _group_properties: Option<&serde_json::Value>,
        _properties_last_updated_at: Option<&serde_json::Value>,
        _properties_last_operation: Option<&serde_json::Value>,
        _created_at: Option<chrono::DateTime<chrono::Utc>>,
    ) -> storage::StorageResult<Option<storage::Group>> {
        Ok(None)
    }

    async fn delete_groups_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }

    async fn get_group_type_mapping_by_dashboard_id(
        &self,
        _team_id: i64,
        _dashboard_id: i64,
        consistency: storage::postgres::ConsistencyLevel,
    ) -> storage::StorageResult<Option<storage::GroupTypeMapping>> {
        self.record(consistency);
        Ok(None)
    }

    async fn update_group_type_mapping(
        &self,
        _project_id: i64,
        _group_type_index: i32,
        _update_mask: &[String],
        _name_singular: Option<&str>,
        _name_plural: Option<&str>,
        _detail_dashboard_id: Option<i64>,
        _default_columns: Option<&[String]>,
    ) -> storage::StorageResult<Option<storage::GroupTypeMapping>> {
        Ok(None)
    }

    async fn delete_group_type_mapping(
        &self,
        _project_id: i64,
        _group_type_index: i32,
    ) -> storage::StorageResult<bool> {
        Ok(false)
    }

    async fn delete_group_type_mappings_batch_for_team(
        &self,
        _team_id: i64,
        _batch_size: i64,
    ) -> storage::StorageResult<i64> {
        Ok(0)
    }
}
