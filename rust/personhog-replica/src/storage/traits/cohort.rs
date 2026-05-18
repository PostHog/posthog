use async_trait::async_trait;

use crate::storage::error::StorageResult;
use crate::storage::postgres::ConsistencyLevel;
use crate::storage::types::CohortMembership;

/// Cohort membership operations
#[async_trait]
pub trait CohortStorage: Send + Sync {
    async fn check_cohort_membership(
        &self,
        person_id: i64,
        cohort_ids: &[i64],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<CohortMembership>>;

    async fn count_cohort_members(
        &self,
        cohort_ids: &[i64],
        consistency: ConsistencyLevel,
    ) -> StorageResult<i64>;

    async fn delete_cohort_member(&self, cohort_id: i64, person_id: i64) -> StorageResult<bool>;

    async fn delete_cohort_members_bulk(
        &self,
        cohort_ids: &[i64],
        batch_size: i32,
    ) -> StorageResult<i64>;

    async fn insert_cohort_members(
        &self,
        cohort_id: i64,
        person_ids: &[i64],
        version: Option<i32>,
    ) -> StorageResult<i64>;

    async fn list_cohort_member_ids(
        &self,
        cohort_id: i64,
        cursor: i64,
        limit: i32,
        consistency: ConsistencyLevel,
    ) -> StorageResult<(Vec<i64>, Option<i64>)>;
}
