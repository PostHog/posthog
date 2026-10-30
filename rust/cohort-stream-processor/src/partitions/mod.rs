//! Partition-affined routing and per-partition workers.
//!
//! All state mutations for a given `(team_id, person_id)` serialize through exactly one worker,
//! with no cross-worker coordination on the hot path (the worker-affinity invariant). The
//! long-lived worker that owns the `Receiver` from [`router::PartitionRouter::add_partition`] and
//! runs the Stage 1 loop lives in [`crate::workers`].

pub mod backpressure;
pub mod fence;
pub mod follower;
pub mod intake;
pub mod offset_tracker;
pub mod ownership;
pub mod pacing;
pub mod pause;
pub mod positions;
pub mod rebalance;
pub mod router;
pub mod shuffle_message;
pub mod split;
pub mod stamp;
pub mod watermarks;

pub use cohort_core::partitioner;

pub use backpressure::{Backpressure, PartitionHoldover};
pub use fence::{
    AdmittedSplit, ClaimedSplit, CommitLedger, Committed, FenceBlock, FenceError, InputCommits,
    OwnershipAudit, StoreSource, AUDIT_INTERVAL,
};
pub use follower::{Follower, FollowerSet};
pub use intake::{Admission, MeteredReceiver, PartitionIntake};
pub use offset_tracker::{DeferredOffset, MarkOutcome, OffsetTracker};
pub use ownership::{OwnershipError, PartitionOwnership};
pub use pacing::{
    AgeMs, CauseSet, Hysteresis, PauseCause, PauseLedger, SeedPacing, SeedPacingConfig, UsedPct,
};
pub use partitioner::{
    merge_partition_key, murmur2, partition_for, partition_of, COHORT_PARTITION_COUNT,
};
pub use pause::{ConsumerPauser, PartitionPauser};
pub use positions::{
    list_offsets, FollowerGroup, InputGroups, InputPositions, InputTopic, OwnedPositions,
    PositionsError, ResumeOffset,
};
pub use rebalance::CohortConsumerContext;
pub use router::{
    PartitionRouter, RouteError, SeedReceiver, SeedRefusal, SeedSendOutcome, SendOutcome,
    WorkerInbox,
};
pub use shuffle_message::ShuffleMessage;
pub use split::{Role, SplitClaim, SplitError};
pub use stamp::{CommitStamp, Stamp, StampedList};
pub use watermarks::{LiveWatermarks, WatermarkMs};
