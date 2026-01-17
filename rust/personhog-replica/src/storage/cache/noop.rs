use std::sync::Arc;

use async_trait::async_trait;
use uuid::Uuid;

use super::traits::PersonCache;
use crate::storage::{Person, PersonLookup, StorageResult};

/// A no-op person cache that passes all requests directly to the underlying storage.
///
/// This is used when caching is disabled. It implements the `PersonCache` trait
/// but performs no caching - all operations delegate immediately to the wrapped
/// `PersonLookup` implementation.
pub struct NoopPersonCache<S: PersonLookup> {
    storage: Arc<S>,
}

impl<S: PersonLookup> NoopPersonCache<S> {
    pub fn new(storage: Arc<S>) -> Self {
        Self { storage }
    }
}

#[async_trait]
impl<S: PersonLookup + 'static> PersonCache for NoopPersonCache<S> {
    async fn get_person_by_id(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> StorageResult<Option<Person>> {
        self.storage.get_person_by_id(team_id, person_id).await
    }

    async fn get_person_by_uuid(&self, team_id: i64, uuid: Uuid) -> StorageResult<Option<Person>> {
        self.storage.get_person_by_uuid(team_id, uuid).await
    }

    async fn get_persons_by_ids(
        &self,
        team_id: i64,
        person_ids: &[i64],
    ) -> StorageResult<Vec<Person>> {
        self.storage.get_persons_by_ids(team_id, person_ids).await
    }

    async fn get_persons_by_uuids(
        &self,
        team_id: i64,
        uuids: &[Uuid],
    ) -> StorageResult<Vec<Person>> {
        self.storage.get_persons_by_uuids(team_id, uuids).await
    }

    async fn get_person_by_distinct_id(
        &self,
        team_id: i64,
        distinct_id: &str,
    ) -> StorageResult<Option<Person>> {
        self.storage
            .get_person_by_distinct_id(team_id, distinct_id)
            .await
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<(String, Option<Person>)>> {
        self.storage
            .get_persons_by_distinct_ids_in_team(team_id, distinct_ids)
            .await
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
    ) -> StorageResult<Vec<((i64, String), Option<Person>)>> {
        self.storage
            .get_persons_by_distinct_ids_cross_team(team_distinct_ids)
            .await
    }
}
