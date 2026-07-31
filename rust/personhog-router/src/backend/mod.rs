pub mod discovery;
mod leader;
mod replica;
mod stash;

pub use leader::{
    AddressResolver, BounceReason, ForwardDecision, ForwardPath, LeaderBackend, LeaderBackendConfig,
};
pub(crate) use leader::{BOUNCE_BACKOFF, MAX_CONSECUTIVE_BOUNCES};
pub use replica::{ReplicaBackend, ReplicaDnsConfig};
pub use stash::{DrainSession, StashDecision, StashKey, StashTable, StashedRequest, TakenKeyRun};
