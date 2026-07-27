//! Feature-gated (`pg-test-support`) test hooks: mint pure chunk states without a claim, and drive
//! the store's lease-fenced SQL directly by [`ChunkLease`] so the integration test can exercise the
//! epoch fence in isolation. Not compiled into the shipping binary.

use crate::domain::{ChunkLease, ChunkSpec, ClaimedChunk, ProduceHwms, ScannedChunk, SeedTile};
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
