//! The day-chunk claim/CAS ledger in PostgreSQL: the sole owner of the `cohort_backfill_chunks` SQL.
//!
//! Written chunk statuses bind [`ChunkStatus::as_str`] as a parameter; the two multi-status `IN`
//! predicates are hoisted into [`ACTIVE_STATUSES_SQL`]/[`RETRYABLE_STATUSES_SQL`], scanned by a unit
//! test through [`ChunkStatus::from_str`] so the SQL vocabulary can never drift from the enum.
//! Every claim charges an attempt (saturating at the cap) and bumps the fencing `claim_epoch`;
//! expired `produced` leases are reclaimable without an attempt cap (their tiles are already in
//! Kafka and must reach `confirmed`), while expired `scanning` leases are capped and dead-lettered
//! by [`PgChunkStore::reap_poisoned_chunks`] so a chunk that hard-crashes its worker cannot
//! re-scan forever. Depends on `domain` (the pure chunk states it mints and the typed ids) and
//! nothing above.

use chrono::NaiveDate;
use cohort_core::filters::TeamId;
use cohort_core::{day_idx_of_naive_date, DayIdx};
use sqlx::types::Json;
use sqlx::{FromRow, PgPool};
use std::fmt;
use std::num::NonZeroU16;
use uuid::Uuid;

use crate::domain::{
    bands_for_day, Band, BandSpec, BandSpecError, ChunkId, ChunkLease, ChunkSpec, ChunkStatus,
    ClaimEpoch, ClaimKind, ClaimedChunk, EnqueuedChunk, Halted, ProduceHwms, ProducedChunk, RunId,
    SChunkMs, ScannedChunk,
};

use super::lease::LeaseHandle;
use super::{Claimant, LeaseDuration, MaxAttempts, RenderedError, PERSISTED_ERROR_LIMIT};

/// Chunk statuses holding a live lease — the targets of the fenced heartbeat/fail/confirm writes.
const ACTIVE_STATUSES_SQL: &str = "('scanning', 'produced')";
/// Chunk statuses eligible for a fresh claim while under the attempt cap.
const RETRYABLE_STATUSES_SQL: &str = "('pending', 'failed')";

#[derive(Debug, Clone)]
pub struct PgChunkStore {
    pool: PgPool,
}

