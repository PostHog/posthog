use async_trait::async_trait;
use uuid::Uuid;

use crate::storage::error::StorageResult;
use crate::storage::types::{Person, SplitResult};

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
        include_properties: bool,
    ) -> StorageResult<Vec<Person>>;

    async fn get_persons_by_uuids(
        &self,
        team_id: i64,
        uuids: &[Uuid],
        include_properties: bool,
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
        include_properties: bool,
    ) -> StorageResult<Vec<(String, Option<Person>)>>;

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
        include_properties: bool,
    ) -> StorageResult<Vec<((i64, String), Option<Person>)>>;

    // Deletes

    /// Delete persons by UUID for a given team. Large batches are split into
    /// fixed-size chunks and deleted concurrently. Each chunk runs in its own
    /// transaction, deleting distinct_ids first (FK is NO ACTION) then persons
    /// (feature flag hash key overrides cascade at the DB level). Idempotent:
    /// deleting already-removed UUIDs is a no-op.
    async fn delete_persons(&self, team_id: i64, uuids: &[Uuid]) -> StorageResult<i64>;

    /// Delete up to `batch_size` persons for a team. Selects person IDs with
    /// FOR UPDATE SKIP LOCKED, then splits them into fixed-size chunks and
    /// deletes concurrently. Each chunk deletes distinct_ids first (FK is
    /// NO ACTION) then persons (feature flag hash key overrides cascade at
    /// the DB level). Returns the number of deleted person records; 0 means
    /// no more persons to delete.
    async fn delete_persons_batch_for_team(
        &self,
        team_id: i64,
        batch_size: i64,
    ) -> StorageResult<i64>;

    /// Delete up to `batch_size` posthog_personlessdistinctid rows for a team.
    /// These rows have no person FK, so they aren't covered by person deletion.
    /// Returns the number of deleted rows; 0 means no more rows to delete.
    async fn delete_personless_distinct_ids_batch_for_team(
        &self,
        team_id: i64,
        batch_size: i64,
    ) -> StorageResult<i64>;

    /// Atomically split distinct_ids off a person onto new persons.
    ///
    /// Within a single transaction (constant statement count, set-based):
    /// 1. Locks the specified PersonDistinctId rows with SELECT FOR UPDATE and
    ///    validates ownership under the lock
    /// 2. Creates new persons via one bulk upsert (deterministic UUIDv5,
    ///    version = original person version + 101)
    /// 3. Reassigns PDIs to new persons in one bulk update
    ///    (version = original PDI version + 101)
    ///
    /// Returns StorageError::NotFound if the person doesn't exist or any
    /// distinct_id doesn't belong to it.
    async fn split_person(
        &self,
        team_id: i64,
        person_id: i64,
        distinct_ids_to_split: &[String],
    ) -> StorageResult<Vec<SplitResult>>;

    // Undelete repair

    /// Bump a person_distinct_id row's version to `min_version`, but only when the stored
    /// version is lower (the update never lowers a version). Returns the person the
    /// distinct_id maps to whenever it exists — even if the guard left the version
    /// unchanged — and None when the distinct_id does not exist (it has not been re-used
    /// yet). Used by the undelete repair flow to revive a soft-deleted distinct_id.
    async fn set_person_distinct_id_version_floor(
        &self,
        team_id: i64,
        distinct_id: &str,
        min_version: i64,
    ) -> StorageResult<Option<Person>>;

    /// Bump a person's version to `min_version`, but only when the stored version is
    /// lower (the update never lowers a version). Returns whether a row was updated.
    async fn set_person_version_floor(
        &self,
        team_id: i64,
        person_id: i64,
        min_version: i64,
    ) -> StorageResult<bool>;
}
