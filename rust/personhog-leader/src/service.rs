use std::sync::Arc;

use common_kafka::kafka_producer::KafkaContext;
use dashmap::DashMap;
use metrics::counter;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeader;
use personhog_proto::personhog::leader::v1::LeaderGetPersonRequest;
use personhog_proto::personhog::types::v1::{
    GetPersonResponse, Person, UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};
use rdkafka::producer::FutureProducer;
use sqlx::postgres::PgPool;
use tokio::sync::Mutex;
use tonic::{Request, Response, Status};

use crate::cache::{CacheLookup, CachedPerson, PartitionedCache, PersonCacheKey};
use crate::kafka::produce_person_changelog;
use crate::person_update::{apply_property_updates, compute_event_property_updates};
use crate::pg::load_person_from_pg;

pub struct PersonHogLeaderService {
    cache: Arc<PartitionedCache>,
    /// Per-key locks to serialize concurrent updates for the same person.
    /// Prevents lost updates from concurrent get -> compute -> produce -> put
    /// sequences, and thundering herd on PG fallback.
    locks: Arc<DashMap<PersonCacheKey, Arc<Mutex<()>>>>,
    producer: FutureProducer<KafkaContext>,
    changelog_topic: String,
    /// Read-only pool for PG fallback on cache miss.
    fallback_pool: Option<PgPool>,
}

impl PersonHogLeaderService {
    pub fn new(
        cache: Arc<PartitionedCache>,
        producer: FutureProducer<KafkaContext>,
        changelog_topic: String,
        fallback_pool: Option<PgPool>,
        locks: Arc<DashMap<PersonCacheKey, Arc<Mutex<()>>>>,
    ) -> Self {
        Self {
            cache,
            locks,
            producer,
            changelog_topic,
            fallback_pool,
        }
    }

    /// Load a person from PG and populate the cache. Assumes the caller
    /// holds the per-key lock.
    async fn load_from_pg(
        &self,
        partition: u32,
        key: &PersonCacheKey,
    ) -> Result<Arc<CachedPerson>, Status> {
        let Some(pool) = &self.fallback_pool else {
            return Err(Status::not_found(format!(
                "person not found: team_id={}, person_id={}",
                key.team_id, key.person_id
            )));
        };

        match load_person_from_pg(pool, key).await {
            Ok(Some(person)) => {
                self.cache.put(partition, key.clone(), person.clone());
                Ok(Arc::new(person))
            }
            Ok(None) => Err(Status::not_found(format!(
                "person not found: team_id={}, person_id={}",
                key.team_id, key.person_id
            ))),
            Err(e) => {
                counter!("personhog_leader_pg_fallback_errors_total").increment(1);
                tracing::error!(
                    team_id = key.team_id,
                    person_id = key.person_id,
                    error = %e,
                    "PG fallback query failed"
                );
                Err(Status::internal("failed to load person from database"))
            }
        }
    }

    /// Look up a person from cache, falling back to PG on miss.
    /// Acquires a per-key lock.
    async fn lookup_or_load(
        &self,
        partition: u32,
        key: &PersonCacheKey,
    ) -> Result<Arc<CachedPerson>, Status> {
        // Fast path: cache hit (no lock needed)
        match self.cache.get(partition, key) {
            CacheLookup::Found(person) => return Ok(person),
            CacheLookup::PartitionNotOwned => {
                return Err(Status::failed_precondition(format!(
                    "partition {} not owned by this leader",
                    partition
                )));
            }
            CacheLookup::PersonNotFound => {}
        }

        // Cache miss -- acquire per-key lock to prevent thundering herd
        let mutex = self.locks.entry(key.clone()).or_default().value().clone();
        let _guard = mutex.lock().await;

        // Double-check cache -- another request may have loaded it
        if let CacheLookup::Found(person) = self.cache.get(partition, key) {
            return Ok(person);
        }

        self.load_from_pg(partition, key).await
    }

