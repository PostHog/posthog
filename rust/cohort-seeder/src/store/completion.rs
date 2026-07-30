//! The backfill-completion protocol's PostgreSQL access: the planning-proof stamp, the
//! `seeding → reconciling` CAS, the atomic dispatch record, and the epoch-fenced observation writes
//! the observer drives. `sqlx` stays confined here; everything above receives typed
//! rows, typed capabilities, and typed errors. Depends on `domain` and the sibling store helpers.
//!
//! Every observation write carries the dispatch fence `AND reconcile_dispatched_at = $epoch AND
//! status = 'reconciling'`. A miss returns [`CompletionStoreError::CompletionFenceLost`], mirroring
//! the chunk store's `LeaseLost`: a stale writer (an older dispatch superseded by a re-dispatch, or a
//! run Django has already moved on) can never clobber the ruling dispatch's state.

use chrono::{DateTime, Utc};
use cohort_core::filters::{CohortId, TeamId};
use common_types::cohort::TeamAllowlist;
use serde_json::Value;
use sqlx::types::Json;
use sqlx::{FromRow, PgPool};
use std::collections::{HashMap, HashSet};
use std::fmt;

use crate::domain::{
    BehavioralShapeHash, BehavioralShapeHashError, CompletionParts, CompletionPhase,
    CompletionStatus, DispatchEpoch, MarkerWatch, ObservationEnds, PartitionBitmap,
    PartitionBitmapError, ReconcileHwms, RunId, WatchPositions, MARKER_WATCH_SCHEMA,
};

use super::runs::RunKind;

use super::{RenderedError, PERSISTED_ERROR_LIMIT};

/// The completion columns the two discovery SELECTs share, kept in a macro so both queries stay
/// byte-identical and the composed SQL is a compile-time constant (mirrors `runs::run_columns!`).
macro_rules! completion_columns {
    () => {
        "id, team_id, status, chunks_planned_at, reconcile_dispatched_at, \
         reconcile_observed_at, reconcile_hwms, marker_watch"
    };
}

// Status vocabulary the composed SQL names, kept in macros so the queries stay compile-time
// constants while a unit test can still scan them against the status enums — the same drift guard
// `chunks.rs` applies to its `IN` fragments.
macro_rules! seeding_status {
    () => {
        "'seeding'"
    };
}
macro_rules! reconciling_status {
    () => {
        "'reconciling'"
    };
}
macro_rules! confirmed_chunk_status {
    () => {
        "'confirmed'"
    };
}

const DISCOVER_COMPLETION_ALL: &str = concat!(
    "\n    SELECT ",
    completion_columns!(),
    "\n    FROM cohort_backfill_runs",
    "\n    WHERE status IN (",
    seeding_status!(),
    ", ",
    reconciling_status!(),
    ")",
    "\n      AND backfill_kind = 'behavioral'",
    "\n    ORDER BY created_at\n"
);

const DISCOVER_COMPLETION_ONLY: &str = concat!(
    "\n    SELECT ",
    completion_columns!(),
    "\n    FROM cohort_backfill_runs",
    "\n    WHERE status IN (",
    seeding_status!(),
    ", ",
    reconciling_status!(),
    ")",
    "\n      AND backfill_kind = 'behavioral'",
    "\n      AND team_id = ANY($1)",
    "\n    ORDER BY created_at\n"
);

const CAS_RUN_RECONCILING: &str = concat!(
    "\n        UPDATE cohort_backfill_runs",
    "\n        SET status = ",
    reconciling_status!(),
    ", updated_at = now()",
    "\n        WHERE id = $1 AND backfill_kind = 'behavioral' AND status = ",
    seeding_status!(),
    " AND chunks_planned_at IS NOT NULL",
    "\n          AND NOT EXISTS (",
    "\n              SELECT 1 FROM cohort_backfill_chunks",
    "\n              WHERE run_id = $1 AND status <> ",
    confirmed_chunk_status!(),
    "\n          )",
    "\n        RETURNING id, reconcile_dispatched_at\n"
);

const RUNS_WITH_ALL_CHUNKS_CONFIRMED: &str = concat!(
    "\n    SELECT candidate.run_id",
    "\n    FROM unnest($1::uuid[]) AS candidate(run_id)",
    "\n    WHERE NOT EXISTS (",
    "\n        SELECT 1 FROM cohort_backfill_chunks",
    "\n        WHERE run_id = candidate.run_id AND status <> ",
    confirmed_chunk_status!(),
    "\n    )\n"
);

