//! Run discovery, boundary establishment, and pinned-payload load in PostgreSQL. Owns the
//! `cohort_backfill_runs`/`cohort_backfill_run_cohorts` SQL (Q1/Q2/Q8 + warnings). Depends on `domain`.

use std::str::FromStr;

use chrono::{DateTime, Utc};
use cohort_core::filters::{CohortId, TeamId};
use common_types::cohort::TeamAllowlist;
use serde_json::Value;
use sqlx::types::Json;
use sqlx::{FromRow, PgPool};

use crate::domain::{
    PinnedError, PinnedParticipation, PinnedParticipationState, PinnedRun, PinnedRunSnapshot,
    RunId, TriggerKind, UtcMillis, ValidatedPinnedRun,
};

use super::{RenderedError, PERSISTED_ERROR_LIMIT};

/// The one run-column list the three run SELECTs share. A macro (not a `const`) so it can feed
/// `concat!`, which only accepts literals and macro expansions — the composed SQL text stays a
/// compile-time constant, byte-identical to the former inline lists and pinned by the pg test.
macro_rules! run_columns {
    () => {
        "id, team_id, cohort_id, trigger_kind, scope, status, timezone, boundary_at, pinned"
    };
}

const DISCOVER_ALL: &str = concat!(
    "\n    SELECT ",
    run_columns!(),
    "\n    FROM cohort_backfill_runs",
    "\n    WHERE status IN ('awaiting_boundary', 'seeding')",
    "\n      AND backfill_kind = 'behavioral'",
    "\n    ORDER BY created_at\n"
);

const DISCOVER_ONLY: &str = concat!(
    "\n    SELECT ",
    run_columns!(),
    "\n    FROM cohort_backfill_runs",
    "\n    WHERE status IN ('awaiting_boundary', 'seeding')",
    "\n      AND backfill_kind = 'behavioral'",
    "\n      AND team_id = ANY($1)",
    "\n    ORDER BY created_at\n"
);

const READ_RUN: &str = concat!(
    "\n    SELECT ",
    run_columns!(),
    "\n    FROM cohort_backfill_runs",
    "\n    WHERE id = $1 AND backfill_kind = 'behavioral'\n"
);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunWarningNote {
    ConditionsDropped,
    LookbackTruncated,
}

impl RunWarningNote {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ConditionsDropped => "Seeder dropped unsupported pinned conditions.",
            Self::LookbackTruncated => {
                "Seeder truncated cohort history to the configured lookback."
            }
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunStatus {
    AwaitingBoundary,
    Blocked,
    Seeding,
    Reconciling,
    Completed,
    Superseded,
    Cancelled,
    Failed,
}

impl RunStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::AwaitingBoundary => "awaiting_boundary",
            Self::Blocked => "blocked",
            Self::Seeding => "seeding",
            Self::Reconciling => "reconciling",
            Self::Completed => "completed",
            Self::Superseded => "superseded",
            Self::Cancelled => "cancelled",
            Self::Failed => "failed",
        }
    }
}

impl FromStr for RunStatus {
    type Err = RunError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "awaiting_boundary" => Ok(Self::AwaitingBoundary),
            "blocked" => Ok(Self::Blocked),
            "seeding" => Ok(Self::Seeding),
            "reconciling" => Ok(Self::Reconciling),
            "completed" => Ok(Self::Completed),
            "superseded" => Ok(Self::Superseded),
            "cancelled" => Ok(Self::Cancelled),
            "failed" => Ok(Self::Failed),
            other => Err(RunError::UnknownStatus(other.to_string())),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunScope {
    Team,
    Cohort,
}

impl RunScope {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Team => "team",
            Self::Cohort => "cohort",
        }
    }
}

impl FromStr for RunScope {
    type Err = RunError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "team" => Ok(Self::Team),
            "cohort" => Ok(Self::Cohort),
            other => Err(RunError::UnknownScope(other.to_string())),
        }
    }
}

#[derive(Debug, Clone)]
pub struct DiscoveredRun {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub cohort_id: Option<CohortId>,
    pub trigger: TriggerKind,
    pub scope: RunScope,
    pub status: RunStatus,
    pub timezone: String,
    pub boundary_at: Option<DateTime<Utc>>,
    pub pinned: Value,
}

