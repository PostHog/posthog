use async_trait::async_trait;
use uuid::Uuid;

use crate::storage::error::StorageResult;
use crate::storage::types::Person;

/// Person lookup operations by ID, UUID, and distinct ID
#[async_trait]
pub trait PersonLookup: Send + Sync {
    // Lookups by ID/UUID

    async fn get_person_by_id(&self, team_id: i64, person_id: i64)
        -> StorageResult<Option<Person>>;

    async fn get_person_by_uuid(&self, team_id: i64, uuid: Uuid) -> StorageResult<Option<Person>>;

    async fn get_persons_by_ids(
        &self,
        team_id: i64,
        person_ids: &[i64],
    ) -> StorageResult<Vec<Person>>;

    async fn get_persons_by_uuids(
        &self,
        team_id: i64,
        uuids: &[Uuid],
    ) -> StorageResult<Vec<Person>>;

    // Lookups by distinct ID

    async fn get_person_by_distinct_id(
        &self,
        team_id: i64,
        distinct_id: &str,
    ) -> StorageResult<Option<Person>>;

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<(String, Option<Person>)>>;

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
    ) -> StorageResult<Vec<((i64, String), Option<Person>)>>;
}
