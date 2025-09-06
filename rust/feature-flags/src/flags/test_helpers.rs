/* Test Helpers specifically for the flags module */

use serde_json::Value;

use crate::{
    flags::flag_models::{FeatureFlag, FlagFilters, FlagPropertyGroup},
    properties::property_models::{OperatorType, PropertyFilter, PropertyType},
};

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
