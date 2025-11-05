/* Test Helpers specifically for the flags module */

use serde_json::Value;
use std::sync::Arc;

use crate::{
    api::errors::FlagError,
    flags::flag_models::{
        FeatureFlag, FeatureFlagList, FlagFilters, FlagPropertyGroup, TEAM_FLAGS_CACHE_PREFIX,
    },
    properties::property_models::{OperatorType, PropertyFilter, PropertyType},
};
use common_redis::Client as RedisClient;
use common_types::ProjectId;

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
    }
}

/// Test-only helper to read feature flags directly from Redis
///
/// This bypasses the ReadThroughCache and directly reads from Redis,
/// useful for testing cache behavior and verifying cache contents.
pub async fn get_flags_from_redis(
    client: Arc<dyn RedisClient + Send + Sync>,
    project_id: ProjectId,
) -> Result<FeatureFlagList, FlagError> {
    tracing::debug!(
        "Attempting to read flags from Redis at key '{}{}'",
        TEAM_FLAGS_CACHE_PREFIX,
        project_id
    );

    let serialized_flags = client
        .get(format!("{TEAM_FLAGS_CACHE_PREFIX}{project_id}"))
        .await?;

    let flags_list: Vec<FeatureFlag> = serde_json::from_str(&serialized_flags).map_err(|e| {
        tracing::error!(
            "failed to parse data to flags list for project {}: {}",
            project_id,
            e
        );
        FlagError::RedisDataParsingError
    })?;

    tracing::debug!(
        "Successfully read {} flags from Redis at key '{}{}'",
        flags_list.len(),
        TEAM_FLAGS_CACHE_PREFIX,
        project_id
    );

    Ok(FeatureFlagList { flags: flags_list })
}
