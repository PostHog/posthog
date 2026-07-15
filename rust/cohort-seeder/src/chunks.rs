use std::collections::BTreeMap;
use std::fmt;
use std::num::NonZeroU32;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use chrono::NaiveDate;
use cohort_core::filters::TeamId;
use cohort_core::stage1::bucket_tz::day_idx_of_naive_date;
use metrics::counter;
use serde::{Deserialize, Serialize};
use sqlx::types::Json;
use sqlx::{FromRow, PgPool};
use tokio::sync::Notify;
use tokio::task::{AbortHandle, JoinError, JoinHandle};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

use crate::domain::{DomainError, SeedDomain};
use crate::ids::{Band, ChunkId, ClaimEpoch, DayIdx, RunId, SChunkMs};
use crate::observability::metrics::{CHUNKS_RECLAIMED, LEASE_HEARTBEATS, LEASE_LOST};
use crate::pinned::PinnedRun;
use crate::scan::ScanError;
use crate::tile::SeedTile;

#[derive(Debug, Clone)]
pub struct ChunkStore {
    pool: PgPool,
}

impl ChunkStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub fn pool(&self) -> &PgPool {
        &self.pool
    }

    pub async fn plan_chunks(
        &self,
        run_id: RunId,
        days: impl IntoIterator<Item = DayIdx>,
    ) -> Result<u64, ChunkError> {
        let mut ids = Vec::new();
        let mut dates = Vec::new();
        let mut bands = Vec::new();
        for day in days {
            let date = date_for_day(day).ok_or(ChunkError::InvalidDay(day))?;
            for band in bands_for_day(day) {
                ids.push(Uuid::now_v7());
                dates.push(date);
                bands.push(band.0);
            }
        }
        if ids.is_empty() {
            return Ok(0);
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
                SELECT u.id, r.id, r.team_id, u.day, u.band, 'pending', 0, '', 0, '', 0,
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
        .fetch_one(&self.pool)
        .await?;
        if !result.run_seeding {
            return Err(ChunkError::RunNotSeeding(run_id));
        }
        u64::try_from(result.inserted)
            .map_err(|_| ChunkError::InvalidInsertedCount(result.inserted))
    }

    pub async fn claim_next(
        &self,
        run_ids: &[RunId],
        claimed_by: &str,
        lease_duration: Duration,
        max_attempts: u32,
    ) -> Result<Option<ClaimedChunk>, ChunkError> {
        if run_ids.is_empty() {
            return Ok(None);
        }
        validate_claimant(claimed_by)?;
        let lease_secs = duration_seconds(lease_duration)?;
        let max_attempts = i32::try_from(max_attempts)
            .map_err(|_| ChunkError::AttemptsOutOfRange(max_attempts))?;
        let run_ids = run_ids.iter().map(|run_id| run_id.0).collect::<Vec<_>>();
        let row = sqlx::query_as::<_, ClaimedRow>(
            r#"
            WITH next_chunk AS (
                SELECT c.id, c.status IN ('scanning', 'produced') AS was_reclaim
                FROM cohort_backfill_chunks c
                JOIN cohort_backfill_runs r ON r.id = c.run_id
                WHERE c.run_id = ANY($1) AND r.status = 'seeding'
                  AND ((c.status IN ('pending', 'failed') AND c.attempts < $4)
                       OR (c.status IN ('scanning', 'produced') AND c.lease_expires_at < now()))
                ORDER BY c.day, c.band
                LIMIT 1
                FOR UPDATE OF c SKIP LOCKED
            )
            UPDATE cohort_backfill_chunks c
            SET status = 'scanning', claim_epoch = c.claim_epoch + 1, claimed_by = $2,
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
        )
        .bind(run_ids)
        .bind(claimed_by)
        .bind(lease_secs)
        .bind(max_attempts)
        .fetch_optional(&self.pool)
        .await?;

        row.map(|row| {
            if row.was_reclaim {
                counter!(CHUNKS_RECLAIMED).increment(1);
            }
            self.claimed_chunk(row, claimed_by, lease_duration)
        })
        .transpose()
    }

    pub async fn remaining_chunks(&self, run_ids: &[RunId]) -> Result<u64, ChunkError> {
        if run_ids.is_empty() {
            return Ok(0);
        }
        let run_ids = run_ids.iter().map(|run_id| run_id.0).collect::<Vec<_>>();
        let count: i64 = sqlx::query_scalar(
            r#"
            SELECT count(*)::bigint
            FROM cohort_backfill_chunks
            WHERE run_id = ANY($1) AND status <> 'confirmed'
            "#,
        )
        .bind(run_ids)
        .fetch_one(&self.pool)
        .await?;
        u64::try_from(count).map_err(|_| ChunkError::InvalidRemainingCount(count))
    }

    async fn heartbeat(
        &self,
        lease: ChunkLease,
        claimed_by: &str,
        lease_duration: Duration,
    ) -> Result<(), ChunkError> {
        let lease_secs = duration_seconds(lease_duration)?;
        let updated = sqlx::query_scalar::<_, ChunkId>(
            r#"
            UPDATE cohort_backfill_chunks c
            SET lease_expires_at = now() + make_interval(secs => $3), updated_at = now()
            FROM cohort_backfill_runs r
            WHERE c.id = $1 AND c.claim_epoch = $2 AND c.claimed_by = $4
              AND c.status IN ('scanning', 'produced')
              AND r.id = c.run_id AND r.status = 'seeding'
            RETURNING c.id
            "#,
        )
        .bind(lease.chunk_id)
        .bind(lease.epoch)
        .bind(lease_secs)
        .bind(claimed_by)
        .fetch_optional(&self.pool)
        .await?;
        fenced(updated, lease, ChunkOperation::Heartbeat)
    }

    #[allow(dead_code)]
    async fn mark_produced(
        &self,
        lease: ChunkLease,
        tiles_produced: u64,
    ) -> Result<(), ChunkError> {
        let tiles_produced = i64::try_from(tiles_produced)
            .map_err(|_| ChunkError::TilesProducedOutOfRange(tiles_produced))?;
        let updated = sqlx::query_scalar::<_, ChunkId>(
            r#"
            UPDATE cohort_backfill_chunks
            SET status = 'produced', tiles_produced = $3, updated_at = now()
            WHERE id = $1 AND claim_epoch = $2 AND status = 'scanning'
            RETURNING id
            "#,
        )
        .bind(lease.chunk_id)
        .bind(lease.epoch)
        .bind(tiles_produced)
        .fetch_optional(&self.pool)
        .await?;
        fenced(updated, lease, ChunkOperation::MarkProduced)
    }

    async fn confirm(
        &self,
        lease: ChunkLease,
        produce_hwms: &ProduceHwms,
    ) -> Result<(), ChunkError> {
        let updated = sqlx::query_scalar::<_, ChunkId>(
            r#"
            UPDATE cohort_backfill_chunks
            SET status = 'confirmed', confirmed_at = now(), produce_hwms = $3, updated_at = now()
            WHERE id = $1 AND claim_epoch = $2 AND status IN ('scanning', 'produced')
            RETURNING id
            "#,
        )
        .bind(lease.chunk_id)
        .bind(lease.epoch)
        .bind(Json(produce_hwms))
        .fetch_optional(&self.pool)
        .await?;
        fenced(updated, lease, ChunkOperation::Confirm)
    }

    async fn fail_chunk(&self, lease: ChunkLease, error: &str) -> Result<(), ChunkError> {
        let updated = sqlx::query_scalar::<_, ChunkId>(
            r#"
            UPDATE cohort_backfill_chunks
            SET status = 'failed', last_error = left($3, 4096), updated_at = now()
            WHERE id = $1 AND claim_epoch = $2 AND status IN ('scanning', 'produced')
            RETURNING id
            "#,
        )
        .bind(lease.chunk_id)
        .bind(lease.epoch)
        .bind(error)
        .fetch_optional(&self.pool)
        .await?;
        fenced(updated, lease, ChunkOperation::Fail)
    }

    async fn unclaim(&self, lease: ChunkLease) -> Result<(), ChunkError> {
        let updated = sqlx::query_scalar::<_, ChunkId>(
            r#"
            UPDATE cohort_backfill_chunks
            SET status = 'pending', claimed_by = '', claimed_at = NULL, lease_expires_at = NULL,
                attempts = GREATEST(attempts - 1, 0), updated_at = now()
            WHERE id = $1 AND claim_epoch = $2 AND status = 'scanning'
            RETURNING id
            "#,
        )
        .bind(lease.chunk_id)
        .bind(lease.epoch)
        .fetch_optional(&self.pool)
        .await?;
        fenced(updated, lease, ChunkOperation::Unclaim)
    }

    fn claimed_chunk(
        &self,
        row: ClaimedRow,
        claimed_by: &str,
        lease_duration: Duration,
    ) -> Result<ClaimedChunk, ChunkError> {
        let num_bands = u32::try_from(row.num_bands)
            .ok()
            .and_then(NonZeroU32::new)
            .ok_or(ChunkError::InvalidBandCount(row.num_bands))?;
        let identity = ClaimIdentity {
            lease: ChunkLease {
                chunk_id: row.id,
                run_id: row.run_id,
                epoch: row.claim_epoch,
            },
            claimed_by: claimed_by.to_string(),
        };
        let guard = LeaseGuard::start(self.clone(), identity.clone(), lease_duration);
        Ok(ClaimedChunk {
            store: self.clone(),
            identity,
            team_id: TeamId(row.team_id),
            day: day_idx_of_naive_date(row.day),
            band: row.band,
            num_bands,
            s_chunk: SChunkMs(row.s_chunk_ms),
            guard,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ChunkLease {
    chunk_id: ChunkId,
    run_id: RunId,
    epoch: ClaimEpoch,
}

impl ChunkLease {
    pub const fn chunk_id(self) -> ChunkId {
        self.chunk_id
    }

    pub const fn run_id(self) -> RunId {
        self.run_id
    }

    pub const fn epoch(self) -> ClaimEpoch {
        self.epoch
    }
}

#[derive(Debug, Clone)]
struct ClaimIdentity {
    lease: ChunkLease,
    claimed_by: String,
}

pub struct ClaimedChunk {
    store: ChunkStore,
    identity: ClaimIdentity,
    team_id: TeamId,
    day: DayIdx,
    band: Band,
    num_bands: NonZeroU32,
    s_chunk: SChunkMs,
    guard: LeaseGuard,
}

impl fmt::Debug for ClaimedChunk {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ClaimedChunk")
            .field("identity", &self.identity)
            .field("team_id", &self.team_id)
            .field("day", &self.day)
            .field("band", &self.band)
            .field("num_bands", &self.num_bands)
            .field("s_chunk", &self.s_chunk)
            .finish_non_exhaustive()
    }
}

impl ClaimedChunk {
    pub const fn lease(&self) -> ChunkLease {
        self.identity.lease
    }

    pub fn claimed_by(&self) -> &str {
        &self.identity.claimed_by
    }

    pub const fn team_id(&self) -> TeamId {
        self.team_id
    }

    pub const fn day(&self) -> DayIdx {
        self.day
    }

    pub const fn band(&self) -> Band {
        self.band
    }

    pub const fn num_bands(&self) -> NonZeroU32 {
        self.num_bands
    }

    pub const fn s_chunk(&self) -> SChunkMs {
        self.s_chunk
    }

    pub fn cancellation_token(&self) -> CancellationToken {
        self.guard.cancellation_token()
    }

    pub async fn lease_failure(&self) -> LeaseFailure {
        self.guard.failure.wait().await
    }

    pub fn domain(&self, run: &PinnedRun) -> Result<SeedDomain, ChunkError> {
        if run.run_id != self.identity.lease.run_id || run.team_id != self.team_id {
            return Err(ChunkError::RunMismatch {
                chunk_run_id: self.identity.lease.run_id,
                chunk_team_id: self.team_id.0,
                pinned_run_id: run.run_id,
                pinned_team_id: run.team_id.0,
            });
        }
        Ok(SeedDomain::new(
            self.day,
            run.boundary,
            run.tz,
            self.s_chunk,
        )?)
    }

    pub async fn heartbeat_now(&self, lease_duration: Duration) -> Result<(), ChunkError> {
        self.store
            .heartbeat(
                self.identity.lease,
                &self.identity.claimed_by,
                lease_duration,
            )
            .await
    }

    pub async fn fail(self, error: &str) -> Result<(), ChunkError> {
        self.store.fail_chunk(self.identity.lease, error).await
    }

    pub async fn unclaim(self) -> Result<(), ChunkError> {
        self.store.unclaim(self.identity.lease).await
    }

    #[allow(dead_code)]
    pub(crate) fn finish_scan(self, tiles: Vec<SeedTile>) -> ScannedChunk {
        ScannedChunk { chunk: self, tiles }
    }
}

pub struct ScannedChunk {
    chunk: ClaimedChunk,
    tiles: Vec<SeedTile>,
}

impl fmt::Debug for ScannedChunk {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ScannedChunk")
            .field("chunk", &self.chunk)
            .field("tiles", &self.tiles.len())
            .finish()
    }
}

impl ScannedChunk {
    pub const fn lease(&self) -> ChunkLease {
        self.chunk.lease()
    }

    pub fn tiles(&self) -> &[SeedTile] {
        &self.tiles
    }

    pub fn cancellation_token(&self) -> CancellationToken {
        self.chunk.cancellation_token()
    }

    pub async fn lease_failure(&self) -> LeaseFailure {
        self.chunk.lease_failure().await
    }

    pub(crate) async fn mark_enqueued(
        self,
    ) -> Result<EnqueuedChunk, StateTransitionFailure<ScannedChunk>> {
        let tiles_produced = match u64::try_from(self.tiles.len()) {
            Ok(count) => count,
            Err(_) => {
                return Err(StateTransitionFailure::new(
                    self,
                    ChunkError::TilesProducedOutOfRange(u64::MAX),
                ));
            }
        };
        if let Err(source) = self
            .chunk
            .store
            .mark_produced(self.chunk.identity.lease, tiles_produced)
            .await
        {
            return Err(StateTransitionFailure::new(self, source));
        }
        Ok(EnqueuedChunk {
            chunk: self.chunk,
            tiles_produced,
        })
    }

    pub async fn fail(self, error: &str) -> Result<(), ChunkError> {
        self.chunk.fail(error).await
    }

    pub async fn unclaim(self) -> Result<(), ChunkError> {
        self.chunk.unclaim().await
    }
}

pub struct EnqueuedChunk {
    chunk: ClaimedChunk,
    tiles_produced: u64,
}

impl fmt::Debug for EnqueuedChunk {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("EnqueuedChunk")
            .field("chunk", &self.chunk)
            .field("tiles_produced", &self.tiles_produced)
            .finish()
    }
}

impl EnqueuedChunk {
    pub const fn lease(&self) -> ChunkLease {
        self.chunk.lease()
    }

    pub fn cancellation_token(&self) -> CancellationToken {
        self.chunk.cancellation_token()
    }

    pub async fn lease_failure(&self) -> LeaseFailure {
        self.chunk.lease_failure().await
    }

    pub(crate) fn finish_deliveries(self, produce_hwms: ProduceHwms) -> ProducedChunk {
        ProducedChunk {
            chunk: self.chunk,
            tiles_produced: self.tiles_produced,
            produce_hwms,
        }
    }

    pub async fn fail(self, error: &str) -> Result<(), ChunkError> {
        self.chunk.fail(error).await
    }
}

pub struct ProducedChunk {
    chunk: ClaimedChunk,
    tiles_produced: u64,
    produce_hwms: ProduceHwms,
}

impl fmt::Debug for ProducedChunk {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProducedChunk")
            .field("chunk", &self.chunk)
            .field("tiles_produced", &self.tiles_produced)
            .field("produce_hwms", &self.produce_hwms)
            .finish()
    }
}