/// Which fenced write lost its dispatch epoch. Carried on [`CompletionStoreError::CompletionFenceLost`]
/// so operators can see where a stale observation was rejected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CompletionOperation {
    RecordDispatch,
    PersistEnds,
    PersistObservations,
    MarkCompleted,
    RecordPartial,
    RecordShortfall,
    MarkObserved,
    MarkObservedUnreconcilable,
}

impl fmt::Display for CompletionOperation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::RecordDispatch => "record-dispatch",
            Self::PersistEnds => "persist-ends",
            Self::PersistObservations => "persist-observations",
            Self::MarkCompleted => "mark-completed",
            Self::RecordPartial => "record-partial",
            Self::RecordShortfall => "record-shortfall",
            Self::MarkObserved => "mark-observed",
            Self::MarkObservedUnreconcilable => "mark-observed-unreconcilable",
        })
    }
}

#[derive(Debug, thiserror::Error)]
pub enum CompletionStoreError {
    #[error("PostgreSQL completion operation failed")]
    Pg(#[from] sqlx::Error),
    #[error("run {run_id:?} lost its dispatch fence during {operation}")]
    CompletionFenceLost {
        run_id: RunId,
        operation: CompletionOperation,
    },
    #[error("run {run_id:?} cohort {cohort_id:?} has out-of-range reconcile marker bits")]
    InvalidMarkerBits {
        run_id: RunId,
        cohort_id: CohortId,
        #[source]
        source: PartitionBitmapError,
    },
    #[error("run {run_id:?} cohort {cohort_id:?} has an invalid pinned behavioral shape hash")]
    InvalidBehavioralShapeHash {
        run_id: RunId,
        cohort_id: CohortId,
        #[source]
        source: BehavioralShapeHashError,
    },
}

/// Whether the planning-proof stamp was applied by this call or was already present.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlanningStampOutcome {
    Stamped,
    Skipped,
}

/// A run proven to hold `reconciling` status, minted only by the CAS out of `seeding`
/// ([`cas_run_reconciling`]) or by re-confirming an already-reconciling run ([`confirm_reconciling`]).
/// It is linear: [`ReconcilingClaim::record`] persists the dispatch or [`ReconcilingClaim::revert`]
/// releases it back to `seeding`, and either consumes the claim so a dispatch can never be recorded
/// twice off one CAS. Both minting queries filter `backfill_kind`, so a claim also proves the run
/// belongs to this protocol.
#[must_use]
#[derive(Debug)]
pub struct ReconcilingClaim {
    run_id: RunId,
    /// `reconcile_dispatched_at` as of the mint; `None` for a never-dispatched run.
    dispatched_at_mint: Option<DateTime<Utc>>,
}

impl ReconcilingClaim {
    pub const fn run_id(&self) -> RunId {
        self.run_id
    }

    /// Roll the run back to `seeding` after a post-CAS `Incomplete` (a `bands_per_day` raise that
    /// added chunks between the CAS proving zero remaining and the dispatch). Any dispatch record is
    /// cleared with the status: a re-dispatch of a run with an unparseable record can land here, and
    /// leaving the columns behind would strand the run as a seeding-with-reconcile-columns anomaly.
    ///
    /// Fenced on the epoch observed at mint: `confirm_reconciling` is not exclusive, so without it a
    /// losing replica's revert would wipe a winner's just-recorded dispatch. Best-effort otherwise —
    /// a run that already left `reconciling` simply matches nothing.
    pub async fn revert(self, pool: &PgPool) -> Result<(), CompletionStoreError> {
        sqlx::query(
            r#"
            UPDATE cohort_backfill_runs
            SET status = 'seeding', reconcile_dispatched_at = NULL, reconcile_observed_at = NULL,
                reconcile_hwms = NULL, marker_watch = NULL, updated_at = now()
            WHERE id = $1 AND status = 'reconciling'
              AND reconcile_dispatched_at IS NOT DISTINCT FROM $2
            "#,
        )
        .bind(self.run_id)
        .bind(self.dispatched_at_mint)
        .execute(pool)
        .await?;
        Ok(())
    }

