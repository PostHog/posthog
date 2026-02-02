use async_trait::async_trait;

use crate::storage::error::StorageResult;
use crate::storage::postgres::ConsistencyLevel;
use crate::storage::types::{HashKeyOverrideContext, HashKeyOverrideInput};

/// Feature flag hash key override operations
#[async_trait]
pub trait FeatureFlagStorage: Send + Sync {
    /// Gets the context needed for hash key override decisions.
    ///
    /// This resolves distinct IDs to person IDs and returns existing hash key
    /// override information for each person.
    ///
    /// When `check_person_exists` is true, only returns results for persons that
    /// exist in the posthog_person table. This uses an EXISTS subquery against
    /// the person table.
    ///
    /// ## Consistency
    ///
    /// The `consistency` parameter controls which database pool is used:
    /// - `Strong`: Uses the primary database, guaranteeing read-after-write consistency.
    ///   This is important when the caller has just written hash key overrides and needs
    ///   to read them back immediately.
    /// - `Eventual`: Uses the replica database, which may have replication lag.
    ///
    /// Note: When the personhog-leader service is implemented, the person table will be
    /// cached on the leader pods. At that point, strong consistency for person data will
    /// require routing to the leader service, not the primary database. The current
    /// implementation queries the primary database directly as a temporary solution.
    async fn get_hash_key_override_context(
        &self,
        team_id: i64,
        distinct_ids: &[String],
        check_person_exists: bool,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<HashKeyOverrideContext>>;

    /// Batch upsert hash key overrides. Returns the number of inserted records.
    ///
    /// All overrides in a batch share the same `hash_key`, which is used for
    /// experience continuity - ensuring consistent flag values when a user
    /// logs in with a new distinct_id.
    async fn upsert_hash_key_overrides(
        &self,
        team_id: i64,
        overrides: &[HashKeyOverrideInput],
        hash_key: &str,
    ) -> StorageResult<i64>;

    /// Delete all hash key overrides for the specified teams. Returns the number of deleted records.
    async fn delete_hash_key_overrides_by_teams(&self, team_ids: &[i64]) -> StorageResult<i64>;
}