impl ProducedChunk {
    pub const fn lease(&self) -> ChunkLease {
        self.chunk.lease()
    }

    pub const fn tiles_produced(&self) -> u64 {
        self.tiles_produced
    }

    pub fn produce_hwms(&self) -> &ProduceHwms {
        &self.produce_hwms
    }

    pub fn cancellation_token(&self) -> CancellationToken {
        self.chunk.cancellation_token()
    }

    pub async fn lease_failure(&self) -> LeaseFailure {
        self.chunk.lease_failure().await
    }

    pub async fn confirm(self) -> Result<(), StateTransitionFailure<ProducedChunk>> {
        if let Err(source) = self
            .chunk
            .store
            .confirm(self.chunk.identity.lease, &self.produce_hwms)
            .await
        {
            return Err(StateTransitionFailure::new(self, source));
        }
        Ok(())
    }

    pub async fn fail(self, error: &str) -> Result<(), ChunkError> {
        self.chunk.fail(error).await
    }
}

pub struct StateTransitionFailure<S> {
    state: S,
    source: ChunkError,
}

impl<S> StateTransitionFailure<S> {
    fn new(state: S, source: ChunkError) -> Self {
        Self { state, source }
    }

    pub fn state(&self) -> &S {
        &self.state
    }

    pub fn error(&self) -> &ChunkError {
        &self.source
    }