impl PgChunkStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn plan_chunks(
        &self,
        run_id: RunId,
        days: impl IntoIterator<Item = DayIdx>,
        bands_per_day: NonZeroU16,
    ) -> Result<PlanOutcome, ChunkStoreError> {
        let mut ids = Vec::new();
        let mut dates = Vec::new();
        let mut bands = Vec::new();
        for day in days {
            let date = date_for_day(day).ok_or(ChunkStoreError::InvalidDay(day))?;
            for band in bands_for_day(day, bands_per_day) {
                ids.push(Uuid::now_v7());
                dates.push(date);
                bands.push(band.0);
            }
        }
        if ids.is_empty() {
            return Ok(PlanOutcome::Planned { inserted: 0 });
        }

        let result = sqlx::query_as::<_, PlanRow>(
            r#"
            WITH target_run AS (
                SELECT id, team_id
                FROM cohort_backfill_runs
                WHERE id = $1 AND status = 'seeding'
            ), input AS (
                SELECT * FROM unnest($2::uuid[], $3::date[], $4::smallint[]) AS u(id, day, band)
            ), inserted AS (
                INSERT INTO cohort_backfill_chunks
                    (id, run_id, team_id, day, band, status, claim_epoch, claimed_by, attempts,
                     last_error, tiles_produced, created_at, updated_at)
                SELECT u.id, r.id, r.team_id, u.day, u.band, $5, 0, '', 0, '', 0,
                       now(), now()
                FROM input u CROSS JOIN target_run r
                ON CONFLICT (run_id, day, band) DO NOTHING
                RETURNING id
            )
            SELECT EXISTS(SELECT 1 FROM target_run) AS run_seeding,
                   count(*)::bigint AS inserted
            FROM inserted
            "#,
        )
        .bind(run_id)
        .bind(ids)
        .bind(dates)
        .bind(bands)
        .bind(ChunkStatus::Pending.as_str())
        .fetch_one(&self.pool)
        .await?;
        if !result.run_seeding {
            return Ok(PlanOutcome::RunNotSeeding);
        }
        let inserted = u64::try_from(result.inserted)
            .map_err(|_| ChunkStoreError::InvalidInsertedCount(result.inserted))?;
        Ok(PlanOutcome::Planned { inserted })
    }

    pub async fn claim_next(
        &self,
        run_ids: &[RunId],
        claimant: &Claimant,
        lease: LeaseDuration,
        max_attempts: MaxAttempts,
    ) -> Result<Option<Claim>, ChunkStoreError> {
        if run_ids.is_empty() {
            return Ok(None);
        }
        let run_ids = run_ids.iter().map(|run_id| run_id.0).collect::<Vec<_>>();
        let sql = format!(
            r#"
            WITH next_chunk AS (
                SELECT c.id, c.status IN {active} AS was_reclaim
                FROM cohort_backfill_chunks c
                JOIN cohort_backfill_runs r ON r.id = c.run_id
                WHERE c.run_id = ANY($1) AND r.status = 'seeding'
                  AND ((c.status IN {retryable} AND c.attempts < $4)
                       OR (c.status = $6 AND c.lease_expires_at < now())
                       OR (c.status = $5 AND c.lease_expires_at < now() AND c.attempts < $4))
                ORDER BY c.day, c.band
                LIMIT 1
                FOR UPDATE OF c SKIP LOCKED
            )
            UPDATE cohort_backfill_chunks c
            SET status = $5, claim_epoch = c.claim_epoch + 1, claimed_by = $2,
                claimed_at = now(), lease_expires_at = now() + make_interval(secs => $3),
                s_chunk_at = now(),
                attempts = CASE WHEN c.attempts < $4 THEN c.attempts + 1 ELSE c.attempts END,
                updated_at = now()
            FROM next_chunk
            WHERE c.id = next_chunk.id
            RETURNING c.id, c.run_id, c.team_id, c.day, c.band, c.claim_epoch,
                      (extract(epoch FROM c.s_chunk_at) * 1000)::bigint AS s_chunk_ms,
                      (SELECT count(*) FROM cohort_backfill_chunks s
                       WHERE s.run_id = c.run_id AND s.day = c.day) AS num_bands,
                      next_chunk.was_reclaim
            "#,
            active = ACTIVE_STATUSES_SQL,
            retryable = RETRYABLE_STATUSES_SQL,
        );
        let row = sqlx::query_as::<_, ClaimedRow>(&sql)
            .bind(run_ids)
            .bind(claimant.as_str())
            .bind(lease.as_secs())
            .bind(max_attempts.get())
            .bind(ChunkStatus::Scanning.as_str())
            .bind(ChunkStatus::Produced.as_str())
            .fetch_optional(&self.pool)
            .await?;

        row.map(|row| self.assemble_claim(row, claimant, lease))
            .transpose()
    }

    /// Dead-letter `scanning` chunks whose lease expired at the attempt cap. A clean failure caps
    /// out through `fail` plus the claim gate, but a worker that dies without reaching `fail`
    /// (panic, OOM, SIGKILL) leaves its chunk `scanning`; once its attempts saturate, the claim
    /// predicate no longer reclaims it, and this sweep moves it to the same terminal `failed`
    /// state a clean cap-out reaches, so it surfaces to operators instead of stalling invisibly.
    /// Returns the number of chunks dead-lettered.
    pub async fn reap_poisoned_chunks(
        &self,
        run_ids: &[RunId],
        max_attempts: MaxAttempts,
    ) -> Result<u64, ChunkStoreError> {
        if run_ids.is_empty() {
            return Ok(0);
        }
        let run_ids = run_ids.iter().map(|run_id| run_id.0).collect::<Vec<_>>();
        let result = sqlx::query(
            r#"
            UPDATE cohort_backfill_chunks
            SET status = $3, last_error = left($4, $5), updated_at = now()
            WHERE run_id = ANY($1) AND status = $2
              AND lease_expires_at < now() AND attempts >= $6
            "#,
        )
        .bind(run_ids)
        .bind(ChunkStatus::Scanning.as_str())
        .bind(ChunkStatus::Failed.as_str())
        .bind("lease expired at the attempt cap without a clean failure; worker crash suspected")
        .bind(PERSISTED_ERROR_LIMIT)
        .bind(max_attempts.get())
        .execute(&self.pool)
        .await?;
        Ok(result.rows_affected())
    }

    pub async fn mark_produced(
        &self,
        chunk: ScannedChunk,
    ) -> Result<EnqueuedChunk, Halted<ScannedChunk, ChunkStoreError>> {
        let spec = chunk.spec();
        let tiles_produced = match u64::try_from(chunk.tiles().len()) {
            Ok(count) => count,
            Err(_) => {
                return Err(Halted::failed(
                    chunk,
                    ChunkStoreError::TilesProducedOutOfRange(u64::MAX),
                ));
            }
        };
        if let Err(error) = self.mark_produced_raw(spec.lease, tiles_produced).await {
            return Err(Halted::failed(chunk, error));
        }
        Ok(EnqueuedChunk::new(spec, tiles_produced))
    }

    pub async fn confirm(
        &self,
        chunk: ProducedChunk,
    ) -> Result<ChunkLease, Halted<ProducedChunk, ChunkStoreError>> {
        let spec = chunk.spec();
        if let Err(error) = self.confirm_raw(spec.lease, chunk.hwms()).await {
            return Err(Halted::failed(chunk, error));
        }
        Ok(spec.lease)
    }

    pub async fn fail(
        &self,
        lease: ChunkLease,
        error: &RenderedError,
    ) -> Result<(), ChunkStoreError> {
        let updated = sqlx::query_scalar::<_, ChunkId>(&format!(
            r#"
            UPDATE cohort_backfill_chunks
            SET status = $3, last_error = left($4, $5), updated_at = now()
            WHERE id = $1 AND claim_epoch = $2 AND status IN {active}
            RETURNING id
            "#,
            active = ACTIVE_STATUSES_SQL,
        ))
        .bind(lease.chunk_id())
        .bind(lease.epoch())
        .bind(ChunkStatus::Failed.as_str())
        .bind(error.as_str())
        .bind(PERSISTED_ERROR_LIMIT)
        .fetch_optional(&self.pool)
        .await?;
        fenced(updated, lease, ChunkOperation::Fail)
    }

    pub async fn unclaim(&self, lease: ChunkLease) -> Result<(), ChunkStoreError> {
        let updated = sqlx::query_scalar::<_, ChunkId>(
            r#"
            UPDATE cohort_backfill_chunks
            SET status = $3, claimed_by = '', claimed_at = NULL, lease_expires_at = NULL,
                attempts = GREATEST(attempts - 1, 0), updated_at = now()
            WHERE id = $1 AND claim_epoch = $2 AND status = 'scanning'
            RETURNING id
            "#,
        )
        .bind(lease.chunk_id())
        .bind(lease.epoch())
        .bind(ChunkStatus::Pending.as_str())
        .fetch_optional(&self.pool)
        .await?;
        fenced(updated, lease, ChunkOperation::Unclaim)
    }

    pub async fn remaining_chunks(&self, run_ids: &[RunId]) -> Result<u64, ChunkStoreError> {
        if run_ids.is_empty() {
            return Ok(0);
        }
        let run_ids = run_ids.iter().map(|run_id| run_id.0).collect::<Vec<_>>();
        let count: i64 = sqlx::query_scalar(
            r#"
            SELECT count(*)::bigint
            FROM cohort_backfill_chunks
            WHERE run_id = ANY($1) AND status <> $2
            "#,
        )
        .bind(run_ids)
        .bind(ChunkStatus::Confirmed.as_str())
        .fetch_one(&self.pool)
        .await?;
        u64::try_from(count).map_err(|_| ChunkStoreError::InvalidRemainingCount(count))
    }

    pub(crate) async fn heartbeat(
        &self,
        lease: ChunkLease,
        claimant: &Claimant,
        lease_duration: LeaseDuration,
    ) -> Result<(), ChunkStoreError> {
        let updated = sqlx::query_scalar::<_, ChunkId>(&format!(
            r#"
            UPDATE cohort_backfill_chunks c
            SET lease_expires_at = now() + make_interval(secs => $3), updated_at = now()
            FROM cohort_backfill_runs r
            WHERE c.id = $1 AND c.claim_epoch = $2 AND c.claimed_by = $4
              AND c.status IN {active}
              AND r.id = c.run_id AND r.status = 'seeding'
            RETURNING c.id
            "#,
            active = ACTIVE_STATUSES_SQL,
        ))
        .bind(lease.chunk_id())
        .bind(lease.epoch())
        .bind(lease_duration.as_secs())
        .bind(claimant.as_str())
        .fetch_optional(&self.pool)
        .await?;
        fenced(updated, lease, ChunkOperation::Heartbeat)
    }

    pub(crate) async fn mark_produced_raw(
        &self,
        lease: ChunkLease,
        tiles_produced: u64,
    ) -> Result<(), ChunkStoreError> {
        let tiles_produced = i64::try_from(tiles_produced)
            .map_err(|_| ChunkStoreError::TilesProducedOutOfRange(tiles_produced))?;
        let updated = sqlx::query_scalar::<_, ChunkId>(
            r#"
            UPDATE cohort_backfill_chunks
            SET status = $3, tiles_produced = $4, updated_at = now()
            WHERE id = $1 AND claim_epoch = $2 AND status = 'scanning'
            RETURNING id
            "#,
        )
        .bind(lease.chunk_id())
        .bind(lease.epoch())
        .bind(ChunkStatus::Produced.as_str())
        .bind(tiles_produced)
        .fetch_optional(&self.pool)
        .await?;
        fenced(updated, lease, ChunkOperation::MarkProduced)
    }

    pub(crate) async fn confirm_raw(
        &self,
        lease: ChunkLease,
        produce_hwms: &ProduceHwms,
    ) -> Result<(), ChunkStoreError> {
        let updated = sqlx::query_scalar::<_, ChunkId>(&format!(
            r#"
            UPDATE cohort_backfill_chunks
            SET status = $3, confirmed_at = now(), produce_hwms = $4, updated_at = now()
            WHERE id = $1 AND claim_epoch = $2 AND status IN {active}
            RETURNING id
            "#,
            active = ACTIVE_STATUSES_SQL,
        ))
        .bind(lease.chunk_id())
        .bind(lease.epoch())
        .bind(ChunkStatus::Confirmed.as_str())
        .bind(Json(produce_hwms))
        .fetch_optional(&self.pool)
        .await?;
        fenced(updated, lease, ChunkOperation::Confirm)
    }

    fn assemble_claim(
        &self,
        row: ClaimedRow,
        claimant: &Claimant,
        lease_duration: LeaseDuration,
    ) -> Result<Claim, ChunkStoreError> {
        let band = BandSpec::new(row.band.0, row.num_bands)?;
        let lease = ChunkLease::new(row.id, row.run_id, row.claim_epoch);
        let spec = ChunkSpec {
            lease,
            team_id: TeamId(row.team_id),
            day: day_idx_of_naive_date(row.day),
            band,
            s_chunk: SChunkMs(row.s_chunk_ms),
        };
        let handle = LeaseHandle::start(self.clone(), lease, claimant.clone(), lease_duration);
        Ok(Claim {
            chunk: ClaimedChunk::new(spec),
            kind: ClaimKind::from_was_reclaim(row.was_reclaim),
            lease: handle,
        })
    }
}