    /// Look up a person from cache, falling back to PG on miss.
    /// The caller must already hold the per-key lock.
    async fn lookup_or_load_locked(
        &self,
        partition: u32,
        key: &PersonCacheKey,
    ) -> Result<Arc<CachedPerson>, Status> {
        match self.cache.get(partition, key) {
            CacheLookup::Found(person) => Ok(person),
            CacheLookup::PartitionNotOwned => Err(Status::failed_precondition(format!(
                "partition {} not owned by this leader",
                partition
            ))),
            CacheLookup::PersonNotFound => self.load_from_pg(partition, key).await,
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

        let person = self.lookup_or_load(req.partition, &cache_key).await?;

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

        // Per-key lock serializes concurrent updates for the same person
        let mutex = self
            .locks
            .entry(cache_key.clone())
            .or_default()
            .value()
            .clone();
        let _guard = mutex.lock().await;

        let person = self
            .lookup_or_load_locked(req.partition, &cache_key)
            .await?;

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

        // Produce to Kafka first, then update the cache on success.
        // Readers only ever see durably committed state.
        if let Err(e) =
            produce_person_changelog(&self.producer, &self.changelog_topic, &proto).await
        {
            tracing::error!(
                team_id = cache_key.team_id,
                person_id = cache_key.person_id,
                error = %e,
                "failed to produce person state changelog"
            );
            return Err(Status::internal(format!(
                "failed to durably store person state: {e}"
            )));
        }

        self.cache.put(req.partition, cache_key, updated_person);
        counter!("personhog_leader_updates_total", "outcome" => "updated").increment(1);

        Ok(Response::new(UpdatePersonPropertiesResponse {
            person: Some(proto),
            updated: true,
        }))
    }
}

/// Remove lock entries that no one is currently waiting on. Entries
/// with `Arc::strong_count == 1` are only held by the map itself, so
/// no request is actively using them. Returns the number removed.
pub fn sweep_idle_locks(locks: &DashMap<PersonCacheKey, Arc<Mutex<()>>>) -> usize {
    let before = locks.len();
    locks.retain(|_, v| Arc::strong_count(v) > 1);
    let removed = before - locks.len();
    if removed > 0 {
        tracing::debug!(removed, remaining = locks.len(), "swept idle locks");
    }
    removed
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_key(team_id: i64, person_id: i64) -> PersonCacheKey {
        PersonCacheKey { team_id, person_id }
    }

    #[test]
    fn sweep_removes_idle_entries() {
        let locks = DashMap::new();
        locks.insert(make_key(1, 1), Arc::new(Mutex::new(())));
        locks.insert(make_key(1, 2), Arc::new(Mutex::new(())));
        locks.insert(make_key(1, 3), Arc::new(Mutex::new(())));

        let removed = sweep_idle_locks(&locks);

        assert_eq!(removed, 3);
        assert_eq!(locks.len(), 0);
    }

    #[test]
    fn sweep_preserves_held_entries() {
        let locks = DashMap::new();
        locks.insert(make_key(1, 1), Arc::new(Mutex::new(())));
        locks.insert(make_key(1, 2), Arc::new(Mutex::new(())));
        locks.insert(make_key(1, 3), Arc::new(Mutex::new(())));

        // Simulate an active holder cloning the Arc (as lookup_or_load does)
        let _held = locks.get(&make_key(1, 2)).unwrap().clone();

        let removed = sweep_idle_locks(&locks);

        assert_eq!(removed, 2);
        assert_eq!(locks.len(), 1);
        assert!(locks.contains_key(&make_key(1, 2)));
    }

    #[test]
    fn sweep_is_noop_when_empty() {
        let locks: DashMap<PersonCacheKey, Arc<Mutex<()>>> = DashMap::new();

        let removed = sweep_idle_locks(&locks);

        assert_eq!(removed, 0);
    }
}
