//! Kafka consumers — one rdkafka `StreamConsumer` per input topic. The `events` submodule covers
//! `cohort_stream_events`, the hot path; `merges` carries the merge-protocol follower consumers;
//! `seeds` carries the backfill seed follower and `run_gate` its run catalog gate; `readiness` is the
//! gate behind `/_ready`.

mod boot;
pub mod events;
pub mod merges;
pub mod readiness;
pub mod run_gate;
pub mod seeds;

pub use events::{CohortStreamEvent, CohortStreamEventsConsumer, ConsumedEvent, EventDispatcher};
pub use merges::{
    CascadeRoute, ConsumedCascade, ConsumedMerge, ConsumedTransfer, FollowerConsumer,
    FollowerRoute, MergeRoute, TransferRoute,
};
pub use readiness::{BootReadiness, NotReady, RebuildGuard};
pub use run_gate::{
    PgRunParticipants, PinnedCohort, RunLookupError, RunParticipants, RunParticipantsSource,
};
pub use seeds::{ConsumedSeed, SeedFollowerConsumer, SeedSkipReason, SeedWork};
