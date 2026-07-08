use async_trait::async_trait;
use sqlx::PgPool;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use uuid::Uuid;

use crate::cohorts::cohort_models::CohortId;
use crate::metrics::consts::{
    DB_COHORT_MEMBERSHIP_ERRORS_COUNTER, DB_COHORT_MEMBERSHIP_READS_COUNTER,
    FLAG_REALTIME_COHORT_DB_QUERY_TIME,
};
use common_types::TeamId;

use super::provider::{CohortMembershipError, CohortMembershipProvider};

/// Queries the behavioral cohorts PostgreSQL database for realtime cohort membership.
///
/// The `cohort_membership` table has a unique constraint on (team_id, cohort_id, person_id)
/// with an `in_cohort` boolean indicating active membership.
#[derive(Clone)]
pub struct RealtimeCohortMembershipProvider {
    pool: Arc<PgPool>,
    lookup_timeout: Duration,
}

impl RealtimeCohortMembershipProvider {
    /// Upper bound on one membership lookup, covering pool acquire + query. The pool's
    /// acquire timeout alone is 2s by default, so without this bound an unreachable
    /// behavioral cohorts DB would stall every uncached lookup for a large share of the
    /// 4.5s flags request budget. On timeout the lookup fails like any query error and
    /// the caller degrades to non-membership.
    const DEFAULT_LOOKUP_TIMEOUT: Duration = Duration::from_millis(500);

    pub fn new(pool: Arc<PgPool>) -> Self {
        Self::with_lookup_timeout(pool, Self::DEFAULT_LOOKUP_TIMEOUT)
    }

    pub fn with_lookup_timeout(pool: Arc<PgPool>, lookup_timeout: Duration) -> Self {
        Self {
            pool,
            lookup_timeout,
        }
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

        // The cohort_membership table uses BIGINT columns, so we bind i64 params
        // and decode i64 results. CohortId is i32 today, which is safe as long as
        // IDs stay below ~2.1 billion; if that ceiling is ever reached, CohortId
        // should be widened to i64 across the codebase.
        let cohort_ids_i64: Vec<i64> = cohort_ids.iter().map(|&id| i64::from(id)).collect();
        let query_timer =
            common_metrics::timing_guard_high_precision(FLAG_REALTIME_COHORT_DB_QUERY_TIME, &[]);
        let query_future = sqlx::query_as::<_, CohortMembershipRow>(
            r#"
            SELECT cohort_id
            FROM cohort_membership
            WHERE team_id = $1
              AND person_id = $2
              AND cohort_id = ANY($3)
              AND in_cohort = true
            "#,
        )
        .bind(i64::from(team_id))
        .bind(person_uuid)
        .bind(&cohort_ids_i64)
        .fetch_all(self.pool.as_ref());

        let rows = match tokio::time::timeout(self.lookup_timeout, query_future).await {
            Ok(Ok(rows)) => {
                common_metrics::inc(DB_COHORT_MEMBERSHIP_READS_COUNTER, &[], 1);
                query_timer.label("outcome", "success").fin();
                rows
            }
            Ok(Err(e)) => {
                common_metrics::inc(DB_COHORT_MEMBERSHIP_ERRORS_COUNTER, &[], 1);
                query_timer.label("outcome", "error").fin();
                return Err(CohortMembershipError::QueryFailed(e.to_string()));
            }
            Err(_elapsed) => {
                common_metrics::inc(DB_COHORT_MEMBERSHIP_ERRORS_COUNTER, &[], 1);
                query_timer.label("outcome", "timeout").fin();
                return Err(CohortMembershipError::QueryFailed(format!(
                    "membership lookup timed out after {:?}",
                    self.lookup_timeout
                )));
            }
        };

        let matched_set: std::collections::HashSet<CohortId> = rows
            .iter()
            .filter_map(|r| CohortId::try_from(r.cohort_id).ok())
            .collect();

        let result = cohort_ids
            .iter()
            .map(|id| (*id, matched_set.contains(id)))
            .collect();

        Ok(result)
    }
}

#[derive(sqlx::FromRow)]
struct CohortMembershipRow {
    cohort_id: i64,
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
    use crate::utils::test_utils::TestContext;

    /// Exercises the real SQL against the behavioral cohorts DB: schema drift on
    /// `cohort_membership`, a broken `in_cohort` predicate, or lost team scoping
    /// would surface only here — no other test runs this query.
    #[tokio::test]
    async fn test_realtime_provider_queries_cohort_membership_table() {
        let context = TestContext::new(None).await;
        let Some(pool) = context.behavioral_cohorts_pool.clone() else {
            eprintln!("behavioral cohorts DB not available, skipping");
            return;
        };

        let team_id = 1;
        let person = Uuid::new_v4();
        context
            .insert_cohort_membership(team_id, 101, person, true)
            .await
            .unwrap();
        context
            .insert_cohort_membership(team_id, 102, person, false)
            .await
            .unwrap();
        context
            .insert_cohort_membership(team_id + 1, 103, person, true)
            .await
            .unwrap();

        let provider = RealtimeCohortMembershipProvider::new(pool);
        let result = provider
            .check_memberships(team_id, person, &[101, 102, 103, 104])
            .await
            .unwrap();

        assert!(result[&101], "in_cohort=true row should be a member");
        assert!(!result[&102], "in_cohort=false row should not be a member");
        assert!(
            !result[&103],
            "membership under another team must not leak across teams"
        );
        assert!(!result[&104], "cohort with no row should not be a member");
    }

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
