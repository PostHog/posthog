use async_trait::async_trait;

use crate::storage::error::StorageResult;
use crate::storage::types::CohortMembership;

/// Cohort membership operations
#[async_trait]
pub trait CohortStorage: Send + Sync {
    async fn check_cohort_membership(
        &self,
        person_id: i64,
        cohort_ids: &[i64],
    ) -> StorageResult<Vec<CohortMembership>>;
}
