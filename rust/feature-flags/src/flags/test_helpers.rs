/* Test Helpers specifically for the flags module */

use serde_json::Value;
use std::sync::Arc;

use crate::{
    api::errors::FlagError,
    flags::flag_models::{
        FeatureFlag, FeatureFlagList, FlagFilters, FlagPropertyGroup, HypercacheFlagsWrapper,
    },
    properties::property_models::{OperatorType, PropertyFilter, PropertyType},
};
use common_redis::Client as RedisClient;
use common_types::TeamId;

/// Generate the Django-compatible hypercache key for tests
/// Format: posthog:1:cache/teams/{team_id}/feature_flags/flags.json
/// The "posthog:1:" prefix matches Django's cache versioning
pub fn hypercache_test_key(team_id: TeamId) -> String {
    format!("posthog:1:cache/teams/{team_id}/feature_flags/flags.json")
}

pub fn create_simple_property_filter(
    key: &str,
    prop_type: PropertyType,
    operator: OperatorType,
) -> PropertyFilter {
    PropertyFilter {
        key: key.to_string(),
        value: Some(Value::String("value".to_string())),
        operator: Some(operator),
        group_type_index: None,
        negation: None,
        prop_type,
    }
}

pub fn create_simple_flag_filters(groups: Vec<FlagPropertyGroup>) -> FlagFilters {
    FlagFilters {
        groups,
        multivariate: None,
        aggregation_group_type_index: None,
        payloads: None,
        super_groups: None,
        holdout_groups: None,
    }
}

pub fn create_simple_flag_property_group(
    properties: Vec<PropertyFilter>,
    rollout_percentage: f64,
) -> FlagPropertyGroup {
    FlagPropertyGroup {
        properties: Some(properties),
        rollout_percentage: Some(rollout_percentage),
        variant: None,
    }
}

pub fn create_simple_flag(properties: Vec<PropertyFilter>, rollout_percentage: f64) -> FeatureFlag {
    FeatureFlag {
        filters: create_simple_flag_filters(vec![create_simple_flag_property_group(
            properties,
            rollout_percentage,
        )]),
        id: 1,
        team_id: 1,
        name: Some("Flag 1".to_string()),
        key: "flag_1".to_string(),
        deleted: false,
        active: true,
        ensure_experience_continuity: Some(false),
        version: Some(1),
        evaluation_runtime: Some("all".to_string()),
        evaluation_tags: None,
        bucketing_identifier: None,
    }
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
            FlagError::RedisDataParsingError
        })?;

    // Parse JSON string -> HypercacheFlagsWrapper
    let wrapper: HypercacheFlagsWrapper = serde_json::from_str(&json_string).map_err(|e| {
        tracing::error!(
            "Failed to parse hypercache JSON for team {}: {}",
            team_id,
            e
        );
        FlagError::RedisDataParsingError
    })?;

    tracing::debug!(
        "Successfully read {} flags from hypercache at key '{}'",
        wrapper.flags.len(),
        cache_key
    );

    Ok(FeatureFlagList {
        flags: wrapper.flags,
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
        flags: flags.flags.clone(),
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
        FlagError::RedisDataParsingError
    })?;

    let pickled_bytes = serde_pickle::to_vec(&json_string, Default::default()).map_err(|e| {
        tracing::error!(
            "Failed to pickle {} flags for team {}: {}",
            flags.flags.len(),
            team_id,
            e
        );
        FlagError::RedisDataParsingError
    })?;

    let cache_key = hypercache_test_key(team_id);

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
            FlagError::CacheUpdateError
        })?;

    Ok(())
}
