use async_trait::async_trait;
use uuid::Uuid;

use crate::storage::error::StorageResult;
use crate::storage::types::RaiseResult;

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
}
