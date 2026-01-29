use std::collections::HashSet;

use async_trait::async_trait;

use super::{PostgresStorage, DB_QUERY_DURATION};
use crate::storage::error::StorageResult;
use crate::storage::traits::CohortStorage;
use crate::storage::types::CohortMembership;

#[async_trait]
impl CohortStorage for PostgresStorage {
    async fn check_cohort_membership(
        &self,
        person_id: i64,
        cohort_ids: &[i64],
    ) -> StorageResult<Vec<CohortMembership>> {
        if cohort_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "check_cohort_membership".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let cohort_ids_i32: Vec<i32> = cohort_ids.iter().map(|&id| id as i32).collect();

        let member_ids: Vec<i32> = sqlx::query_scalar(
            r#"
            SELECT cohort_id
            FROM posthog_cohortpeople
            WHERE person_id = $1 AND cohort_id = ANY($2)
            "#,
        )
        .bind(person_id)
        .bind(&cohort_ids_i32)
        .fetch_all(&self.pool)
        .await?;

        let member_set: HashSet<i64> = member_ids.into_iter().map(|id| id as i64).collect();

        Ok(cohort_ids
            .iter()
            .map(|&cohort_id| CohortMembership {
                cohort_id,
                is_member: member_set.contains(&cohort_id),
            })
            .collect())
    }
}
