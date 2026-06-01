use async_trait::async_trait;

use crate::storage::error::StorageResult;
use crate::storage::postgres::ConsistencyLevel;
use crate::storage::types::{Group, GroupIdentifier, GroupKey, GroupTypeMapping};

/// Group and group type mapping operations
#[async_trait]
pub trait GroupStorage: Send + Sync {
    // Group lookups

    async fn get_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Option<Group>>;

    async fn get_groups(
        &self,
        team_id: i64,
        identifiers: &[GroupIdentifier],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<Group>>;

    async fn get_groups_batch(
        &self,
        keys: &[GroupKey],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<(GroupKey, Group)>>;

    // Group writes

    async fn create_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
        group_properties: &serde_json::Value,
        created_at: chrono::DateTime<chrono::Utc>,
    ) -> StorageResult<Group>;

    #[allow(clippy::too_many_arguments)]
    async fn update_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
        update_mask: &[String],
        group_properties: Option<&serde_json::Value>,
        properties_last_updated_at: Option<&serde_json::Value>,
        properties_last_operation: Option<&serde_json::Value>,
        created_at: Option<chrono::DateTime<chrono::Utc>>,
    ) -> StorageResult<Option<Group>>;

    async fn delete_groups_batch_for_team(
        &self,
        team_id: i64,
        batch_size: i64,
    ) -> StorageResult<i64>;

    // Group type mapping lookups

    async fn get_group_type_mappings_by_team_id(
        &self,
        team_id: i64,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<GroupTypeMapping>>;

    async fn get_group_type_mappings_by_team_ids(
        &self,
        team_ids: &[i64],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<GroupTypeMapping>>;

    async fn get_group_type_mappings_by_project_id(
        &self,
        project_id: i64,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<GroupTypeMapping>>;

    async fn get_group_type_mappings_by_project_ids(
        &self,
        project_ids: &[i64],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<GroupTypeMapping>>;

    async fn get_group_type_mapping_by_dashboard_id(
        &self,
        team_id: i64,
        dashboard_id: i64,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Option<GroupTypeMapping>>;

    // Group type mapping writes

    #[allow(clippy::too_many_arguments)]
    async fn update_group_type_mapping(
        &self,
        project_id: i64,
        group_type_index: i32,
        update_mask: &[String],
        name_singular: Option<&str>,
        name_plural: Option<&str>,
        detail_dashboard_id: Option<i64>,
        default_columns: Option<&[String]>,
    ) -> StorageResult<Option<GroupTypeMapping>>;

    async fn delete_group_type_mapping(
        &self,
        project_id: i64,
        group_type_index: i32,
    ) -> StorageResult<bool>;

    async fn delete_group_type_mappings_batch_for_team(
        &self,
        team_id: i64,
        batch_size: i64,
    ) -> StorageResult<i64>;
}
