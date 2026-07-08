pub mod discovery;
mod leader;
mod replica;
mod retry;
mod stash;

pub use leader::{AddressResolver, LeaderBackend, LeaderBackendConfig};
pub use replica::{ReplicaBackend, ReplicaDnsConfig};
pub use stash::{StashDecision, StashTable, StashedRequest};
