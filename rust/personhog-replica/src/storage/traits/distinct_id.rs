use async_trait::async_trait;

use crate::storage::error::StorageResult;
use crate::storage::types::{DistinctIdMapping, DistinctIdWithVersion};

/// Distinct ID operations - fetching distinct IDs for persons
#[async_trait]
pub trait DistinctIdLookup: Send + Sync {
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
}
