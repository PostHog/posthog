use async_trait::async_trait;

use crate::storage::error::StorageResult;
use crate::storage::types::{PersonIdWithOverrideKeys, PersonIdWithOverrides};

/// Feature flag hash key override operations
#[async_trait]
pub trait FeatureFlagStorage: Send + Sync {
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
}