    pub fn into_parts(self) -> (S, ChunkError) {
        (self.state, self.source)
    }
}

impl<S: fmt::Debug> fmt::Debug for StateTransitionFailure<S> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("StateTransitionFailure")
            .field("state", &self.state)
            .field("source", &self.source)
            .finish()
    }
}

impl<S> fmt::Display for StateTransitionFailure<S> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.source.fmt(formatter)
    }
}

impl<S: fmt::Debug> std::error::Error for StateTransitionFailure<S> {}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ProduceHwms(BTreeMap<i32, i64>);

impl ProduceHwms {
    pub fn observe(&mut self, partition: i32, offset: i64) {
        self.0
            .entry(partition)
            .and_modify(|current| *current = (*current).max(offset))
            .or_insert(offset);
    }

    pub fn merge(&mut self, other: Self) {
        for (partition, offset) in other.0 {
            self.observe(partition, offset);
        }
    }

    pub fn get(&self, partition: i32) -> Option<i64> {
        self.0.get(&partition).copied()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

#[doc(hidden)]
#[cfg(feature = "pg-test-support")]
pub mod pg_test_support {
    use super::*;

    pub async fn heartbeat(
        store: &ChunkStore,
        lease: ChunkLease,
        claimed_by: &str,
        lease_duration: Duration,
    ) -> Result<(), ChunkError> {
        store.heartbeat(lease, claimed_by, lease_duration).await
    }

    pub async fn mark_produced(
        store: &ChunkStore,
        lease: ChunkLease,
        tiles_produced: u64,
    ) -> Result<(), ChunkError> {
        store.mark_produced(lease, tiles_produced).await
    }

    pub async fn confirm(
        store: &ChunkStore,
        lease: ChunkLease,
        produce_hwms: &ProduceHwms,
    ) -> Result<(), ChunkError> {
        store.confirm(lease, produce_hwms).await
    }

    pub async fn fail(
        store: &ChunkStore,
        lease: ChunkLease,
        error: &str,
    ) -> Result<(), ChunkError> {
        store.fail_chunk(lease, error).await
    }

    pub async fn unclaim(store: &ChunkStore, lease: ChunkLease) -> Result<(), ChunkError> {
        store.unclaim(lease).await
    }
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
pub enum ChunkError {
    #[error("PostgreSQL chunk operation failed: {0}")]
    Pg(#[from] sqlx::Error),
    #[error(transparent)]
    Domain(#[from] DomainError),
    #[error(transparent)]
    Scan(#[from] ScanError),
    #[error("chunk {lease:?} lost its lease during {operation}")]
    LeaseLost {
        lease: ChunkLease,
        operation: ChunkOperation,
    },
    #[error("claimant must contain 1 to 255 bytes")]
    InvalidClaimant,
    #[error("chunk lease must be at least one second")]
    InvalidLeaseDuration,
    #[error("maximum attempts {0} exceeds PostgreSQL integer range")]
    AttemptsOutOfRange(u32),
    #[error("tiles produced {0} exceeds PostgreSQL bigint range")]
    TilesProducedOutOfRange(u64),
    #[error("day index {0} is outside chrono's date range")]
    InvalidDay(DayIdx),
    #[error("claimed chunk reported invalid band count {0}")]
    InvalidBandCount(i64),
    #[error("run {0:?} is not seeding")]
    RunNotSeeding(RunId),
    #[error("chunk planner returned invalid insert count {0}")]
    InvalidInsertedCount(i64),
    #[error("chunk counter returned invalid remaining count {0}")]
    InvalidRemainingCount(i64),
    #[error(
        "chunk run/team ({chunk_run_id:?}, {chunk_team_id}) does not match pinned run/team ({pinned_run_id:?}, {pinned_team_id})"
    )]
    RunMismatch {
        chunk_run_id: RunId,
        chunk_team_id: i32,
        pinned_run_id: RunId,
        pinned_team_id: i32,
    },
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

struct LeaseGuard {
    cancel: CancellationToken,
    failure: LeaseFailureSignal,
    worker_abort: AbortHandle,
    supervisor: JoinHandle<()>,
}

impl LeaseGuard {
    fn start(store: ChunkStore, identity: ClaimIdentity, lease_duration: Duration) -> Self {
        let cancel = CancellationToken::new();
        let worker_cancel = cancel.clone();
        let worker = tokio::spawn(async move {
            let _cancel_on_exit = CancelOnDrop(worker_cancel.clone());
            let heartbeat_interval = (lease_duration / 3).max(Duration::from_secs(1));
            let mut ticker = tokio::time::interval(heartbeat_interval);
            ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
            ticker.tick().await;
            loop {
                tokio::select! {
                    biased;
                    _ = worker_cancel.cancelled() => return Ok(()),
                    _ = ticker.tick() => {
                        let heartbeat = store
                            .heartbeat(identity.lease, &identity.claimed_by, lease_duration)
                            .await;
                        match heartbeat {
                            Ok(()) => counter!(LEASE_HEARTBEATS).increment(1),
                            Err(error) => {
                                counter!(LEASE_LOST).increment(1);
                                return Err(error);
                            }
                        }
                    }
                }
            }
        });
        Self::supervise(cancel, worker)
    }

    fn supervise(cancel: CancellationToken, worker: JoinHandle<Result<(), ChunkError>>) -> Self {
        let worker_abort = worker.abort_handle();
        let failure = LeaseFailureSignal::new();
        let failure_state = Arc::clone(&failure.state);
        let supervisor = tokio::spawn(async move {
            match worker.await {
                Ok(Ok(())) => {}
                Ok(Err(error)) => {
                    failure_state.publish(LeaseFailure::Heartbeat(error));
                }
                Err(error) => {
                    failure_state.publish(LeaseFailure::Task(error));
                }
            }
        });
        Self {
            cancel,
            failure,
            worker_abort,
            supervisor,
        }
    }

    fn cancellation_token(&self) -> CancellationToken {
        self.cancel.child_token()
    }
}

impl Drop for LeaseGuard {
    fn drop(&mut self) {
        self.cancel.cancel();
        self.worker_abort.abort();
        self.supervisor.abort();
    }
}

#[derive(Debug, thiserror::Error)]
pub enum LeaseFailure {
    #[error("lease heartbeat failed: {0}")]
    Heartbeat(ChunkError),
    #[error("lease heartbeat task failed: {0}")]
    Task(JoinError),
}

struct LeaseFailureState {
    failure: Mutex<Option<LeaseFailure>>,
    notify: Notify,
}

impl LeaseFailureState {
    fn publish(&self, failure: LeaseFailure) {
        *self
            .failure
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(failure);
        self.notify.notify_one();
    }
}

pub struct LeaseFailureSignal {
    state: Arc<LeaseFailureState>,
}

impl LeaseFailureSignal {
    fn new() -> Self {
        Self {
            state: Arc::new(LeaseFailureState {
                failure: Mutex::new(None),
                notify: Notify::new(),
            }),
        }
    }

    pub async fn wait(&self) -> LeaseFailure {
        loop {
            let notified = self.state.notify.notified();
            if let Some(failure) = self
                .state
                .failure
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take()
            {
                return failure;
            }
            notified.await;
        }
    }
}

struct CancelOnDrop(CancellationToken);

impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        self.0.cancel();
    }
}

pub fn bands_for_day(_day: DayIdx) -> Vec<Band> {
    vec![Band(0)]
}

fn fenced(
    updated: Option<ChunkId>,
    lease: ChunkLease,
    operation: ChunkOperation,
) -> Result<(), ChunkError> {
    updated
        .map(|_| ())
        .ok_or(ChunkError::LeaseLost { lease, operation })
}

fn validate_claimant(claimed_by: &str) -> Result<(), ChunkError> {
    if claimed_by.is_empty() || claimed_by.len() > 255 {
        return Err(ChunkError::InvalidClaimant);
    }
    Ok(())
}

fn duration_seconds(duration: Duration) -> Result<i64, ChunkError> {
    if duration < Duration::from_secs(1) {
        return Err(ChunkError::InvalidLeaseDuration);
    }
    i64::try_from(duration.as_secs()).map_err(|_| ChunkError::InvalidLeaseDuration)
}

fn date_for_day(day: DayIdx) -> Option<NaiveDate> {
    let epoch = NaiveDate::from_ymd_opt(1970, 1, 1)?;
    epoch.checked_add_signed(chrono::Duration::days(i64::from(day)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn produce_hwms_fold_by_partition_maximum() {
        let mut hwms = ProduceHwms::default();
        hwms.observe(2, 9);
        hwms.observe(1, 4);
        hwms.observe(2, 7);
        let mut later = ProduceHwms::default();
        later.observe(1, 11);
        later.observe(3, 1);
        hwms.merge(later);

        assert_eq!(hwms.get(1), Some(11));
        assert_eq!(hwms.get(2), Some(9));
        assert_eq!(hwms.get(3), Some(1));
        assert_eq!(
            serde_json::to_value(hwms).unwrap(),
            serde_json::json!({"1": 11, "2": 9, "3": 1})
        );
    }

    #[tokio::test]
    async fn lease_guard_surfaces_task_panics_and_cancels() {
        let cancel = CancellationToken::new();
        let worker_cancel = cancel.clone();
        let worker: JoinHandle<Result<(), ChunkError>> = tokio::spawn(async move {
            let _cancel_on_exit = CancelOnDrop(worker_cancel);
            panic!("heartbeat panic")
        });
        let guard = LeaseGuard::supervise(cancel.clone(), worker);

        let failure = tokio::time::timeout(Duration::from_secs(1), guard.failure.wait())
            .await
            .unwrap();
        assert!(matches!(failure, LeaseFailure::Task(error) if error.is_panic()));
        assert!(cancel.is_cancelled());
    }
}
