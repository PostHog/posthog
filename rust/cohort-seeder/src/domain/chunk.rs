//! Pure chunk typestates and vocabulary; depends only on `cohort-core` and sibling domain modules.
//!
//! The states hold data only — no pool, no store handle, no lease. DB-effecting transitions are
//! minted exclusively by [`crate::store::chunks`]; the pure transitions here consume `self`. This is
//! what makes "a chunk cannot be produced twice or confirmed unscanned" a compile-time property.

use std::collections::BTreeMap;
use std::num::NonZeroU32;
use std::str::FromStr;

use cohort_core::filters::TeamId;
use cohort_core::DayIdx;
use serde::{Deserialize, Serialize};

use super::ids::{ChunkId, ClaimEpoch, RunId, SChunkMs};
use super::window::DomainError;
use cohort_core::seed::SeedTile;

/// The lease coordinates that fence every chunk mutation: chunk identity + owning run + claim epoch.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ChunkLease {
    chunk_id: ChunkId,
    run_id: RunId,
    epoch: ClaimEpoch,
}

impl ChunkLease {
    pub(crate) const fn new(chunk_id: ChunkId, run_id: RunId, epoch: ClaimEpoch) -> Self {
        Self {
            chunk_id,
            run_id,
            epoch,
        }
    }

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

/// The persisted chunk lifecycle vocabulary. `as_str`/`FromStr` are the single source of truth the
/// store's SQL binds against; the store's unit test scans its hoisted status fragments through
/// [`ChunkStatus::from_str`] so the two can never drift.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChunkStatus {
    Pending,
    Scanning,
    Produced,
    Confirmed,
    Failed,
}

impl ChunkStatus {
    pub const ALL: [Self; 5] = [
        Self::Pending,
        Self::Scanning,
        Self::Produced,
        Self::Confirmed,
        Self::Failed,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Scanning => "scanning",
            Self::Produced => "produced",
            Self::Confirmed => "confirmed",
            Self::Failed => "failed",
        }
    }
}

impl FromStr for ChunkStatus {
    type Err = UnknownChunkStatus;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "pending" => Ok(Self::Pending),
            "scanning" => Ok(Self::Scanning),
            "produced" => Ok(Self::Produced),
            "confirmed" => Ok(Self::Confirmed),
            "failed" => Ok(Self::Failed),
            other => Err(UnknownChunkStatus(other.to_string())),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("unknown chunk status {0:?}")]
pub struct UnknownChunkStatus(pub String);

/// Whether a claim took a fresh chunk or reclaimed one whose prior lease expired. The app emits
/// `CHUNKS_RECLAIMED` on [`ClaimKind::Reclaim`]; the store no longer touches that metric.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClaimKind {
    Fresh,
    Reclaim,
}

impl ClaimKind {
    pub const fn from_was_reclaim(was_reclaim: bool) -> Self {
        if was_reclaim {
            Self::Reclaim
        } else {
            Self::Fresh
        }
    }
}

/// A band assignment proven in range at claim-row decode: `band < num_bands`, checked once.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BandSpec {
    band: u32,
    num_bands: NonZeroU32,
}

impl BandSpec {
    pub fn new(band: i16, num_bands: i64) -> Result<Self, BandSpecError> {
        let num_bands = u32::try_from(num_bands)
            .ok()
            .and_then(NonZeroU32::new)
            .ok_or(BandSpecError::InvalidBandCount(num_bands))?;
        let band = u32::try_from(band).map_err(|_| BandSpecError::BandOutOfRange {
            band,
            num_bands: num_bands.get(),
        })?;
        if band >= num_bands.get() {
            return Err(BandSpecError::BandOutOfRange {
                band: band as i16,
                num_bands: num_bands.get(),
            });
        }
        Ok(Self { band, num_bands })
    }

    pub const fn band(self) -> u32 {
        self.band
    }

    pub const fn num_bands(self) -> NonZeroU32 {
        self.num_bands
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum BandSpecError {
    #[error("claimed chunk reported invalid band count {0}")]
    InvalidBandCount(i64),
    #[error("claimed chunk band {band} is outside 0..{num_bands}")]
    BandOutOfRange { band: i16, num_bands: u32 },
}

/// The immutable coordinates carried through every chunk state. `Copy`, so a state can be consumed
/// while its spec is read back out (e.g. the store mints the next state from `chunk.spec()`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ChunkSpec {
    pub lease: ChunkLease,
    pub team_id: TeamId,
    pub day: DayIdx,
    pub band: BandSpec,
    pub s_chunk: SChunkMs,
}

/// Freshly claimed and locked; minted only by `store.claim_next` (or `test_support`).
#[derive(Debug)]
pub struct ClaimedChunk {
    spec: ChunkSpec,
}

impl ClaimedChunk {
    pub(crate) const fn new(spec: ChunkSpec) -> Self {
        Self { spec }
    }

    pub const fn spec(&self) -> ChunkSpec {
        self.spec
    }

    /// Pure transition: attach the scanned tiles. No DB effect.
    pub fn into_scanned(self, tiles: Vec<SeedTile>) -> ScannedChunk {
        ScannedChunk::new(self.spec, tiles)
    }
}

/// Scanned into tiles but not yet marked produced.
pub struct ScannedChunk {
    spec: ChunkSpec,
    tiles: Vec<SeedTile>,
}

impl ScannedChunk {
    pub(crate) fn new(spec: ChunkSpec, tiles: Vec<SeedTile>) -> Self {
        Self { spec, tiles }
    }