    /// Atomically write the whole dispatch record: set `reconcile_hwms`, `marker_watch`, a fresh
    /// `reconcile_dispatched_at` fence, null `reconcile_observed_at`, and reset every non-superseded
    /// participation's bits/completion/error. Returns the fence epoch minted from the RETURNING
    /// timestamp.
    ///
    /// Fenced on the mint epoch like [`ReconcilingClaim::revert`]: the reset discards marker bits and
    /// completions, so a second claimant committing after the first would silently undo observations
    /// already merged under the ruling epoch. The loser gets `CompletionFenceLost`, which the driver
    /// counts and retries. A run Django moved out of `reconciling` loses the fence the same way.
    pub async fn record(
        self,
        pool: &PgPool,
        hwms: &ReconcileHwms,
        watch: &MarkerWatch,
    ) -> Result<DispatchEpoch, CompletionStoreError> {
        let run_id = self.run_id;
        let mut tx = pool.begin().await?;
        let dispatched_at = sqlx::query_scalar::<_, DateTime<Utc>>(
            r#"
            UPDATE cohort_backfill_runs
            SET reconcile_hwms = $2, marker_watch = $3,
                reconcile_dispatched_at = now(), reconcile_observed_at = NULL, updated_at = now()
            WHERE id = $1 AND status = 'reconciling'
              AND reconcile_dispatched_at IS NOT DISTINCT FROM $4
            RETURNING reconcile_dispatched_at
            "#,
        )
        .bind(run_id)
        .bind(Json(hwms))
        .bind(Json(watch))
        .bind(self.dispatched_at_mint)
        .fetch_optional(&mut *tx)
        .await?
        .ok_or(CompletionStoreError::CompletionFenceLost {
            run_id,
            operation: CompletionOperation::RecordDispatch,
        })?;

        sqlx::query(
            r#"
            UPDATE cohort_backfill_run_cohorts
            SET reconcile_marker_bits = 0, reconcile_completed_at = NULL, error = ''
            WHERE run_id = $1 AND superseded_at IS NULL
            "#,
        )
        .bind(run_id)
        .execute(&mut *tx)
        .await?;

        tx.commit().await?;
        Ok(DispatchEpoch::from_dispatched_at(dispatched_at))
    }
}

/// Stamp the planning proof (`chunks_planned_at`) exactly once for a seeding run — the durable
/// evidence that chunk planning ran, which distinguishes a legitimately zero-chunk run from one
/// whose planning has not yet happened. The stamp pair is the one kind-parameterized exception to
/// this module's hardcoded behavioral filters: person runs earn their planning proof here too,
/// while every other entry point stays behavioral-only, so a `person_property` run id handed to
/// the reconcile protocol can never enter it.
pub async fn mark_chunks_planned(
    pool: &PgPool,
    run_id: RunId,
    kind: RunKind,
) -> Result<PlanningStampOutcome, CompletionStoreError> {
    let stamped = sqlx::query_scalar::<_, RunId>(
        r#"
        UPDATE cohort_backfill_runs
        SET chunks_planned_at = now(), updated_at = now()
        WHERE id = $1 AND backfill_kind = $2 AND status = 'seeding'
          AND chunks_planned_at IS NULL
        RETURNING id
        "#,
    )
    .bind(run_id)
    .bind(kind.as_str())
    .fetch_optional(pool)
    .await?;
    Ok(if stamped.is_some() {
        PlanningStampOutcome::Stamped
    } else {
        PlanningStampOutcome::Skipped
    })
}

/// The planning-proof timestamp, read for the dispatch-completion check. `None` means either the run
/// is absent or planning has not been stamped.
pub async fn read_planning_stamp(
    pool: &PgPool,
    run_id: RunId,
    kind: RunKind,
) -> Result<Option<DateTime<Utc>>, CompletionStoreError> {
    let stamp: Option<Option<DateTime<Utc>>> = sqlx::query_scalar(
        "SELECT chunks_planned_at FROM cohort_backfill_runs \
         WHERE id = $1 AND backfill_kind = $2",
    )
    .bind(run_id)
    .bind(kind.as_str())
    .fetch_optional(pool)
    .await?;
    Ok(stamp.flatten())
}

/// CAS a seeding run into `reconciling`. Admits the transition only once planning is proven and every
/// chunk has confirmed, freezing the chunk ledger (`claim_next`/`heartbeat`/`plan_chunks` all require
/// `seeding`). `None` means the CAS was lost — another dispatcher won, chunks reappeared, or the run
/// left `seeding`.
pub async fn cas_run_reconciling(
    pool: &PgPool,
    run_id: RunId,
) -> Result<Option<ReconcilingClaim>, CompletionStoreError> {
    let claimed = sqlx::query_as::<_, ClaimRow>(CAS_RUN_RECONCILING)
        .bind(run_id)
        .fetch_optional(pool)
        .await?;
    Ok(claimed.map(ClaimRow::into_claim))
}