/// A run proven `seeding` with an established boundary — the only place the boundary `Option`
/// narrows to a value and the trigger stays typed all the way into [`PinnedRunSnapshot`]. Minted
/// only by [`establish_boundary`].
#[derive(Debug, Clone)]
pub struct SeedableRun {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub trigger: TriggerKind,
    pub timezone: String,
    pub boundary_at: UtcMillis,
    pub pinned: Value,
}

impl SeedableRun {
    fn promote(run: DiscoveredRun, boundary_at: DateTime<Utc>) -> Self {
        Self {
            run_id: run.run_id,
            team_id: run.team_id,
            trigger: run.trigger,
            timezone: run.timezone,
            boundary_at: UtcMillis::new(boundary_at.timestamp_millis()),
            pinned: run.pinned,
        }
    }

    pub async fn load_pinned(&self, pool: &PgPool) -> Result<ValidatedPinnedRun, RunError> {
        let rows = sqlx::query_as::<_, ParticipationRow>(
            r#"
            SELECT team_id, cohort_id, filters_shape_hash, pinned_filters, superseded_at
            FROM cohort_backfill_run_cohorts
            WHERE run_id = $1
            ORDER BY cohort_id
            "#,
        )
        .bind(self.run_id)
        .fetch_all(pool)
        .await?;

        let mut participations = Vec::with_capacity(rows.len());
        for row in rows {
            if row.team_id != self.team_id.0 {
                return Err(RunError::CrossTeamParticipation {
                    run_id: self.run_id,
                    cohort_id: CohortId(row.cohort_id),
                    expected_team_id: self.team_id.0,
                    actual_team_id: row.team_id,
                });
            }
            participations.push(PinnedParticipation {
                cohort_id: CohortId(row.cohort_id),
                pinned_filters: row.pinned_filters.0,
                state: if row.superseded_at.is_some() {
                    PinnedParticipationState::Superseded
                } else {
                    PinnedParticipationState::Active
                },
            });
        }
        let snapshot = PinnedRunSnapshot {
            run_id: self.run_id,
            team_id: self.team_id,
            trigger: self.trigger,
            timezone: self.timezone.clone(),
            boundary_at_ms: self.boundary_at.as_i64(),
            pinned: self.pinned.clone(),
            participations,
        };
        Ok(PinnedRun::validate(snapshot)?)
    }
}

#[derive(Debug, Clone)]
pub enum BoundaryOutcome {
    Established(SeedableRun),
    AlreadyEstablished(SeedableRun),
    NoLongerSeedable { run_id: RunId, status: RunStatus },
}

#[derive(Debug, thiserror::Error)]
pub enum RunError {
    #[error("PostgreSQL run operation failed: {0}")]
    Pg(#[from] sqlx::Error),
    #[error(transparent)]
    Pinned(#[from] PinnedError),
    #[error("unknown backfill run status {0:?}")]
    UnknownStatus(String),
    #[error("unknown backfill scope {0:?}")]
    UnknownScope(String),
    #[error("run {run_id:?} has unknown backfill trigger {value:?}")]
    InvalidTrigger { run_id: RunId, value: String },
    #[error("run {run_id:?} has unknown backfill scope {value:?}")]
    InvalidScope { run_id: RunId, value: String },
    #[error("run {run_id:?} has unknown backfill status {value:?}")]
    InvalidStatus { run_id: RunId, value: String },
    #[error("run {0:?} was not found")]
    NotFound(RunId),
    #[error("disaster-recovery run {0:?} has no pinned boundary")]
    DisasterRecoveryBoundaryMissing(RunId),
    #[error("seeding run {0:?} has no established boundary")]
    SeedingBoundaryMissing(RunId),
    #[error("run {0:?} is no longer active and could not be failed")]
    NotActive(RunId),
    #[error(
        "run {run_id:?} team {expected_team_id} has cohort {cohort_id:?} stored under team {actual_team_id}"
    )]
    CrossTeamParticipation {
        run_id: RunId,
        cohort_id: CohortId,
        expected_team_id: i32,
        actual_team_id: i32,
    },
}

