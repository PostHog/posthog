use axum::async_trait;
use sqlx::PgPool;
use std::collections::HashMap;
use std::sync::Arc;
use uuid::Uuid;

use crate::cohorts::cohort_models::CohortId;
use common_types::TeamId;

use super::provider::{CohortMembershipError, CohortMembershipProvider};

/// Queries the behavioral cohorts PostgreSQL database for realtime cohort membership.
///
/// The `cohort_membership` table has a unique constraint on (team_id, cohort_id, person_id)
/// with an `in_cohort` boolean indicating active membership.
#[derive(Clone)]
pub struct RealtimeCohortMembershipProvider {
    pool: Arc<PgPool>,
}

impl RealtimeCohortMembershipProvider {
    pub fn new(pool: Arc<PgPool>) -> Self {
        Self { pool }
    }
}

#[async_trait]
impl CohortMembershipProvider for RealtimeCohortMembershipProvider {
    async fn check_memberships(
        &self,
        team_id: TeamId,
        person_uuid: Uuid,
        cohort_ids: &[CohortId],
    ) -> Result<HashMap<CohortId, bool>, CohortMembershipError> {
        if cohort_ids.is_empty() {
            return Ok(HashMap::new());
        }

        let matched_cohort_ids: Vec<CohortMembershipRow> = sqlx::query_as(
            r#"
            SELECT cohort_id
            FROM cohort_membership
            WHERE team_id = $1
              AND person_id = $2
              AND cohort_id = ANY($3)
              AND in_cohort = true
            "#,
        )
        .bind(team_id)
        .bind(person_uuid)
        .bind(cohort_ids)
        .fetch_all(self.pool.as_ref())
        .await
        .map_err(|e| CohortMembershipError::QueryFailed(e.to_string()))?;

        let matched_set: std::collections::HashSet<CohortId> =
            matched_cohort_ids.iter().map(|r| r.cohort_id).collect();

        let result = cohort_ids
            .iter()
            .map(|id| (*id, matched_set.contains(id)))
            .collect();

        Ok(result)
    }
}

#[derive(sqlx::FromRow)]
struct CohortMembershipRow {
    cohort_id: CohortId,
}

/// No-op provider used when the behavioral cohorts database is not configured.
/// Conservatively returns false (not a member) for all lookups.
pub struct NoOpCohortMembershipProvider;

#[async_trait]
impl CohortMembershipProvider for NoOpCohortMembershipProvider {
    async fn check_memberships(
        &self,
        _team_id: TeamId,
        _person_uuid: Uuid,
        cohort_ids: &[CohortId],
    ) -> Result<HashMap<CohortId, bool>, CohortMembershipError> {
        Ok(cohort_ids.iter().map(|id| (*id, false)).collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_noop_provider_returns_false_for_all() {
        let provider = NoOpCohortMembershipProvider;
        let cohort_ids = vec![1, 2, 3];

        let result = provider
            .check_memberships(1, Uuid::new_v4(), &cohort_ids)
            .await
            .unwrap();

        assert_eq!(result.len(), 3);
        assert!(!result[&1]);
        assert!(!result[&2]);
        assert!(!result[&3]);
    }

    #[tokio::test]
    async fn test_noop_provider_empty_cohorts() {
        let provider = NoOpCohortMembershipProvider;

        let result = provider
            .check_memberships(1, Uuid::new_v4(), &[])
            .await
            .unwrap();

        assert!(result.is_empty());
    }
}
