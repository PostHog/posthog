use std::sync::Arc;

use metrics::counter;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeader;
use personhog_proto::personhog::leader::v1::{
    LeaderGetPersonRequest, UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};
use personhog_proto::personhog::types::v1::{GetPersonResponse, Person};
use tonic::{Request, Response, Status};

use crate::cache::{CachedPerson, PartitionedCache, PersonCacheKey};
use crate::person_update::{apply_property_updates, compute_event_property_updates};

pub struct PersonHogLeaderService {
    cache: Arc<PartitionedCache>,
}

impl PersonHogLeaderService {
    pub fn new(cache: Arc<PartitionedCache>) -> Self {
        Self { cache }
    }
}

fn cached_person_to_proto(p: &CachedPerson) -> Person {
    let properties_bytes = serde_json::to_vec(&p.properties).unwrap_or_default();
    Person {
        id: p.id,
        uuid: p.uuid.clone(),
        team_id: p.team_id,
        properties: properties_bytes,
        properties_last_updated_at: Vec::new(),
        properties_last_operation: Vec::new(),
        created_at: p.created_at,
        version: p.version,
        is_identified: p.is_identified,
        is_user_id: None,
        last_seen_at: None,
    }
}

#[tonic::async_trait]
impl PersonHogLeader for PersonHogLeaderService {
    async fn get_person(
        &self,
        request: Request<LeaderGetPersonRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        let req = request.into_inner();
        let cache_key = PersonCacheKey {
            team_id: req.team_id,
            person_id: req.person_id,
        };

        if !self.cache.has_partition(req.partition) {
            return Err(Status::failed_precondition(format!(
                "partition {} not owned by this leader",
                req.partition
            )));
        }

        let person = self.cache.get(req.partition, &cache_key).ok_or_else(|| {
            Status::not_found(format!(
                "person not found: team_id={}, person_id={}",
                req.team_id, req.person_id
            ))
        })?;

        Ok(Response::new(GetPersonResponse {
            person: Some(cached_person_to_proto(&person)),
        }))
    }

    async fn update_person_properties(
        &self,
        request: Request<UpdatePersonPropertiesRequest>,
    ) -> Result<Response<UpdatePersonPropertiesResponse>, Status> {
        let req = request.into_inner();

        if !self.cache.has_partition(req.partition) {
            return Err(Status::failed_precondition(format!(
                "partition {} not owned by this leader",
                req.partition
            )));
        }

        let cache_key = PersonCacheKey {
            team_id: req.team_id,
            person_id: req.person_id,
        };

        let person = self.cache.get(req.partition, &cache_key).ok_or_else(|| {
            Status::not_found(format!(
                "person not found: team_id={}, person_id={}",
                req.team_id, req.person_id
            ))
        })?;

        // Parse the property diffs from the request
        let set_properties: serde_json::Value = if req.set_properties.is_empty() {
            serde_json::Value::Object(serde_json::Map::new())
        } else {
            serde_json::from_slice(&req.set_properties).map_err(|e| {
                Status::invalid_argument(format!("invalid set_properties JSON: {e}"))
            })?
        };

        let set_once_properties: serde_json::Value = if req.set_once_properties.is_empty() {
            serde_json::Value::Object(serde_json::Map::new())
        } else {
            serde_json::from_slice(&req.set_once_properties).map_err(|e| {
                Status::invalid_argument(format!("invalid set_once_properties JSON: {e}"))
            })?
        };

        // Compute property updates
        let updates = compute_event_property_updates(
            &req.event_name,
            &set_properties,
            &set_once_properties,
            &req.unset_properties,
            &person.properties,
        );

        if !updates.has_changes {
            counter!("personhog_leader_updates_total", "outcome" => "no_change").increment(1);
            return Ok(Response::new(UpdatePersonPropertiesResponse {
                person: Some(cached_person_to_proto(&person)),
                updated: false,
            }));
        }

        // Apply updates to get new properties
        let (new_properties, actually_updated) =
            apply_property_updates(&updates, &person.properties);

        if !actually_updated {
            counter!("personhog_leader_updates_total", "outcome" => "no_change").increment(1);
            return Ok(Response::new(UpdatePersonPropertiesResponse {
                person: Some(cached_person_to_proto(&person)),
                updated: false,
            }));
        }

        // TODO: get → compute → put is not atomic. Two concurrent requests for the same
        // person could read the same version, compute independently, and last-write-wins.
        // Safe while each partition has a single leader, but needs compare-and-swap or
        // per-key locking for production multi-writer scenarios.
        let updated_person = CachedPerson {
            properties: new_properties,
            version: person.version + 1,
            ..person
        };
        self.cache
            .put(req.partition, cache_key, updated_person.clone());

        counter!("personhog_leader_updates_total", "outcome" => "updated").increment(1);

        Ok(Response::new(UpdatePersonPropertiesResponse {
            person: Some(cached_person_to_proto(&updated_person)),
            updated: true,
        }))
    }
}