/// A freshly claimed chunk: its pure state, whether it was a reclaim (for the app's metric), and the
/// heartbeat handle to hold alongside it. Assembled entirely by the store — the pure state never
/// calls back into the store.
pub struct Claim {
    pub chunk: ClaimedChunk,
    pub kind: ClaimKind,
    pub lease: LeaseHandle,
}

/// The result of planning a run's day-chunks. `RunNotSeeding` is control flow (the run left the
/// `seeding` state between discovery and planning), not an error.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlanOutcome {
    Planned { inserted: u64 },
    RunNotSeeding,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChunkOperation {
    Heartbeat,
    MarkProduced,
    Confirm,
    Fail,
    Unclaim,
}

impl fmt::Display for ChunkOperation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Heartbeat => "heartbeat",
            Self::MarkProduced => "mark-produced",
            Self::Confirm => "confirm",
            Self::Fail => "fail",
            Self::Unclaim => "unclaim",
        })
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ChunkStoreError {
    #[error("PostgreSQL chunk operation failed")]
    Pg(#[from] sqlx::Error),
    #[error("chunk {lease:?} lost its lease during {operation}")]
    LeaseLost {
        lease: ChunkLease,
        operation: ChunkOperation,
    },
    #[error("tiles produced {0} exceeds PostgreSQL bigint range")]
    TilesProducedOutOfRange(u64),
    #[error("day index {0} is outside chrono's date range")]
    InvalidDay(DayIdx),
    #[error(transparent)]
    Band(#[from] BandSpecError),
    #[error("chunk planner returned invalid insert count {0}")]
    InvalidInsertedCount(i64),
    #[error("chunk counter returned invalid remaining count {0}")]
    InvalidRemainingCount(i64),
}

#[derive(Debug, FromRow)]
struct ClaimedRow {
    id: ChunkId,
    run_id: RunId,
    team_id: i32,
    day: NaiveDate,
    band: Band,
    claim_epoch: ClaimEpoch,
    s_chunk_ms: i64,
    num_bands: i64,
    was_reclaim: bool,
}

#[derive(Debug, FromRow)]
struct PlanRow {
    run_seeding: bool,
    inserted: i64,
}

fn fenced(
    updated: Option<ChunkId>,
    lease: ChunkLease,
    operation: ChunkOperation,
) -> Result<(), ChunkStoreError> {
    updated
        .map(|_| ())
        .ok_or(ChunkStoreError::LeaseLost { lease, operation })
}

fn date_for_day(day: DayIdx) -> Option<NaiveDate> {
    let epoch = NaiveDate::from_ymd_opt(1970, 1, 1)?;
    epoch.checked_add_signed(chrono::Duration::days(i64::from(day)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hoisted_status_fragments_only_name_live_chunk_statuses() {
        for fragment in [ACTIVE_STATUSES_SQL, RETRYABLE_STATUSES_SQL] {
            let statuses = fragment
                .trim_matches(|c| c == '(' || c == ')')
                .split(',')
                .map(|token| token.trim().trim_matches('\''));
            for status in statuses {
                assert!(
                    status.parse::<ChunkStatus>().is_ok(),
                    "SQL fragment names non-vocabulary status {status:?}"
                );
            }
        }
    }
}
