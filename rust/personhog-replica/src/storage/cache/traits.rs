use async_trait::async_trait;
use uuid::Uuid;

use crate::storage::{Person, StorageResult};

/// Trait for person lookup caching.
///
/// Implementations can provide different caching behaviors:
/// - `NoopPersonCache`: Pass through directly to storage (no caching)
/// - Future: `RedisPersonCache`: Cache-aside pattern with Redis
///
/// The trait mirrors `PersonLookup` but with an explicit focus on caching.
/// Implementations wrap an underlying storage and can add caching logic
/// before/after storage calls.
#[async_trait]
pub trait PersonCache: Send + Sync {
    /// Get a person by their internal ID.
    /// Implementations may check cache first before hitting storage.
    async fn get_person_by_id(&self, team_id: i64, person_id: i64)
        -> StorageResult<Option<Person>>;

    /// Get a person by their UUID.
    async fn get_person_by_uuid(&self, team_id: i64, uuid: Uuid) -> StorageResult<Option<Person>>;

    /// Get multiple persons by their internal IDs.
    async fn get_persons_by_ids(
        &self,
        team_id: i64,
        person_ids: &[i64],
    ) -> StorageResult<Vec<Person>>;

    /// Get multiple persons by their UUIDs.
    async fn get_persons_by_uuids(
        &self,
        team_id: i64,
        uuids: &[Uuid],
    ) -> StorageResult<Vec<Person>>;

    /// Get a person by distinct ID (highest volume operation).
    async fn get_person_by_distinct_id(
        &self,
        team_id: i64,
        distinct_id: &str,
    ) -> StorageResult<Option<Person>>;

    /// Get multiple persons by distinct IDs within a single team.
    async fn get_persons_by_distinct_ids_in_team(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<(String, Option<Person>)>>;

    /// Get multiple persons by distinct IDs across different teams.
    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
    ) -> StorageResult<Vec<((i64, String), Option<Person>)>>;
}
