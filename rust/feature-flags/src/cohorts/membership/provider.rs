use axum::async_trait;
use std::collections::HashMap;
use thiserror::Error;
use uuid::Uuid;

use crate::cohorts::cohort_models::CohortId;
use common_types::TeamId;

#[derive(Error, Debug, Clone)]
pub enum CohortMembershipError {
    #[error("Query failed: {0}")]
    QueryFailed(String),
}

/// Provides cohort membership lookups for realtime/behavioral cohorts.
///
/// Implementations query the behavioral cohorts database to determine whether
/// a person is a member of specific cohorts. Results are returned as a map of
/// cohort_id -> is_member, which integrates directly with the existing
/// `apply_cohort_membership_logic` function.
#[async_trait]
pub trait CohortMembershipProvider: Send + Sync + 'static {
    /// Check membership for a person across multiple cohorts.
    ///
    /// Returns a map of cohort_id -> is_member for each requested cohort.
    /// Cohorts where the person is not a member will have `false`.
    async fn check_memberships(
        &self,
        team_id: TeamId,
        person_uuid: Uuid,
        cohort_ids: &[CohortId],
    ) -> Result<HashMap<CohortId, bool>, CohortMembershipError>;
}