/// Mint a claim for an already-`reconciling` run so a re-dispatch (self-healing an undispatched or
/// stale record) can rewrite its dispatch state. `None` means the run is no longer `reconciling`.
/// Non-exclusive by design — whichever claimant records last sets the ruling fence.
pub async fn confirm_reconciling(
    pool: &PgPool,
    run_id: RunId,
) -> Result<Option<ReconcilingClaim>, CompletionStoreError> {
    let claimed = sqlx::query_as::<_, ClaimRow>(
        r#"
        UPDATE cohort_backfill_runs
        SET updated_at = now()
        WHERE id = $1 AND backfill_kind = 'behavioral' AND status = 'reconciling'
        RETURNING id, reconcile_dispatched_at
        "#,
    )
    .bind(run_id)
    .fetch_optional(pool)
    .await?;
    Ok(claimed.map(ClaimRow::into_claim))
}

/// Record the captured observation ends under the dispatch fence — the once-per-dispatch write that
/// arms the settlement proof. It patches only the `ends` key: the observer holds discovery-time
/// positions, so writing the whole document would race the watch task's position flush and regress
/// the watcher's coverage (safe in direction, but on an idle topic nothing would ever repair it and
/// the run could never mint a proof).
pub async fn persist_observation_ends(
    pool: &PgPool,
    run_id: RunId,
    epoch: DispatchEpoch,
    ends: &ObservationEnds,
) -> Result<(), CompletionStoreError> {
    let updated = sqlx::query_scalar::<_, RunId>(
        r#"
        UPDATE cohort_backfill_runs
        SET marker_watch = jsonb_set(
                coalesce(marker_watch, jsonb_build_object('schema', $4::bigint, 'positions', '{}'::jsonb)),
                '{ends}', $3::jsonb, true
            ),
            updated_at = now()
        WHERE id = $1 AND reconcile_dispatched_at = $2 AND status = 'reconciling'
        RETURNING id
        "#,
    )
    .bind(run_id)
    .bind(epoch.as_datetime())
    .bind(Json(ends))
    .bind(i64::from(MARKER_WATCH_SCHEMA))
    .fetch_optional(pool)
    .await?;
    fence(updated, run_id, CompletionOperation::PersistEnds)
}

/// OR-merge observed marker bits into every named cohort and advance the watcher positions, in one
/// fenced transaction. The bit merge is idempotent (`bits | $bits`), so a replayed flush is a no-op.
/// Repeated cohort ids in `bit_updates` are folded with `bit_or` first: `UPDATE ... FROM` applies a
/// single source row per target, so unfolded duplicates would silently drop every bit but one's.
pub async fn persist_marker_observations(
    pool: &PgPool,
    run_id: RunId,
    epoch: DispatchEpoch,
    bit_updates: &[(CohortId, PartitionBitmap)],
    positions: &WatchPositions,
) -> Result<(), CompletionStoreError> {
    let mut tx = pool.begin().await?;
    // The positions write also proves the fence: its RETURNING gates the whole transaction.
    // `jsonb_set(NULL, ...)` is NULL, which would wipe the document instead of advancing it. A NULL
    // `marker_watch` under a live fence is unreachable (`record` writes both atomically), so the
    // coalesce only keeps a hypothetical stray NULL from discarding the positions being flushed.
    let fenced = sqlx::query_scalar::<_, RunId>(
        r#"
        UPDATE cohort_backfill_runs
        SET marker_watch = jsonb_set(
                coalesce(marker_watch, jsonb_build_object('schema', $4::bigint, 'ends', NULL)),
                '{positions}', $3::jsonb, true
            ),
            updated_at = now()
        WHERE id = $1 AND reconcile_dispatched_at = $2 AND status = 'reconciling'
        RETURNING id
        "#,
    )
    .bind(run_id)
    .bind(epoch.as_datetime())
    .bind(Json(positions))
    .bind(i64::from(MARKER_WATCH_SCHEMA))
    .fetch_optional(&mut *tx)
    .await?;
    if fenced.is_none() {
        return Err(CompletionStoreError::CompletionFenceLost {
            run_id,
            operation: CompletionOperation::PersistObservations,
        });
    }

    if !bit_updates.is_empty() {
        let cohort_ids: Vec<i32> = bit_updates.iter().map(|(cohort, _)| cohort.0).collect();
        let bits: Vec<i64> = bit_updates
            .iter()
            .map(|(_, bitmap)| bitmap.as_bits())
            .collect();
        sqlx::query(
            r#"
            UPDATE cohort_backfill_run_cohorts c
            SET reconcile_marker_bits = c.reconcile_marker_bits | u.bits
            FROM (
                SELECT cohort_id, bit_or(bits) AS bits
                FROM unnest($2::int[], $3::bigint[]) AS raw(cohort_id, bits)
                GROUP BY cohort_id
            ) AS u
            WHERE c.run_id = $1 AND c.cohort_id = u.cohort_id AND c.superseded_at IS NULL
            "#,
        )
        .bind(run_id)
        .bind(cohort_ids)
        .bind(bits)
        .execute(&mut *tx)
        .await?;
    }

    tx.commit().await?;
    Ok(())
}

