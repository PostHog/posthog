//! The gRPC service surface. This module is dispatch-only: each RPC family
//! lives in its own submodule (get_or_create and the merge entrance today;
//! resolution, claims, and splits will follow the same pattern). [`merge`]
//! carries MergePersons' identity work — validation, resolution,
//! classification, inline settlement.

pub mod error;
pub mod get_or_create;
pub mod merge;
pub mod validation;

use std::sync::Arc;

use tonic::{Request, Response, Status};

use personhog_proto::personhog::identity::v1::person_hog_identity_server::PersonHogIdentity;
use personhog_proto::personhog::identity::v1::{
    GetDistinctIdsForPersonsRequest, GetDistinctIdsForPersonsResponse,
    GetOrCreatePersonByDistinctIdRequest, GetOrCreatePersonByDistinctIdResponse,
    GetOrCreatePersonResult, GetOrCreatePersonsByDistinctIdsRequest,
    GetOrCreatePersonsByDistinctIdsResponse, GetPersonByDistinctIdResult,
    GetPersonsByDistinctIdsRequest, GetPersonsByDistinctIdsResponse, MergePersonsRequest,
    MergePersonsResponse,
};
use personhog_proto::personhog::types::v1::{DistinctIdWithVersion, PersonDistinctIds};

use crate::leader::PropertyWriter;
use crate::service::merge::MergeEntrance;
use crate::service::validation::{
    validate_batch_size, validate_entry, validate_team_id, RequestLimits,
};
use crate::storage::IdentityStorage;

pub struct PersonHogIdentityService {
    pub(crate) storage: Arc<dyn IdentityStorage>,
    pub(crate) property_writer: Arc<dyn PropertyWriter>,
    pub(crate) limits: RequestLimits,
    merge: MergeEntrance,
}

impl PersonHogIdentityService {
    pub fn new(
        storage: Arc<dyn IdentityStorage>,
        property_writer: Arc<dyn PropertyWriter>,
        limits: RequestLimits,
        merge: MergeEntrance,
    ) -> Self {
        Self {
            storage,
            property_writer,
            limits,
            merge,
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

    async fn get_persons_by_distinct_ids(
        &self,
        request: Request<GetPersonsByDistinctIdsRequest>,
    ) -> Result<Response<GetPersonsByDistinctIdsResponse>, Status> {
        let keys = request.into_inner().keys;
        validate_batch_size(&self.limits, keys.len())?;
        for key in &keys {
            validate_team_id(key.team_id)?;
        }

        let identifiers: Vec<(i64, String)> = keys
            .iter()
            .map(|key| (key.team_id, key.distinct_id.clone()))
            .collect();
        let resolved = self
            .storage
            .resolve_distinct_ids(&identifiers)
            .await
            .map_err(|e| crate::service::error::log_and_convert_error(e, "resolve_distinct_ids"))?;

        let results = identifiers
            .into_iter()
            .map(|(team_id, distinct_id)| {
                // Look up rather than consume: a key repeated in one
                // request must resolve on every occurrence.
                let person = resolved
                    .get(&(team_id, distinct_id.clone()))
                    .cloned()
                    .map(Into::into);
                GetPersonByDistinctIdResult {
                    team_id,
                    distinct_id,
                    person,
                }
            })
            .collect();
        Ok(Response::new(GetPersonsByDistinctIdsResponse { results }))
    }

    async fn get_distinct_ids_for_persons(
        &self,
        request: Request<GetDistinctIdsForPersonsRequest>,
    ) -> Result<Response<GetDistinctIdsForPersonsResponse>, Status> {
        let req = request.into_inner();
        validate_team_id(req.team_id)?;
        validate_batch_size(&self.limits, req.person_ids.len())?;

        // Dedupe: the response groups by person, so a repeated id adds
        // nothing — but the limited query's UNNEST + LATERAL runs per
        // occurrence, and duplicated rows would merge into one group
        // that exceeds the advertised per-person limit.
        let mut person_ids = req.person_ids;
        person_ids.sort_unstable();
        person_ids.dedup();

        let mappings = self
            .storage
            .get_distinct_ids_for_persons(req.team_id, &person_ids, req.limit_per_person)
            .await
            .map_err(|e| {
                crate::service::error::log_and_convert_error(e, "get_distinct_ids_for_persons")
            })?;

        let mut by_person: std::collections::HashMap<i64, Vec<DistinctIdWithVersion>> =
            std::collections::HashMap::new();
        for mapping in mappings {
            by_person
                .entry(mapping.person_id)
                .or_default()
                .push(DistinctIdWithVersion {
                    distinct_id: mapping.distinct_id,
                    version: mapping.version,
                });
        }
        let person_distinct_ids = by_person
            .into_iter()
            .map(|(person_id, distinct_ids)| PersonDistinctIds {
                person_id,
                distinct_ids,
            })
            .collect();
        Ok(Response::new(GetDistinctIdsForPersonsResponse {
            person_distinct_ids,
        }))
    }

    async fn merge_persons(
        &self,
        request: Request<MergePersonsRequest>,
    ) -> Result<Response<MergePersonsResponse>, Status> {
        Ok(Response::new(
            self.merge.handle(request.into_inner()).await?,
        ))
    }
}
