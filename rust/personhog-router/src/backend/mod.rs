pub mod discovery;
mod leader;
mod replica;
mod retry;
mod stash;

pub use leader::{AddressResolver, LeaderBackend, LeaderBackendConfig};
pub use replica::{ReplicaBackend, ReplicaDnsConfig};
pub use stash::{StashDecision, StashTable, StashedRequest};

use async_trait::async_trait;
use personhog_proto::personhog::types::v1::{
    GetPersonRequest, GetPersonResponse, UpdatePersonPropertiesRequest,
    UpdatePersonPropertiesResponse,
};
use tonic::Status;

/// Trait for leader-specific operations: strong-consistency reads and writes.
/// Only the leader backend implements this (partition-aware routing to leader pods).
#[async_trait]
pub trait LeaderOps: Send + Sync {
    async fn get_person(&self, request: GetPersonRequest) -> Result<GetPersonResponse, Status>;
    async fn update_person_properties(
        &self,
        request: UpdatePersonPropertiesRequest,
    ) -> Result<UpdatePersonPropertiesResponse, Status>;
}
