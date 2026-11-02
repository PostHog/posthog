use async_trait::async_trait;

use crate::storage::error::StorageResult;
use crate::storage::postgres::ConsistencyLevel;
use crate::storage::types::{DistinctIdMapping, DistinctIdRow, DistinctIdWithVersion};

/// Distinct ID operations - fetching distinct IDs for persons
#[async_trait]
pub trait DistinctIdLookup: Send + Sync {
    async fn get_distinct_ids_for_person(
        &self,
        team_id: i64,
        person_id: i64,
        consistency: ConsistencyLevel,
        limit: Option<i64>,
        cursor_id: Option<i64>,
    ) -> StorageResult<Vec<DistinctIdWithVersion>>;

    async fn get_distinct_ids_for_persons(
        &self,
        team_id: i64,
        person_ids: &[i64],
        consistency: ConsistencyLevel,
        limit_per_person: Option<i64>,
    ) -> StorageResult<Vec<DistinctIdMapping>>;

    /// The mapping rows for `distinct_ids`, live or tombstoned, in distinct id order. Missing ids are left out.
    async fn get_distinct_id_rows(
        &self,
        team_id: i64,
        distinct_ids: &[String],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<DistinctIdRow>>;
}
