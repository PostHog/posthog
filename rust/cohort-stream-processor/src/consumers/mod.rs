//! Kafka consumers — one rdkafka `StreamConsumer` per input topic. The `events` submodule covers
//! `cohort_stream_events`, the hot path; `merges` carries the merge-protocol follower consumers.

pub mod events;
pub mod merges;

pub use events::{CohortStreamEvent, CohortStreamEventsConsumer, ConsumedEvent, EventDispatcher};
pub use merges::{
    CascadeRoute, ConsumedCascade, ConsumedMerge, ConsumedTransfer, FollowerConsumer,
    FollowerRoute, MergeRoute, TransferRoute,
};
