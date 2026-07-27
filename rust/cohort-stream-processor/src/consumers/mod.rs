//! Kafka consumers — one rdkafka `StreamConsumer` per input topic. The `events` submodule covers
//! `cohort_stream_events`, the hot path; `merges` carries the merge-protocol follower consumers;
//! `seeds` carries the backfill seed follower.

pub mod events;
pub mod merges;
pub mod seeds;

pub use events::{CohortStreamEvent, CohortStreamEventsConsumer, ConsumedEvent, EventDispatcher};
pub use merges::{
    CascadeRoute, ConsumedCascade, ConsumedMerge, ConsumedTransfer, FollowerConsumer,
    FollowerRoute, MergeRoute, TransferRoute,
};
pub use seeds::{ConsumedSeed, SeedFollowerConsumer, SeedSkipReason, SeedWork};
