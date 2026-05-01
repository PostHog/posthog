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

    // Deletes

    /// Delete persons by UUID for a given team. In a single transaction:
    /// 1. Deletes associated posthog_persondistinctid rows (FK is NO ACTION, would block otherwise)
    /// 2. Deletes the posthog_person rows (posthog_featureflaghashkeyoverride cascades at DB level)
    /// Returns the number of deleted person records.
    async fn delete_persons(&self, team_id: i64, uuids: &[Uuid]) -> StorageResult<i64>;

    /// Delete up to `batch_size` persons for a team. In a single transaction:
    /// 1. Selects up to batch_size person IDs for the team
    /// 2. Deletes their posthog_persondistinctid rows (FK is NO ACTION)
    /// 3. Deletes the posthog_person rows (posthog_featureflaghashkeyoverride cascades at DB level)
    /// Returns the number of deleted person records. 0 means no more persons to delete.
    async fn delete_persons_batch_for_team(
        &self,
        team_id: i64,
        batch_size: i64,
    ) -> StorageResult<i64>;
}
