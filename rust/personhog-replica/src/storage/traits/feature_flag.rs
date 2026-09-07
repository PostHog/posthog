use async_trait::async_trait;

use crate::storage::error::StorageResult;
use crate::storage::postgres::ConsistencyLevel;
use crate::storage::types::{
    HashKeyOverrideContext, HashKeyOverrideCursor, HashKeyOverrideDeleteBatch,
};

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

    /// Upsert hash key overrides by resolving distinct_ids to person_ids server-side.
    ///
    /// Resolves all `distinct_ids` to person_ids via `posthog_persondistinctid`,
    /// cross-joins with `feature_flag_keys`, and inserts overrides with the given
    /// `hash_key`. Returns the number of inserted records.
    async fn upsert_hash_key_overrides(
        &self,
        team_id: i64,
        distinct_ids: &[String],
        feature_flag_keys: &[String],
        hash_key: &str,
    ) -> StorageResult<i64>;

    /// Delete up to `batch_size` hash key overrides across the specified teams.
    ///
    /// Callers loop until `deleted_count` is 0, and pass the returned cursor back on
    /// the next call. The cursor keeps each batch scanning forward along the
    /// (team_id, person_id, feature_flag_key) unique index. Without it the scan
    /// restarts at the start of the team's index range every batch, and walks the
    /// dead entries of the rows that earlier batches deleted.
    async fn delete_hash_key_overrides_by_teams(
        &self,
        team_ids: &[i64],
        batch_size: i64,
        cursor: Option<&HashKeyOverrideCursor>,
    ) -> StorageResult<HashKeyOverrideDeleteBatch>;
}