impl RunError {
    pub const fn run_id(&self) -> Option<RunId> {
        match self {
            Self::InvalidTrigger { run_id, .. }
            | Self::InvalidScope { run_id, .. }
            | Self::InvalidStatus { run_id, .. }
            | Self::NotFound(run_id)
            | Self::DisasterRecoveryBoundaryMissing(run_id)
            | Self::SeedingBoundaryMissing(run_id)
            | Self::NotActive(run_id)
            | Self::CrossTeamParticipation { run_id, .. } => Some(*run_id),
            Self::Pg(_) | Self::Pinned(_) | Self::UnknownStatus(_) | Self::UnknownScope(_) => None,
        }
    }
}

#[derive(Debug, FromRow)]
struct RunRow {
    id: RunId,
    team_id: i32,
    cohort_id: Option<i32>,
    trigger_kind: String,
    scope: String,
    status: String,
    timezone: String,
    boundary_at: Option<DateTime<Utc>>,
    pinned: Json<Value>,
}

impl TryFrom<RunRow> for DiscoveredRun {
    type Error = RunError;

    fn try_from(row: RunRow) -> Result<Self, Self::Error> {
        let trigger =
            row.trigger_kind
                .parse::<TriggerKind>()
                .map_err(|_| RunError::InvalidTrigger {
                    run_id: row.id,
                    value: row.trigger_kind.clone(),
                })?;
        let scope = row.scope.parse().map_err(|_| RunError::InvalidScope {
            run_id: row.id,
            value: row.scope.clone(),
        })?;
        let status = row.status.parse().map_err(|_| RunError::InvalidStatus {
            run_id: row.id,
            value: row.status.clone(),
        })?;
        Ok(Self {
            run_id: row.id,
            team_id: TeamId(row.team_id),
            cohort_id: row.cohort_id.map(CohortId),
            trigger,
            scope,
            status,
            timezone: row.timezone,
            boundary_at: row.boundary_at,
            pinned: row.pinned.0,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn malformed_discovered_rows_keep_the_run_capability_for_q8() {
        let run_id = RunId(uuid::Uuid::from_u128(1));
        let error = DiscoveredRun::try_from(RunRow {
            id: run_id,
            team_id: 2,
            cohort_id: None,
            trigger_kind: "invalid".to_string(),
            scope: "team".to_string(),
            status: "seeding".to_string(),
            timezone: "UTC".to_string(),
            boundary_at: Some(Utc::now()),
            pinned: Json(serde_json::json!({})),
        })
        .unwrap_err();

        assert!(matches!(
            &error,
            RunError::InvalidTrigger {
                run_id: observed,
                ..
            } if *observed == run_id
        ));
        assert_eq!(error.run_id(), Some(run_id));
    }
}

#[derive(Debug, FromRow)]
struct ParticipationRow {
    team_id: i32,
    cohort_id: i32,
    /// B5 CAS-readiness / reconcile seam: the filters shape hash read from
    /// `cohort_backfill_run_cohorts` for a future reconcile slice. Populated by Q1 (whose SQL stays
    /// frozen) but not yet read, so the attr suppresses the dead-field lint until that slice lands.
    #[allow(dead_code)]
    filters_shape_hash: String,
    pinned_filters: Json<Value>,
    superseded_at: Option<DateTime<Utc>>,
}

#[derive(Debug, FromRow)]
struct BoundaryRow {
    boundary_at: DateTime<Utc>,
}

pub async fn discover_runs(
    pool: &PgPool,
    allowlist: &TeamAllowlist,
) -> Result<Vec<DiscoveredRun>, RunError> {
    let rows = match allowlist {
        TeamAllowlist::All => {
            sqlx::query_as::<_, RunRow>(DISCOVER_ALL)
                .fetch_all(pool)
                .await?
        }
        TeamAllowlist::Only(team_ids) => {
            let mut team_ids = team_ids.iter().copied().collect::<Vec<_>>();
            team_ids.sort_unstable();
            sqlx::query_as::<_, RunRow>(DISCOVER_ONLY)
                .bind(team_ids)
                .fetch_all(pool)
                .await?
        }
    };
    rows.into_iter().map(DiscoveredRun::try_from).collect()
}

pub async fn establish_boundary(
    pool: &PgPool,
    run: DiscoveredRun,
) -> Result<BoundaryOutcome, RunError> {
    if run.status == RunStatus::Seeding {
        return match run.boundary_at {
            Some(boundary_at) => Ok(BoundaryOutcome::AlreadyEstablished(SeedableRun::promote(
                run,
                boundary_at,
            ))),
            None => Err(RunError::SeedingBoundaryMissing(run.run_id)),
        };
    }
    if run.trigger == TriggerKind::DisasterRecovery && run.boundary_at.is_none() {
        return Err(RunError::DisasterRecoveryBoundaryMissing(run.run_id));
    }

    let boundary = match run.trigger {
        TriggerKind::DisasterRecovery => {
            sqlx::query_as::<_, BoundaryRow>(
                r#"
            UPDATE cohort_backfill_runs
            SET status = 'seeding', boundary_established_at = now(), updated_at = now()
            WHERE id = $1 AND status = 'awaiting_boundary'
              AND trigger_kind = 'disaster_recovery' AND boundary_at IS NOT NULL
            RETURNING boundary_at
            "#,
            )
            .bind(run.run_id)
            .fetch_optional(pool)
            .await?
        }
        TriggerKind::TeamEnablement | TriggerKind::CohortCreated | TriggerKind::CohortEdited => {
            sqlx::query_as::<_, BoundaryRow>(
                r#"
                UPDATE cohort_backfill_runs
                SET status = 'seeding', boundary_at = now(), boundary_established_at = now(),
                    updated_at = now()
                WHERE id = $1 AND status = 'awaiting_boundary' AND boundary_at IS NULL
                  AND trigger_kind IN ('team_enablement', 'cohort_created', 'cohort_edited')
                RETURNING boundary_at
                "#,
            )
            .bind(run.run_id)
            .fetch_optional(pool)
            .await?
        }
    };

    if let Some(boundary) = boundary {
        return Ok(BoundaryOutcome::Established(SeedableRun::promote(
            run,
            boundary.boundary_at,
        )));
    }

    let current = read_run(pool, run.run_id).await?;
    if current.status == RunStatus::Seeding {
        match current.boundary_at {
            Some(boundary_at) => Ok(BoundaryOutcome::AlreadyEstablished(SeedableRun::promote(
                current,
                boundary_at,
            ))),
            None => Err(RunError::SeedingBoundaryMissing(current.run_id)),
        }
    } else {
        Ok(BoundaryOutcome::NoLongerSeedable {
            run_id: current.run_id,
            status: current.status,
        })
    }
}

pub async fn fail_run(pool: &PgPool, run_id: RunId, error: &RenderedError) -> Result<(), RunError> {
    let failed = sqlx::query_scalar::<_, RunId>(
        r#"
        UPDATE cohort_backfill_runs
        SET status = 'failed', error = left($2, $3), finished_at = now(), updated_at = now()
        WHERE id = $1 AND status IN ('awaiting_boundary', 'seeding')
        RETURNING id
        "#,
    )
    .bind(run_id)
    .bind(error.as_str())
    .bind(PERSISTED_ERROR_LIMIT)
    .fetch_optional(pool)
    .await?;
    failed.map(|_| ()).ok_or(RunError::NotActive(run_id))
}

pub async fn record_run_warning(
    pool: &PgPool,
    run_id: RunId,
    note: RunWarningNote,
) -> Result<bool, RunError> {
    let updated = sqlx::query_scalar::<_, RunId>(
        r#"
        UPDATE cohort_backfill_runs
        SET error = left(
                CASE WHEN error = '' THEN $2 ELSE $2 || E'\n' || error END,
                $3
            ),
            updated_at = now()
        WHERE id = $1 AND status = 'seeding' AND strpos(error, $2) = 0
        RETURNING id
        "#,
    )
    .bind(run_id)
    .bind(note.as_str())
    .bind(PERSISTED_ERROR_LIMIT)
    .fetch_optional(pool)
    .await?;
    Ok(updated.is_some())
}

async fn read_run(pool: &PgPool, run_id: RunId) -> Result<DiscoveredRun, RunError> {
    let row = sqlx::query_as::<_, RunRow>(READ_RUN)
        .bind(run_id)
        .fetch_optional(pool)
        .await?
        .ok_or(RunError::NotFound(run_id))?;
    row.try_into()
}
