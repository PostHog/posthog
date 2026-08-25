//! Feature-gated (`pg-test-support`) test hooks: mint pure chunk states without a claim, and drive
//! the store's lease-fenced SQL directly by [`ChunkLease`] so the integration test can exercise the
//! epoch fence in isolation. Not compiled into the shipping binary.

use chrono::{DateTime, Utc};
use sqlx::PgPool;

use crate::domain::{
    ChunkLease, ChunkSpec, ClaimedChunk, DispatchEpoch, ProduceHwms, RunId, ScannedChunk, SeedTile,
};
use crate::store::chunks::{ChunkStoreError, PgChunkStore};
use crate::store::{Claimant, LeaseDuration, RenderedError};

pub fn claimed(spec: ChunkSpec) -> ClaimedChunk {
    ClaimedChunk::new(spec)
}

pub fn scanned(spec: ChunkSpec, tiles: Vec<SeedTile>) -> ScannedChunk {
    ScannedChunk::new(spec, tiles)
}

pub async fn heartbeat(
    store: &PgChunkStore,
    lease: ChunkLease,
    claimant: &Claimant,
    lease_duration: LeaseDuration,
) -> Result<(), ChunkStoreError> {
    store.heartbeat(lease, claimant, lease_duration).await
}

pub async fn mark_produced_raw(
    store: &PgChunkStore,
    lease: ChunkLease,
    tiles_produced: u64,
) -> Result<(), ChunkStoreError> {
    store.mark_produced_raw(lease, tiles_produced).await
}

pub async fn confirm_raw(
    store: &PgChunkStore,
    lease: ChunkLease,
    hwms: &ProduceHwms,
) -> Result<(), ChunkStoreError> {
    store.confirm_raw(lease, hwms).await
}

pub async fn fail(
    store: &PgChunkStore,
    lease: ChunkLease,
    error: &str,
) -> Result<(), ChunkStoreError> {
    store.fail(lease, &RenderedError::from_message(error)).await
}

pub async fn unclaim(store: &PgChunkStore, lease: ChunkLease) -> Result<(), ChunkStoreError> {
    store.unclaim(lease).await
}

/// Read a run's current dispatch fence epoch. Integration tests cannot mint a [`DispatchEpoch`]
/// (its constructor is `pub(crate)`), so this feature-gated hook hands them the live one.
pub async fn dispatch_epoch(pool: &PgPool, run_id: RunId) -> Result<DispatchEpoch, sqlx::Error> {
    let at: DateTime<Utc> = sqlx::query_scalar(
        "SELECT reconcile_dispatched_at FROM cohort_backfill_runs WHERE id = $1",
    )
    .bind(run_id)
    .fetch_one(pool)
    .await?;
    Ok(DispatchEpoch::from_dispatched_at(at))
}

/// Mint an arbitrary dispatch epoch from a timestamp — the way a test constructs a deliberately
/// stale fence value.
pub fn epoch_at(at: DateTime<Utc>) -> DispatchEpoch {
    DispatchEpoch::from_dispatched_at(at)
}
