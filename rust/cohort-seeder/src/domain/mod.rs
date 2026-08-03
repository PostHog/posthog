//! Pure domain layer for the cohort seeder; depends only on `cohort-core`.
//!
//! No module here reaches into PostgreSQL, ClickHouse, or Kafka. The internal
//! dependency order is strictly downward:
//! `ids` ← {`condition`, `window`} ← `chunk` ← {`plan`, `pinned`, `aggregate`} ← `person`,
//! except that `chunk` reaches back into `person` for the `PersonRange` vocabulary its spec
//! carries. The seed wire contract (`SeedTile`/`PersonSeed` and the ids that ride them) lives in
//! `cohort_core::seed` — shared with the processor — and is re-exported here.

pub mod aggregate;
pub mod chunk;
pub mod completion;
pub mod condition;
pub mod ids;
pub mod ledger;
pub mod partition;
pub mod person;
pub mod pinned;
pub mod plan;
pub mod window;

pub use aggregate::{
    AggregateError, ChunkAccumulator, OutcomeKind, RecordOutcome, RecordStats, VmFailureCounts,
};
pub use chunk::{
    BandSpec, BandSpecError, CancelCause, ChunkDomainError, ChunkLease, ChunkSpec, ChunkStatus,
    ClaimKind, ClaimedChunk, EnqueuedChunk, HaltReason, Halted, ProduceHwms, ProducedChunk,
    ScannedChunk, StreamedChunk, UnknownChunkStatus,
};
pub use cohort_core::seed::{
    BehavioralShapeHash, BehavioralShapeHashError, PersonSeed, ReconcileCompleteMarker,
    ReconcileTile, SeedTile,
};
pub(crate) use completion::MARKER_WATCH_SCHEMA;
pub use completion::{
    CommittedOffset, CompletionParts, CompletionPhase, CompletionStatus, DispatchEpoch,
    DispatchedReconcile, LivenessCheck, MarkerNovelty, MarkerPartition, MarkerPartitionError,
    MarkerWatch, MembershipPartition, NextOffset, ObservationEnds, ObservedMarker, PartitionBitmap,
    PartitionBitmapError, ProducedOffset, ReconcileHwms, ReconcileHwmsError, SeedGroupCommits,
    SettleProof, UndispatchedReason, WatchPositions,
};
pub use condition::{EventNameSet, Lookback, PinnedCondition};
pub use ids::{
    Band, ChunkId, ClaimEpoch, ConditionHash, ConditionHashError, DayIdx, RunId, SChunkMs,
    ScannedAtMs, UtcMillis, UtcMsRange, UtcRangeError,
};
pub use ledger::{MarkerFold, MarkerLedger, SettledVerdict};
pub use partition::{SeedPartition, SeedPartitionCountError, SeedPartitions};
pub use person::{
    person_chunk_sentinel_day, tile_ranges, EvaluatedConditions, PersonChunkSpec,
    PersonChunkSpecError, PersonEvaluator, PersonPinnedSnapshot, PersonPlanError, PersonRange,
    PersonRangeError, PersonRowOutcome, PersonRowSkip, PersonRunValidation, PersonSeedContext,
    PinnedPersonRun, ValidatedPinnedPersonRun, MAX_PERSON_CHUNKS,
};
pub use pinned::{
    PinnedDropReason, PinnedError, PinnedParticipation, PinnedParticipationState, PinnedRun,
    PinnedRunSnapshot, PinnedWarning, TriggerKind, UnknownTriggerKind, ValidatedPinnedRun,
};
pub use plan::{bands_for_day, conditions_active_on, plan_days, ActiveConditions};
pub use window::{Boundary, DomainError, PlanCaps, SeedDomain};
