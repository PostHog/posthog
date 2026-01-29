use async_trait::async_trait;

use crate::storage::error::StorageResult;
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
    ) -> StorageResult<Option<Group>>;

    async fn get_groups(
        &self,
        team_id: i64,
        identifiers: &[GroupIdentifier],
    ) -> StorageResult<Vec<Group>>;

    async fn get_groups_batch(&self, keys: &[GroupKey]) -> StorageResult<Vec<(GroupKey, Group)>>;

    // Group type mappings

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