/// Mark one cohort's reconcile complete (64/64 markers). Idempotent via the `IS NULL` guard, and
/// skipped for superseded participations — supersession trumps completion.
pub async fn mark_participation_completed(
    pool: &PgPool,
    run_id: RunId,
    epoch: DispatchEpoch,
    cohort_id: CohortId,
) -> Result<(), CompletionStoreError> {
    let probe = sqlx::query_scalar::<_, bool>(
        r#"
        WITH fence AS (
            SELECT id FROM cohort_backfill_runs
            WHERE id = $1 AND reconcile_dispatched_at = $2 AND status = 'reconciling'
            FOR UPDATE
        ), updated AS (
            UPDATE cohort_backfill_run_cohorts c
            SET reconcile_completed_at = now()
            FROM fence
            WHERE c.run_id = fence.id AND c.cohort_id = $3
              AND c.reconcile_completed_at IS NULL AND c.superseded_at IS NULL
            RETURNING c.id
        )
        SELECT EXISTS(SELECT 1 FROM fence) AS fence_holds
        "#,
    )
    .bind(run_id)
    .bind(epoch.as_datetime())
    .bind(cohort_id.0)
    .fetch_one(pool)
    .await?;
    resolve_fence(probe, run_id, CompletionOperation::MarkCompleted)
}

/// Record a terminal supersede-by-reconcile outcome: markers short and the cohort diverged or was
/// deleted. An already-superseded participation keeps both its timestamp and its error, so a racing
/// edit's supersession — and the reason Django recorded for it — stays authoritative.
pub async fn record_participation_partial(
    pool: &PgPool,
    run_id: RunId,
    epoch: DispatchEpoch,
    cohort_id: CohortId,
    error: &RenderedError,
) -> Result<(), CompletionStoreError> {
    let probe = sqlx::query_scalar::<_, bool>(
        r#"
        WITH fence AS (
            SELECT id FROM cohort_backfill_runs
            WHERE id = $1 AND reconcile_dispatched_at = $2 AND status = 'reconciling'
            FOR UPDATE
        ), updated AS (
            UPDATE cohort_backfill_run_cohorts c
            SET superseded_at = COALESCE(c.superseded_at, now()),
                error = CASE WHEN c.superseded_at IS NULL THEN left($4, $5) ELSE c.error END
            FROM fence
            WHERE c.run_id = fence.id AND c.cohort_id = $3
            RETURNING c.id
        )
        SELECT EXISTS(SELECT 1 FROM fence) AS fence_holds
        "#,
    )
    .bind(run_id)
    .bind(epoch.as_datetime())
    .bind(cohort_id.0)
    .bind(error.as_str())
    .bind(PERSISTED_ERROR_LIMIT)
    .fetch_one(pool)
    .await?;
    resolve_fence(probe, run_id, CompletionOperation::RecordPartial)
}

/// Record a retryable shortfall: markers short but the hash still matches (a partially-gated fleet,
/// marker loss, allowlist shrink). Error only — `superseded_at` stays NULL so the run is
/// re-dispatchable.
pub async fn record_participation_shortfall(
    pool: &PgPool,
    run_id: RunId,
    epoch: DispatchEpoch,
    cohort_id: CohortId,
    error: &RenderedError,
) -> Result<(), CompletionStoreError> {
    let probe = sqlx::query_scalar::<_, bool>(
        r#"
        WITH fence AS (
            SELECT id FROM cohort_backfill_runs
            WHERE id = $1 AND reconcile_dispatched_at = $2 AND status = 'reconciling'
            FOR UPDATE
        ), updated AS (
            UPDATE cohort_backfill_run_cohorts c
            SET error = left($4, $5)
            FROM fence
            WHERE c.run_id = fence.id AND c.cohort_id = $3 AND c.superseded_at IS NULL
            RETURNING c.id
        )
        SELECT EXISTS(SELECT 1 FROM fence) AS fence_holds
        "#,
    )
    .bind(run_id)
    .bind(epoch.as_datetime())
    .bind(cohort_id.0)
    .bind(error.as_str())
    .bind(PERSISTED_ERROR_LIMIT)
    .fetch_one(pool)
    .await?;
    resolve_fence(probe, run_id, CompletionOperation::RecordShortfall)
}