    pub const fn spec(&self) -> ChunkSpec {
        self.spec
    }

    pub fn tiles(&self) -> &[SeedTile] {
        &self.tiles
    }
}

impl std::fmt::Debug for ScannedChunk {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ScannedChunk")
            .field("spec", &self.spec)
            .field("tiles", &self.tiles.len())
            .finish()
    }
}

/// The `scanning`→`produced` CAS has committed; minted only by `store.mark_produced`.
#[derive(Debug)]
pub struct EnqueuedChunk {
    spec: ChunkSpec,
    tiles_produced: u64,
}

impl EnqueuedChunk {
    pub(crate) const fn new(spec: ChunkSpec, tiles_produced: u64) -> Self {
        Self {
            spec,
            tiles_produced,
        }
    }

    pub const fn spec(&self) -> ChunkSpec {
        self.spec
    }

    pub const fn tiles_produced(&self) -> u64 {
        self.tiles_produced
    }

    /// Pure transition: fold the observed delivery high-water marks in. No DB effect.
    pub fn into_produced(self, hwms: ProduceHwms) -> ProducedChunk {
        ProducedChunk {
            spec: self.spec,
            tiles_produced: self.tiles_produced,
            hwms,
        }
    }
}

/// All deliveries acknowledged; awaiting the terminal `confirm`.
#[derive(Debug)]
pub struct ProducedChunk {
    spec: ChunkSpec,
    tiles_produced: u64,
    hwms: ProduceHwms,
}

impl ProducedChunk {
    pub const fn spec(&self) -> ChunkSpec {
        self.spec
    }

    pub const fn tiles_produced(&self) -> u64 {
        self.tiles_produced
    }

    pub fn hwms(&self) -> &ProduceHwms {
        &self.hwms
    }
}

/// The run/team-mismatch and out-of-range-day checks the scanner runs before touching ClickHouse.
/// Named by the scanner (not the store), so the store never references a ClickHouse type.
#[derive(Debug, thiserror::Error)]
pub enum ChunkDomainError {
    #[error(
        "chunk run/team ({chunk_run_id:?}, {chunk_team_id}) does not match pinned run/team ({pinned_run_id:?}, {pinned_team_id})"
    )]
    RunMismatch {
        chunk_run_id: RunId,
        chunk_team_id: i32,
        pinned_run_id: RunId,
        pinned_team_id: i32,
    },
    #[error(transparent)]
    Domain(#[from] DomainError),
}

/// Why processing stopped without a terminal error the run should own. `Cancelled` distinguishes a
/// global shutdown from a lost lease; `Failed` carries the stage's own error.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CancelCause {
    Shutdown,
    LeaseLost,
}

impl CancelCause {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Shutdown => "chunk processing stopped for shutdown",
            Self::LeaseLost => "chunk processing stopped after the lease was lost",
        }
    }
}

pub enum HaltReason<E> {
    Cancelled(CancelCause),
    Failed(E),
}

/// The one carrier the pipeline consumes when a store- or scan-gated step stops: it hands the state
/// back so the caller can release or fail the chunk. Deliberately not `std::error::Error`.
pub struct Halted<S, E> {
    pub state: S,
    pub reason: HaltReason<E>,
}

impl<S, E> Halted<S, E> {
    pub fn failed(state: S, error: E) -> Self {
        Self {
            state,
            reason: HaltReason::Failed(error),
        }
    }

    pub fn cancelled(state: S, cause: CancelCause) -> Self {
        Self {
            state,
            reason: HaltReason::Cancelled(cause),
        }
    }
}

/// Per-partition delivery high-water marks, persisted as JSON on confirm. Pure data.
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

    pub fn get(&self, partition: i32) -> Option<i64> {
        self.0.get(&partition).copied()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chunk_status_round_trips_through_its_wire_vocabulary() {
        for status in ChunkStatus::ALL {
            assert_eq!(ChunkStatus::from_str(status.as_str()).unwrap(), status);
        }
        assert!(ChunkStatus::from_str("scan").is_err());
    }

    #[test]
    fn claim_kind_maps_the_prior_status_flag() {
        assert_eq!(ClaimKind::from_was_reclaim(true), ClaimKind::Reclaim);
        assert_eq!(ClaimKind::from_was_reclaim(false), ClaimKind::Fresh);
    }

    #[test]
    fn band_spec_admits_only_in_range_bands() {
        assert_eq!(BandSpec::new(3, 8).unwrap().band(), 3);
        assert!(matches!(
            BandSpec::new(8, 8),
            Err(BandSpecError::BandOutOfRange { .. })
        ));
        assert!(matches!(
            BandSpec::new(-1, 8),
            Err(BandSpecError::BandOutOfRange { .. })
        ));
        assert!(matches!(
            BandSpec::new(0, 0),
            Err(BandSpecError::InvalidBandCount(0))
        ));
    }

    #[test]
    fn produce_hwms_fold_by_partition_maximum() {
        let mut hwms = ProduceHwms::default();
        hwms.observe(2, 9);
        hwms.observe(1, 4);
        hwms.observe(2, 7);
        hwms.observe(1, 11);
        hwms.observe(3, 1);

        assert_eq!(hwms.get(1), Some(11));
        assert_eq!(hwms.get(2), Some(9));
        assert_eq!(hwms.get(3), Some(1));
        assert_eq!(
            serde_json::to_value(hwms).unwrap(),
            serde_json::json!({"1": 11, "2": 9, "3": 1})
        );
    }
}
