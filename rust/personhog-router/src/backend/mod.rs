mod channel;
pub mod discovery;
mod follower;
mod leader;
mod stash;

pub use channel::{ChannelBackend, DnsBackendConfig};
pub use follower::{FollowerBackend, FollowerInstance};
pub(crate) use leader::counts_as_possibly_applied;
pub use leader::{
    AddressResolver, BounceReason, ForwardDecision, ForwardPath, LeaderBackend, LeaderBackendConfig,
};
pub(crate) use leader::{BOUNCE_BACKOFF, MAX_CONSECUTIVE_BOUNCES};
pub use stash::{DrainSession, StashDecision, StashKey, StashTable, StashedRequest, TakenKeyRun};
