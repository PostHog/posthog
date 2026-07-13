use std::sync::Arc;
use std::time::Duration;

use moka::future::Cache;

use crate::integrations::model::DecryptedIntegration;

/// In-process cache of decrypted integrations, keyed by integration id.
///
/// Decrypted values live ONLY here (never in Redis), so secrets never leave the pod and hot
/// paths avoid re-decrypting. A short TTL is the entire staleness story in v1 — there is no push
/// invalidation. Keying by id (globally unique) is team-safe because `team_id` travels on the
/// cached value and the service filters on it after every lookup.
pub type CredentialCache = Cache<i64, Arc<DecryptedIntegration>>;

pub fn build(ttl_seconds: u64, max_capacity: u64) -> CredentialCache {
    Cache::builder()
        .time_to_live(Duration::from_secs(ttl_seconds))
        .max_capacity(max_capacity)
        .build()
}
