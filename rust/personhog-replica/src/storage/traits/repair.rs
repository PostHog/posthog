use async_trait::async_trait;
use uuid::Uuid;

use crate::storage::error::StorageResult;
use crate::storage::types::{
    DistinctIdWrite, DistinctIdWriteResult, RaiseResult, RestoreResult, RestoredPerson,
};

/// Writes for the person consistency repair. Each runs in one primary transaction, fails fast on a
/// held row lock, and only raises versions, so a retry after an unknown commit is a no-op.
#[async_trait]
pub trait PersonRepair: Send + Sync {
    /// Raise live persons to at least their min version, under lifecycle marks on them; tombstoned
    /// and missing persons are left unchanged. `floors` must not repeat a uuid. Results keep
    /// request order.
    async fn raise_person_version_floors(
        &self,
        team_id: i64,
        floors: &[(Uuid, i64)],
    ) -> StorageResult<Vec<RaiseResult>>;

    /// Insert each person whose uuid has no row, live or tombstoned. Results keep request order.
    async fn restore_persons(
        &self,
        team_id: i64,
        persons: &[RestoredPerson],
    ) -> StorageResult<Vec<RestoreResult>>;

    /// Apply each mapping write only while the row is in the state the write expects, under
    /// lifecycle marks on the persons written. `writes` must not repeat a distinct id. Results
    /// keep request order.
    async fn write_distinct_ids(
        &self,
        team_id: i64,
        writes: &[DistinctIdWrite],
    ) -> StorageResult<Vec<DistinctIdWriteResult>>;
}
