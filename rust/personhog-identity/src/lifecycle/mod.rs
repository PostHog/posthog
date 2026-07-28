//! Lifecycle sagas: person-destroying operations (delete now, merge case 3
//! later) run as durable sagas with all state in the lifecycle_op tables on
//! the persons primary. Self-contained on purpose — no imports from the
//! get-or-create side; anything shared belongs in personhog-common.
//!
//! This module currently carries the service surface and request validation
//! only. The saga engine (op persistence, lease, step advance, sweeper, GC)
//! and the delete step handlers land next; until then DeletePersons validates
//! and returns UNIMPLEMENTED.

pub mod validation;

use tonic::{Request, Response, Status};

use personhog_proto::personhog::lifecycle::v1::person_hog_lifecycle_server::PersonHogLifecycle;
use personhog_proto::personhog::lifecycle::v1::{DeletePersonsRequest, DeletePersonsResponse};

use crate::lifecycle::validation::validate_delete_persons;

#[derive(Default)]
pub struct PersonHogLifecycleService {}

impl PersonHogLifecycleService {
    pub fn new() -> Self {
        Self {}
    }
}

#[tonic::async_trait]
impl PersonHogLifecycle for PersonHogLifecycleService {
    async fn delete_persons(
        &self,
        request: Request<DeletePersonsRequest>,
    ) -> Result<Response<DeletePersonsResponse>, Status> {
        let request = request.into_inner();
        validate_delete_persons(&request)?;

        Err(Status::unimplemented(
            "DeletePersons is not enabled yet: the delete saga engine has not landed",
        ))
    }
}