/// Stamp `reconcile_observed_at` — the seeder's last write per dispatch cycle. Every
/// participation outcome is written before this, so Django never sees an observed run with an
/// undecided participation.
pub async fn mark_run_observed(
    pool: &PgPool,
    run_id: RunId,
    epoch: DispatchEpoch,
) -> Result<(), CompletionStoreError> {
    let updated = sqlx::query_scalar::<_, RunId>(
        r#"
        UPDATE cohort_backfill_runs
        SET reconcile_observed_at = now(), updated_at = now()
        WHERE id = $1 AND reconcile_dispatched_at = $2 AND status = 'reconciling'
        RETURNING id
        "#,
    )
    .bind(run_id)
    .bind(epoch.as_datetime())
    .fetch_optional(pool)
    .await?;
    fence(updated, run_id, CompletionOperation::MarkObserved)
}

/// Stamp `reconcile_observed_at` for a reconciling run that has nothing left to reconcile: every
/// participation was superseded while it was seeding, so "outcomes before observed" holds
/// vacuously and there is no dispatch to fence against. Without this the run would classify as
/// `ReconcilingUndispatched` on every tick forever — Django's finalizer only discovers runs that
/// carry `reconcile_observed_at`, and terminalizing an all-superseded run as `superseded` is
/// Django's transition to make. The `NOT EXISTS` guard is the fence: a run with an active
/// participation is never shortcut this way.
pub async fn mark_run_observed_unreconcilable(
    pool: &PgPool,
    run_id: RunId,
) -> Result<(), CompletionStoreError> {
    let updated = sqlx::query_scalar::<_, RunId>(
        r#"
        UPDATE cohort_backfill_runs
        SET reconcile_observed_at = now(), updated_at = now()
        WHERE id = $1 AND backfill_kind = 'behavioral' AND status = 'reconciling'
          AND NOT EXISTS (
              SELECT 1 FROM cohort_backfill_run_cohorts
              WHERE run_id = $1 AND superseded_at IS NULL
          )
        RETURNING id
        "#,
    )
    .bind(run_id)
    .fetch_optional(pool)
    .await?;
    fence(
        updated,
        run_id,
        CompletionOperation::MarkObservedUnreconcilable,
    )
}

/// One participation's observation state, seeding the per-run ledger and outcome fold.
#[derive(Debug, Clone)]
pub struct ObservationParticipation {
    pub cohort_id: CohortId,
    pub behavioral_filters_shape_hash: BehavioralShapeHash,
    pub bits: PartitionBitmap,
    pub reconcile_completed_at: Option<DateTime<Utc>>,
    pub superseded_at: Option<DateTime<Utc>>,
    pub stamped_at: Option<DateTime<Utc>>,
}

/// Load every participation's observation state for a run. Superseded rows are included so the
/// caller can let supersession trump completion.
pub async fn load_observation_participations(
    pool: &PgPool,
    run_id: RunId,
) -> Result<Vec<ObservationParticipation>, CompletionStoreError> {
    let rows = sqlx::query_as::<_, ObservationParticipationRow>(
        r#"
        SELECT cohort_id, behavioral_filters_shape_hash, reconcile_marker_bits,
               reconcile_completed_at, superseded_at, stamped_at
        FROM cohort_backfill_run_cohorts
        WHERE run_id = $1
        ORDER BY cohort_id
        "#,
    )
    .bind(run_id)
    .fetch_all(pool)
    .await?;

    let mut participations = Vec::with_capacity(rows.len());
    for row in rows {
        let cohort_id = CohortId(row.cohort_id);
        let bits = PartitionBitmap::from_bits(row.reconcile_marker_bits).map_err(|source| {
            CompletionStoreError::InvalidMarkerBits {
                run_id,
                cohort_id,
                source,
            }
        })?;
        let behavioral_filters_shape_hash =
            BehavioralShapeHash::parse(&row.behavioral_filters_shape_hash).map_err(|source| {
                CompletionStoreError::InvalidBehavioralShapeHash {
                    run_id,
                    cohort_id,
                    source,
                }
            })?;
        participations.push(ObservationParticipation {
            cohort_id,
            behavioral_filters_shape_hash,
            bits,
            reconcile_completed_at: row.reconcile_completed_at,
            superseded_at: row.superseded_at,
            stamped_at: row.stamped_at,
        });
    }
    Ok(participations)
}

