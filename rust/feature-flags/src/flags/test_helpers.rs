/* Test Helpers specifically for the flags module */

use std::sync::Arc;

use crate::{
    api::errors::{simplify_serde_error, FlagError},
    flags::{
        feature_flag_list::PreparedFlags,
        flag_models::{FeatureFlagList, HypercacheFlagsWrapper},
    },
};
use common_redis::Client as RedisClient;
use common_types::TeamId;

/// Generate the Django-compatible hypercache key for tests
/// Format: posthog:1:cache/teams/{team_id}/feature_flags/flags.json
/// The "posthog:1:" prefix matches Django's cache versioning
pub fn hypercache_test_key(team_id: TeamId) -> String {
    format!("posthog:1:cache/teams/{team_id}/feature_flags/flags.json")
}

/// Test-only helper to read feature flags directly from Redis (hypercache format)
///
/// Reads from hypercache key format: posthog:1:cache/teams/{team_id}/feature_flags/flags.json
/// Uses Django-compatible key format with version prefix.
/// Expects Pickle(JSON) format matching what Django writes.
/// Useful for testing cache behavior and verifying cache contents.
pub async fn get_flags_from_redis(
    client: Arc<dyn RedisClient + Send + Sync>,
    team_id: TeamId,
) -> Result<FeatureFlagList, FlagError> {
    let cache_key = hypercache_test_key(team_id);
    tracing::debug!(
        "Attempting to read flags from hypercache at key '{}'",
        cache_key
    );

    // Read raw bytes (zstd decompression handled by Redis client, pickle format)
    let raw_bytes = client.get_raw_bytes(cache_key.clone()).await?;

    // Deserialize pickle -> JSON string
    let json_string: String =
        serde_pickle::from_slice(&raw_bytes, Default::default()).map_err(|e| {
            tracing::error!(
                "Failed to deserialize pickle data for team {}: {}",
                team_id,
                e
            );
            FlagError::DataParsingErrorWithContext(format!(
                "Failed to deserialize pickle data for team {team_id}: {}",
                simplify_serde_error(&e.to_string())
            ))
        })?;

    // Parse JSON string -> HypercacheFlagsWrapper
    let wrapper: HypercacheFlagsWrapper = serde_json::from_str(&json_string).map_err(|e| {
        tracing::error!(
            "Failed to parse hypercache JSON for team {}: {}",
            team_id,
            e
        );
        FlagError::DataParsingErrorWithContext(format!(
            "Failed to parse hypercache JSON for team {team_id}: {}",
            simplify_serde_error(&e.to_string())
        ))
    })?;

    tracing::debug!(
        "Successfully read {} flags from hypercache at key '{}'",
        wrapper.flags.len(),
        cache_key
    );

    Ok(FeatureFlagList {
        flags: PreparedFlags::seal(wrapper.flags),
        evaluation_metadata: Arc::new(wrapper.evaluation_metadata),
        cohorts: wrapper.cohorts.map(Arc::from),
        ..Default::default()
    })
}

/// Test-only helper to write feature flags to hypercache (the new cache format)
///
/// Writes flags in Django-compatible format: Pickle(JSON)
/// at key: posthog:1:cache/teams/{team_id}/feature_flags/flags.json
///
/// This helper writes uncompressed Pickle(JSON) to match small payloads from Django
/// (data < 512 bytes). For larger payloads, Django writes Zstd(Pickle(JSON)), but
/// the Redis client's get_raw_bytes automatically decompresses such data.
pub async fn update_flags_in_hypercache(
    client: Arc<dyn RedisClient + Send + Sync>,
    team_id: TeamId,
    flags: &FeatureFlagList,
    ttl_seconds: Option<u64>,
) -> Result<(), FlagError> {
    let wrapper = HypercacheFlagsWrapper {
        flags: flags.flags.to_vec(),
        evaluation_metadata: (*flags.evaluation_metadata).clone(),
        cohorts: flags.cohorts.as_ref().map(|c| c.to_vec()),
    };

    // Match Django's format: JSON string -> Pickle
    // (Redis client handles zstd decompression automatically, so we don't compress)
    let json_string = serde_json::to_string(&wrapper).map_err(|e| {
        tracing::error!(
            "Failed to serialize {} flags for team {} (hypercache): {}",
            flags.flags.len(),
            team_id,
            e
        );
        FlagError::DataParsingErrorWithContext(format!(
            "Failed to serialize flags for team {team_id}: {}",
            simplify_serde_error(&e.to_string())
        ))
    })?;

    let pickled_bytes = serde_pickle::to_vec(&json_string, Default::default()).map_err(|e| {
        tracing::error!(
            "Failed to pickle {} flags for team {}: {}",
            flags.flags.len(),
            team_id,
            e
        );
        FlagError::DataParsingErrorWithContext(format!(
            "Failed to pickle flags for team {team_id}: {}",
            simplify_serde_error(&e.to_string())
        ))
    })?;

    let cache_key = hypercache_test_key(team_id);
    let etag_key = format!("{cache_key}:etag");
    let etag = common_hypercache::writer::compute_etag(&json_string);

    tracing::info!(
        "Writing flags to hypercache at key '{}' (pickle format): {} flags",
        cache_key,
        flags.flags.len()
    );

    client
        .set_bytes(cache_key, pickled_bytes, ttl_seconds)
        .await
        .map_err(|e| {
            tracing::error!("Failed to update hypercache for project {}: {}", team_id, e);
            FlagError::Internal(format!("Failed to update cache: {e}"))
        })?;

    // Mirror Django's `HyperCache._set_cache_value_redis` (enable_etag=True),
    // which writes the etag in the same `set_many` pipeline as the payload.
    // FlagService now keys the in-memory cache on this etag, so test setups
    // that bypass the real HyperCache writer must still publish it for the
    // version-key fast path to be exercised end-to-end.
    let etag_write = match ttl_seconds {
        Some(ttl) => client.setex(etag_key, etag, ttl).await,
        None => client.set(etag_key, etag).await,
    };
    etag_write.map_err(|e| {
        tracing::error!(
            "Failed to write hypercache etag for team {}: {}",
            team_id,
            e
        );
        FlagError::Internal(format!("Failed to write etag: {e}"))
    })?;

    Ok(())
}
