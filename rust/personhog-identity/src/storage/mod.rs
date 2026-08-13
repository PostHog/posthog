pub mod error;
pub mod postgres;
pub mod types;

use std::collections::HashMap;

use async_trait::async_trait;

pub use error::{StorageError, StorageResult};
pub use types::{AttachOutcome, DistinctIdMapping, Person, PersonStub, StubOutcome};

pub const DB_QUERY_DURATION: &str = "personhog_identity_db_query_duration_ms";

/// Storage operations for the identity service. All queries run on the
/// Postgres primary: identity resolution must never be stale, and stub
/// creation is a sync-plane write.
#[async_trait]
pub trait IdentityStorage: Send + Sync {
    /// Batch-resolve (team_id, distinct_id) keys to persons on the primary.
    /// Returns a map keyed by (team_id, distinct_id); unresolved keys are absent.
    async fn resolve_distinct_ids(
        &self,
        keys: &[(i64, String)],
    ) -> StorageResult<HashMap<(i64, String), Person>>;

    /// Expand person ids to their live distinct id rows on the primary.
    /// With a per-person limit, identified ids survive the cut and the
    /// scan is capped for pathological persons — the same ordering
    /// contract as the replica's expansion.
    async fn get_distinct_ids_for_persons(
        &self,
        team_id: i64,
        person_ids: &[i64],
        limit_per_person: Option<i64>,
    ) -> StorageResult<Vec<DistinctIdMapping>>;

    /// Create person stubs (uuidv5 from team_id:distinct_id, version 0, empty
    /// properties) plus their distinct id rows in one multi-row transaction.
    /// Safe to race: unique conflicts resolve per row to the winner instead of
    /// erroring, so one key's race never fails the rest of the batch.
    ///
    /// Callers must dedupe stubs by (team_id, distinct_id); duplicate keys in
    /// one call have unspecified per-row outcomes. Outcomes are in stub order.
    async fn create_person_stubs(&self, stubs: &[PersonStub]) -> StorageResult<Vec<StubOutcome>>;

    /// Attach personless distinct ids to a live person with plain mapping
    /// inserts. Live mappings are never repointed (`AlreadyMapped`); an id
    /// absent from the result attached nothing. Callers dedupe.
    async fn attach_distinct_ids(
        &self,
        team_id: i64,
        person_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<HashMap<String, AttachOutcome>>;
}
