pub mod error;
pub mod postgres;
pub mod types;

use std::collections::HashMap;

use async_trait::async_trait;

pub use error::{StorageError, StorageResult};
pub use types::{Person, PersonIdentity, PersonStub, StubOutcome};

pub const DB_QUERY_DURATION: &str = "personhog_identity_db_query_duration_ms";

/// Storage operations for the identity service. Writes and strong resolution
/// run on the Postgres primary — the get-or-create path must never see stale
/// mappings. Eventual resolution (`resolve_identities`) runs on the replica
/// pool for the hot per-event read path.
#[async_trait]
pub trait IdentityStorage: Send + Sync {
    /// Batch-resolve (team_id, distinct_id) keys to persons on the primary.
    /// Returns a map keyed by (team_id, distinct_id); unresolved keys are absent.
    async fn resolve_distinct_ids(
        &self,
        keys: &[(i64, String)],
    ) -> StorageResult<HashMap<(i64, String), Person>>;

    /// Batch-resolve (team_id, distinct_id) keys to identity columns on the
    /// replica pool (eventually consistent). Returns a map keyed by
    /// (team_id, distinct_id); unresolved keys are absent.
    async fn resolve_identities(
        &self,
        keys: &[(i64, String)],
    ) -> StorageResult<HashMap<(i64, String), PersonIdentity>>;

    /// Create person stubs (uuidv5 from team_id:distinct_id, version 0, empty
    /// properties) plus their distinct id rows in one multi-row transaction.
    /// Safe to race: unique conflicts resolve per row to the winner instead of
    /// erroring, so one key's race never fails the rest of the batch.
    ///
    /// Callers must dedupe stubs by (team_id, distinct_id); duplicate keys in
    /// one call have unspecified per-row outcomes. Outcomes are in stub order.
    async fn create_person_stubs(&self, stubs: &[PersonStub]) -> StorageResult<Vec<StubOutcome>>;
}
