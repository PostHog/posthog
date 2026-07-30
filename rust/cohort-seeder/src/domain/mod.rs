//! Pure domain layer for the cohort seeder; depends only on `cohort-core`.
//!
//! No module here reaches into PostgreSQL, ClickHouse, or Kafka. The internal
//! dependency order is strictly downward:
//! `ids` ← {`condition`, `window`} ← `chunk` ← {`plan`, `pinned`, `aggregate`}.
//! The seed wire contract (`SeedTile` and the ids that ride it) lives in
//! `cohort_core::seed` — shared with the processor — and is re-exported here.

pub mod aggregate;
pub mod chunk;
pub mod condition;
pub mod ids;
pub mod pinned;
pub mod plan;
pub mod window;

pub use aggregate::{
    AggregateError, ChunkAccumulator, OutcomeKind, RecordOutcome, RecordStats, VmFailureCounts,
};
pub use chunk::{
    BandSpec, BandSpecError, CancelCause, ChunkDomainError, ChunkLease, ChunkSpec, ChunkStatus,
    ClaimKind, ClaimedChunk, EnqueuedChunk, HaltReason, Halted, ProduceHwms, ProducedChunk,
    ScannedChunk, UnknownChunkStatus,
};
pub use cohort_core::seed::SeedTile;
pub use condition::{EventNameSet, Lookback, PinnedCondition};
pub use ids::{
    Band, ChunkId, ClaimEpoch, ConditionHash, ConditionHashError, DayIdx, RunId, SChunkMs,
    UtcMillis, UtcMsRange, UtcRangeError,
};
pub use pinned::{
    PinnedDropReason, PinnedError, PinnedParticipation, PinnedParticipationState, PinnedRun,
    PinnedRunSnapshot, PinnedWarning, TriggerKind, UnknownTriggerKind, ValidatedPinnedRun,
};
pub use plan::{bands_for_day, conditions_active_on, plan_days, ActiveConditions};
pub use window::{Boundary, DomainError, PlanCaps, SeedDomain};