/// The cohort's current behavioral shape, read from `posthog_cohort` to attribute a shortfall. An
/// absent row is treated as `Deleted`; a NULL or unparseable hash is `Indeterminate` (the caller
/// treats it as diverged).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CurrentBehavioralHash {
    Present(BehavioralShapeHash),
    Deleted,
    Indeterminate,
}

/// Read the current behavioral shape hash for each requested cohort. Cohorts with no row are absent
/// from the map, which the caller reads as [`CurrentBehavioralHash::Deleted`].
pub async fn load_current_behavioral_hashes(
    pool: &PgPool,
    team_id: TeamId,
    cohort_ids: &[CohortId],
) -> Result<HashMap<CohortId, CurrentBehavioralHash>, CompletionStoreError> {
    if cohort_ids.is_empty() {
        return Ok(HashMap::new());
    }
    let ids: Vec<i32> = cohort_ids.iter().map(|cohort| cohort.0).collect();
    let rows = sqlx::query_as::<_, CurrentCohortRow>(
        r#"
        SELECT id, behavioral_filters_shape_hash, deleted
        FROM posthog_cohort
        WHERE team_id = $1 AND id = ANY($2)
        "#,
    )
    .bind(team_id.0)
    .bind(ids)
    .fetch_all(pool)
    .await?;

    let mut current = HashMap::with_capacity(rows.len());
    for row in rows {
        let state = if row.deleted {
            CurrentBehavioralHash::Deleted
        } else {
            match row.behavioral_filters_shape_hash {
                Some(hash) => match BehavioralShapeHash::parse(&hash) {
                    Ok(hash) => CurrentBehavioralHash::Present(hash),
                    Err(_) => CurrentBehavioralHash::Indeterminate,
                },
                None => CurrentBehavioralHash::Indeterminate,
            }
        };
        current.insert(CohortId(row.id), state);
    }
    Ok(current)
}

/// Which of the candidate runs have a fully confirmed chunk ledger, in one round trip. The driver
/// ticks inside the orchestrator's poll arm ahead of its liveness heartbeat, so a per-run round trip
/// would scale one tick's cost with the seeding backlog.
pub async fn runs_with_all_chunks_confirmed(
    pool: &PgPool,
    run_ids: &[RunId],
) -> Result<HashSet<RunId>, CompletionStoreError> {
    if run_ids.is_empty() {
        return Ok(HashSet::new());
    }
    let ids = run_ids.iter().map(|run_id| run_id.0).collect::<Vec<_>>();
    let confirmed = sqlx::query_scalar::<_, RunId>(RUNS_WITH_ALL_CHUNKS_CONFIRMED)
        .bind(ids)
        .fetch_all(pool)
        .await?;
    Ok(confirmed.into_iter().collect())
}

/// A run discovered by the completion driver, already classified into its [`CompletionPhase`].
#[derive(Debug, Clone)]
pub struct DiscoveredCompletion {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub phase: CompletionPhase,
}

/// Discover every seeding/reconciling behavioral run and classify each. Rows whose status is not one
/// of the two the query selects are skipped defensively.
pub async fn discover_completions(
    pool: &PgPool,
    allowlist: &TeamAllowlist,
) -> Result<Vec<DiscoveredCompletion>, CompletionStoreError> {
    let rows = match allowlist {
        TeamAllowlist::All => {
            sqlx::query_as::<_, CompletionRunRow>(DISCOVER_COMPLETION_ALL)
                .fetch_all(pool)
                .await?
        }
        TeamAllowlist::Only(team_ids) => {
            let mut team_ids = team_ids.iter().copied().collect::<Vec<_>>();
            team_ids.sort_unstable();
            sqlx::query_as::<_, CompletionRunRow>(DISCOVER_COMPLETION_ONLY)
                .bind(team_ids)
                .fetch_all(pool)
                .await?
        }
    };
    Ok(rows.into_iter().filter_map(classify_row).collect())
}

