//! Partition-affined routing and per-partition workers.
//!
//! All state mutations for a given `(team_id, person_id)` serialize through exactly one worker,
//! with no cross-worker coordination on the hot path (the worker-affinity invariant). The
//! long-lived worker that owns the `Receiver` from [`router::PartitionRouter::add_partition`] and
//! runs the Stage 1 loop lives in [`crate::workers`].

pub mod backpressure;
pub mod follower;
pub mod intake;
pub mod offset_tracker;
pub mod partitioner;
pub mod pause;
pub mod rebalance;
pub mod router;
pub mod shuffle_message;

pub use backpressure::Backpressure;
pub use follower::{Follower, FollowerSet, PartitionMirror};
pub use intake::{Admission, MeteredReceiver, PartitionIntake};
pub use offset_tracker::{MarkOutcome, OffsetTracker};
pub use partitioner::{
    merge_partition_key, murmur2, partition_for, partition_of, COHORT_PARTITION_COUNT,
};
pub use pause::{ConsumerPauser, PartitionPauser};
pub use rebalance::{
    run_rebalance_worker, CohortConsumerContext, ConsumerCommand, ConsumerCommandReceiver,
    ConsumerCommandSender, RebalanceEvent, RebalanceEventReceiver,
};
pub use router::{PartitionRouter, RouteError, SendOutcome};
pub use shuffle_message::ShuffleMessage;
