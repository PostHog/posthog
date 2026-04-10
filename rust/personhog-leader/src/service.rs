use std::sync::{Arc, Mutex};

use dashmap::DashMap;
use metrics::counter;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeader;
use personhog_proto::personhog::leader::v1::LeaderGetPersonRequest;
use personhog_proto::personhog::types::v1::{
    GetPersonResponse, Person, UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};
use tonic::{Request, Response, Status};

use crate::cache::{CacheLookup, CachedPerson, PartitionedCache, PersonCacheKey};
use crate::person_update::{apply_property_updates, compute_event_property_updates};

pub struct PersonHogLeaderService {
    cache: Arc<PartitionedCache>,
    /// Per-key locks to serialize concurrent updates for the same person.
    /// Prevents lost updates from concurrent get → compute → put sequences.
    update_locks: DashMap<PersonCacheKey, Arc<Mutex<()>>>,
}

impl PersonHogLeaderService {
    pub fn new(cache: Arc<PartitionedCache>) -> Self {
        Self {
            cache,
            update_locks: DashMap::new(),
        }
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

#[allow(clippy::result_large_err)]
fn lookup_person(
    cache: &PartitionedCache,
    partition: u32,
    key: &PersonCacheKey,
) -> Result<Arc<CachedPerson>, Status> {
    match cache.get(partition, key) {
        CacheLookup::Found(person) => Ok(person),
        CacheLookup::PersonNotFound => Err(Status::not_found(format!(
            "person not found: team_id={}, person_id={}",
            key.team_id, key.person_id
        ))),
        CacheLookup::PartitionNotOwned => Err(Status::failed_precondition(format!(
            "partition {} not owned by this leader",
            partition
        ))),
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

        let person = lookup_person(&self.cache, req.partition, &cache_key)?;

        Ok(Response::new(GetPersonResponse {
            person: Some(cached_person_to_proto(&person)),
        }))
    }

    async fn update_person_properties(
        &self,
        request: Request<UpdatePersonPropertiesRequest>,
    ) -> Result<Response<UpdatePersonPropertiesResponse>, Status> {
        let req = request.into_inner();

        let cache_key = PersonCacheKey {
            team_id: req.team_id,
            person_id: req.person_id,
        };

        // Parse JSON before acquiring the per-key lock to minimize lock hold time
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

        // Per-key lock serializes concurrent updates for the same person,
        // preventing lost updates from concurrent get → compute → put sequences.
        let mutex = self
            .update_locks
            .entry(cache_key.clone())
            .or_default()
            .value()
            .clone();
        let _guard = mutex.lock().expect("update lock poisoned");

        let person = lookup_person(&self.cache, req.partition, &cache_key)?;

        // Compute property updates
        let updates = compute_event_property_updates(
            &req.event_name,
            &set_properties,
            &set_once_properties,
            &req.unset_properties,
            &person.properties,
        );

        // Fast path: no diffs detected, skip the clone in apply_property_updates
        if !updates.has_changes {
            counter!("personhog_leader_updates_total", "outcome" => "no_change").increment(1);
            return Ok(Response::new(UpdatePersonPropertiesResponse {
                person: Some(cached_person_to_proto(&person)),
                updated: false,
            }));
        }

        // Slow path: apply diffs and check if the values actually changed
        // (has_changes can be true when $set sends the same value that already exists)
        let (new_properties, actually_updated) =
            apply_property_updates(&updates, &person.properties);

        if !actually_updated {
            counter!("personhog_leader_updates_total", "outcome" => "no_change").increment(1);
            return Ok(Response::new(UpdatePersonPropertiesResponse {
                person: Some(cached_person_to_proto(&person)),
                updated: false,
            }));
        }

        let updated_person = CachedPerson {
            id: person.id,
            uuid: person.uuid.clone(),
            team_id: person.team_id,
            properties: new_properties,
            created_at: person.created_at,
            version: person.version + 1,
            is_identified: person.is_identified,
        };
        let proto = cached_person_to_proto(&updated_person);
        self.cache.put(req.partition, cache_key, updated_person);

        counter!("personhog_leader_updates_total", "outcome" => "updated").increment(1);

        Ok(Response::new(UpdatePersonPropertiesResponse {
            person: Some(proto),
            updated: true,
        }))
    }
}
