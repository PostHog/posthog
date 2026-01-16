pub mod postgres;

use async_trait::async_trait;
use thiserror::Error;
use uuid::Uuid;

#[derive(Error, Debug)]
pub enum StorageError {
    /// Connection-level errors (network, TLS, authentication)
    #[error("Database connection error: {0}")]
    Connection(String),

    /// Query execution errors (SQL errors, constraint violations)
    #[error("Database query error: {0}")]
    Query(String),

    /// Connection pool exhausted or closed
    #[error("Database pool exhausted")]
    PoolExhausted,
}

// ============================================================
// Domain types that are storage-agnostic
// ============================================================

#[derive(Debug, Clone)]
pub struct Person {
    pub id: i64,
    pub uuid: Uuid,
    pub team_id: i64,
    pub properties: serde_json::Value,
    pub properties_last_updated_at: Option<serde_json::Value>,
    pub properties_last_operation: Option<serde_json::Value>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub version: Option<i64>,
    pub is_identified: bool,
    pub is_user_id: Option<bool>,
}

#[derive(Debug, Clone)]
pub struct Group {
    pub id: i64,
    pub team_id: i64,
    pub group_type_index: i32,
    pub group_key: String,
    pub group_properties: serde_json::Value,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub properties_last_updated_at: Option<serde_json::Value>,
    pub properties_last_operation: Option<serde_json::Value>,
    pub version: i64,
}

#[derive(Debug, Clone)]
pub struct GroupTypeMapping {
    pub id: i64,
    pub team_id: i64,
    pub project_id: i64,
    pub group_type: String,
    pub group_type_index: i32,
    pub name_singular: Option<String>,
    pub name_plural: Option<String>,
    pub default_columns: Option<serde_json::Value>,
    pub detail_dashboard_id: Option<i64>,
    pub created_at: Option<chrono::DateTime<chrono::Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct GroupIdentifier {
    pub group_type_index: i32,
    pub group_key: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct GroupKey {
    pub team_id: i64,
    pub group_type_index: i32,
    pub group_key: String,
}

#[derive(Debug, Clone)]
pub struct DistinctIdMapping {
    pub person_id: i64,
    pub distinct_id: String,
}

#[derive(Debug, Clone)]
pub struct DistinctIdWithVersion {
    pub distinct_id: String,
    pub version: Option<i64>,
}

#[derive(Debug, Clone)]
pub struct HashKeyOverride {
    pub feature_flag_key: String,
    pub hash_key: String,
}

#[derive(Debug, Clone)]
pub struct PersonIdWithOverrides {
    pub person_id: i64,
    pub distinct_id: String,
    pub overrides: Vec<HashKeyOverride>,
}

#[derive(Debug, Clone)]
pub struct PersonIdWithOverrideKeys {
    pub person_id: i64,
    pub existing_feature_flag_keys: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct CohortMembership {
    pub cohort_id: i64,
    pub is_member: bool,
}

pub type StorageResult<T> = Result<T, StorageError>;

/// Storage abstraction for person data
///
/// Implementations can use different backends (Postgres, DynamoDB, etc.)
/// while the service layer remains unchanged.
#[async_trait]
pub trait PersonStorage: Send + Sync {
    // ============================================================
    // Person lookups by ID/UUID (within a single team)
    // ============================================================
    async fn get_person_by_id(&self, team_id: i64, person_id: i64)
        -> StorageResult<Option<Person>>;

    async fn get_person_by_uuid(&self, team_id: i64, uuid: Uuid) -> StorageResult<Option<Person>>;

    async fn get_persons_by_ids(
        &self,
        team_id: i64,
        person_ids: &[i64],
    ) -> StorageResult<Vec<Person>>;

    async fn get_persons_by_uuids(
        &self,
        team_id: i64,
        uuids: &[Uuid],
    ) -> StorageResult<Vec<Person>>;

    // ============================================================
    // Person lookups by Distinct ID
    // ============================================================
    async fn get_person_by_distinct_id(
        &self,
        team_id: i64,
        distinct_id: &str,
    ) -> StorageResult<Option<Person>>;

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<(String, Option<Person>)>>;

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
    ) -> StorageResult<Vec<((i64, String), Option<Person>)>>;

    // ============================================================
    // Distinct ID operations
    // ============================================================
    async fn get_distinct_ids_for_person(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> StorageResult<Vec<DistinctIdWithVersion>>;

    async fn get_distinct_ids_for_persons(
        &self,
        team_id: i64,
        person_ids: &[i64],
    ) -> StorageResult<Vec<DistinctIdMapping>>;

    // ============================================================
    // Feature Flag support
    // ============================================================
    async fn get_person_ids_and_hash_key_overrides(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<PersonIdWithOverrides>>;

    async fn get_existing_person_ids_with_override_keys(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<PersonIdWithOverrideKeys>>;

    // ============================================================
    // Cohort operations
    // ============================================================
    async fn check_cohort_membership(
        &self,
        person_id: i64,
        cohort_ids: &[i64],
    ) -> StorageResult<Vec<CohortMembership>>;

    // ============================================================
    // Group operations
    // ============================================================
    async fn get_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
    ) -> StorageResult<Option<Group>>;

    async fn get_groups(
        &self,
        team_id: i64,
        identifiers: &[GroupIdentifier],
    ) -> StorageResult<Vec<Group>>;

    async fn get_groups_batch(&self, keys: &[GroupKey]) -> StorageResult<Vec<(GroupKey, Group)>>;

    // ============================================================
    // Group Type Mappings
    // ============================================================
    async fn get_group_type_mappings_by_team_id(
        &self,
        team_id: i64,
    ) -> StorageResult<Vec<GroupTypeMapping>>;

    async fn get_group_type_mappings_by_team_ids(
        &self,
        team_ids: &[i64],
    ) -> StorageResult<Vec<GroupTypeMapping>>;

    async fn get_group_type_mappings_by_project_id(
        &self,
        project_id: i64,
    ) -> StorageResult<Vec<GroupTypeMapping>>;

    async fn get_group_type_mappings_by_project_ids(
        &self,
        project_ids: &[i64],
    ) -> StorageResult<Vec<GroupTypeMapping>>;
}
