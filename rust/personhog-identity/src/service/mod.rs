//! The gRPC service surface. This module is dispatch-only: each RPC family
//! lives in its own submodule (get_or_create today; resolution, claims,
//! splits, and merge classification will follow the same pattern).

pub mod error;
pub mod get_or_create;
pub mod validation;

use std::sync::Arc;

use tonic::{Request, Response, Status};

use personhog_proto::personhog::identity::v1::person_hog_identity_server::PersonHogIdentity;
use personhog_proto::personhog::identity::v1::{
    GetOrCreatePersonByDistinctIdRequest, GetOrCreatePersonByDistinctIdResponse,
    GetOrCreatePersonResult, GetOrCreatePersonsByDistinctIdsRequest,
    GetOrCreatePersonsByDistinctIdsResponse,
};

use crate::leader::PropertyWriter;
use crate::service::validation::{validate_batch_size, validate_entry, RequestLimits};
use crate::storage::IdentityStorage;

pub struct PersonHogIdentityService {
    pub(crate) storage: Arc<dyn IdentityStorage>,
    pub(crate) property_writer: Arc<dyn PropertyWriter>,
    pub(crate) limits: RequestLimits,
}

impl PersonHogIdentityService {
    pub fn new(
        storage: Arc<dyn IdentityStorage>,
        property_writer: Arc<dyn PropertyWriter>,
        limits: RequestLimits,
    ) -> Self {
        Self {
            storage,
            property_writer,
            limits,
        }
    }
}

#[tonic::async_trait]
impl PersonHogIdentity for PersonHogIdentityService {
    async fn get_or_create_person_by_distinct_id(
        &self,
        request: Request<GetOrCreatePersonByDistinctIdRequest>,
    ) -> Result<Response<GetOrCreatePersonByDistinctIdResponse>, Status> {
        let entry = request
            .into_inner()
            .entry
            .ok_or_else(|| Status::invalid_argument("entry is required"))?;
        validate_entry(&self.limits, &entry)?;

        let mut results = self.get_or_create_entries(vec![entry]).await?;
        let (person, created) = results.pop().expect("one entry yields one result")?;
        Ok(Response::new(GetOrCreatePersonByDistinctIdResponse {
            person: Some(person),
            created,
        }))
    }

    async fn get_or_create_persons_by_distinct_ids(
        &self,
        request: Request<GetOrCreatePersonsByDistinctIdsRequest>,
    ) -> Result<Response<GetOrCreatePersonsByDistinctIdsResponse>, Status> {
        let entries = request.into_inner().entries;
        validate_batch_size(&self.limits, entries.len())?;

        let identifiers: Vec<(i64, String)> = entries
            .iter()
            .map(|entry| (entry.team_id, entry.distinct_id.clone()))
            .collect();
        let outcomes = self.get_or_create_entries(entries).await?;

        let results = identifiers
            .into_iter()
            .zip(outcomes)
            .map(|((team_id, distinct_id), outcome)| match outcome {
                Ok((person, created)) => GetOrCreatePersonResult {
                    team_id,
                    distinct_id,
                    person: Some(person),
                    created,
                    error: None,
                },
                Err(status) => GetOrCreatePersonResult {
                    team_id,
                    distinct_id,
                    person: None,
                    created: false,
                    error: Some(format!("{:?}: {}", status.code(), status.message())),
                },
            })
            .collect();

        Ok(Response::new(GetOrCreatePersonsByDistinctIdsResponse {
            results,
        }))
    }
}
