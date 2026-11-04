//! Kafka consumers — one rdkafka `StreamConsumer` per input topic. The `events` submodule covers
//! `cohort_stream_events`, the hot path; `merges` carries the merge-protocol follower consumers;
//! `seeds` carries the backfill seed follower; `readiness` is the gate behind `/_ready`.

mod boot;
pub mod events;
pub mod merges;
pub mod readiness;
pub mod seeds;

pub use events::{CohortStreamEvent, CohortStreamEventsConsumer, ConsumedEvent, EventDispatcher};
pub use merges::{
    CascadeRoute, ConsumedCascade, ConsumedMerge, ConsumedTransfer, FollowerConsumer,
    FollowerRoute, MergeRoute, TransferRoute,
};
pub use readiness::{BootReadiness, NotReady, RebuildGuard};
pub use seeds::{ConsumedSeed, SeedFollowerConsumer, SeedSkipReason, SeedWork};