fn classify_row(row: CompletionRunRow) -> Option<DiscoveredCompletion> {
    let status = match row.status.as_str() {
        "seeding" => CompletionStatus::Seeding,
        "reconciling" => CompletionStatus::Reconciling,
        _ => return None,
    };
    let phase = CompletionPhase::from_parts(CompletionParts {
        status,
        chunks_planned_at: row.chunks_planned_at,
        reconcile_dispatched_at: row.reconcile_dispatched_at,
        reconcile_observed_at: row.reconcile_observed_at,
        reconcile_hwms: row.reconcile_hwms.map(|json| json.0),
        marker_watch: row.marker_watch.map(|json| json.0),
    });
    Some(DiscoveredCompletion {
        run_id: row.id,
        team_id: TeamId(row.team_id),
        phase,
    })
}

fn fence(
    updated: Option<RunId>,
    run_id: RunId,
    operation: CompletionOperation,
) -> Result<(), CompletionStoreError> {
    updated
        .map(|_| ())
        .ok_or(CompletionStoreError::CompletionFenceLost { run_id, operation })
}

/// A fenced participation write probes only whether the run fence held: the data-modifying `updated`
/// CTE executes exactly once whether or not the outer query reads it, and a held fence whose guarded
/// UPDATE touched no row is a legitimate no-op (already completed, already superseded). Only a broken
/// fence is an error.
///
/// The fence CTE takes `FOR UPDATE` on the run row. Without it, under READ COMMITTED, the fence would
/// be evaluated against the statement's own snapshot: a concurrent [`ReconcilingClaim::record`] could
/// commit a re-dispatch after the fence read passed, the participation UPDATE would unblock, and
/// EvalPlanQual would re-check only the participation row's quals — landing a superseded epoch's
/// write inside the new epoch's regime while reporting success. Locking the run row makes the
/// re-check cover the epoch itself, so a stale write always surfaces as `CompletionFenceLost`.
fn resolve_fence(
    fence_holds: bool,
    run_id: RunId,
    operation: CompletionOperation,
) -> Result<(), CompletionStoreError> {
    if fence_holds {
        Ok(())
    } else {
        Err(CompletionStoreError::CompletionFenceLost { run_id, operation })
    }
}

#[derive(Debug, FromRow)]
struct ClaimRow {
    id: RunId,
    reconcile_dispatched_at: Option<DateTime<Utc>>,
}

impl ClaimRow {
    fn into_claim(self) -> ReconcilingClaim {
        ReconcilingClaim {
            run_id: self.id,
            dispatched_at_mint: self.reconcile_dispatched_at,
        }
    }
}

#[derive(Debug, FromRow)]
struct CompletionRunRow {
    id: RunId,
    team_id: i32,
    status: String,
    chunks_planned_at: Option<DateTime<Utc>>,
    reconcile_dispatched_at: Option<DateTime<Utc>>,
    reconcile_observed_at: Option<DateTime<Utc>>,
    reconcile_hwms: Option<Json<Value>>,
    marker_watch: Option<Json<Value>>,
}

#[derive(Debug, FromRow)]
struct ObservationParticipationRow {
    cohort_id: i32,
    behavioral_filters_shape_hash: String,
    reconcile_marker_bits: i64,
    reconcile_completed_at: Option<DateTime<Utc>>,
    superseded_at: Option<DateTime<Utc>>,
    stamped_at: Option<DateTime<Utc>>,
}

#[derive(Debug, FromRow)]
struct CurrentCohortRow {
    id: i32,
    behavioral_filters_shape_hash: Option<String>,
    deleted: bool,
}

#[cfg(test)]
mod tests {
    use crate::domain::ChunkStatus;
    use crate::store::runs::RunStatus;

    use super::*;

    #[test]
    fn hoisted_status_fragments_only_name_live_statuses() {
        for status in [seeding_status!(), reconciling_status!()] {
            assert!(
                status.trim_matches('\'').parse::<RunStatus>().is_ok(),
                "SQL fragment names non-vocabulary run status {status:?}"
            );
        }
        assert!(
            confirmed_chunk_status!()
                .trim_matches('\'')
                .parse::<ChunkStatus>()
                .is_ok(),
            "SQL fragment names a non-vocabulary chunk status"
        );
        // The composed queries must actually be built from the scanned fragments.
        assert!(CAS_RUN_RECONCILING.contains(confirmed_chunk_status!()));
        assert!(RUNS_WITH_ALL_CHUNKS_CONFIRMED.contains(confirmed_chunk_status!()));
        assert!(DISCOVER_COMPLETION_ALL.contains(seeding_status!()));
    }
}
