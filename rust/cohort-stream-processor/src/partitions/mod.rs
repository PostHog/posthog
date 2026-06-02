//! Partition-affined routing and per-partition workers.
//!
//! All state mutations for a given `(team_id, person_id)` serialize through exactly one worker,
//! with no cross-worker coordination on the hot path (the worker-affinity invariant). The
//! long-lived worker that owns the `Receiver` from [`router::PartitionRouter::add_partition`] and
//! runs the Stage 1 loop lives in [`crate::workers`].

pub mod offset_tracker;
pub mod rebalance;
pub mod router;
pub mod shuffle_message;

pub use offset_tracker::{is_replay, MarkOutcome, OffsetTracker};
pub use rebalance::{
    run_rebalance_worker, CohortConsumerContext, ConsumerCommand, ConsumerCommandReceiver,
    ConsumerCommandSender, RebalanceEvent, RebalanceEventReceiver,
};
pub use router::{PartitionRouter, RouteError};
pub use shuffle_message::ShuffleMessage;
