use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    flags::{
        flag_analytics::{
            increment_request_count, PRODUCT_TOUR_TARGETING_FLAG_PREFIX,
            SURVEY_TARGETING_FLAG_PREFIX,
        },
        flag_models::FeatureFlagList,
        flag_request::FlagRequestType,
    },
};
use common_metrics::inc;
use limiters::redis::ServiceName;
use std::collections::HashMap;

use super::types::{Library, RequestContext};

pub async fn check_limits(
    context: &RequestContext,
    verified_token: &str,
) -> Result<Option<FlagsResponse>, FlagError> {
    let billing_limited = context
        .state
        .feature_flags_billing_limiter
        .is_limited(verified_token)
        .await;

    if billing_limited {
        return Ok(Some(FlagsResponse::new(
            false,
            HashMap::new(),
            Some(vec![ServiceName::FeatureFlags.as_string()]),
            context.request_id,
        )));
    }
    Ok(None)
}

/// Records usage metrics for feature flag requests.
///
/// Only increments billing counters if there are billable flags present.
/// Survey and product tour targeting flags are not billable.
///
/// The `library` parameter is passed in to avoid duplicate detection - it should
/// be detected once at the start of request processing and reused.
pub async fn record_usage(
    context: &RequestContext,
    filtered_flags: &FeatureFlagList,
    team_id: i32,
    library: Library,
) {
    let has_billable_flags = contains_billable_flags(filtered_flags);

    if has_billable_flags {
        if let Err(e) = increment_request_count(
            context.state.redis_client.clone(),
            team_id,
            1,
            FlagRequestType::Decide,
            Some(library),
        )
        .await
        {
            inc(
                "flag_request_redis_error",
                &[("error".to_string(), e.to_string())],
                1,
            );
        }
    }
}

/// Checks if the flag list contains any billable flags.
///
/// Returns true if there are any flags that are both active and NOT survey or
/// product tour targeting flags.
fn contains_billable_flags(filtered_flags: &FeatureFlagList) -> bool {
    filtered_flags.flags.iter().any(is_billable_flag)
}

/// Determines if a flag is billable based on its key and active status.
///
/// Returns true for active regular feature flags, false for survey/product tour targeting flags or disabled flags.
fn is_billable_flag(flag: &crate::flags::flag_models::FeatureFlag) -> bool {
    flag.active
        && !flag.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX)
        && !flag.key.starts_with(PRODUCT_TOUR_TARGETING_FLAG_PREFIX)
}

/// Helper function to determine if usage should be recorded
/// This function is extracted for testing purposes
pub fn should_record_usage(filtered_flags: &FeatureFlagList) -> bool {
    contains_billable_flags(filtered_flags)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_models::{FeatureFlag, FlagFilters, FlagPropertyGroup};

    fn create_test_flag(key: &str) -> FeatureFlag {
        FeatureFlag {
            id: 1,
            team_id: 1,
            name: Some(key.to_string()),
            key: key.to_string(),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        }
    }

    #[test]
    fn test_should_record_usage_only_survey_flags() {
        let survey_flag1 = create_test_flag(&format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));
        let survey_flag2 = create_test_flag(&format!("{SURVEY_TARGETING_FLAG_PREFIX}survey2"));

        let flag_list = FeatureFlagList {
            flags: vec![survey_flag1, survey_flag2],
        };

        // Should NOT record usage when only survey flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_only_regular_flags() {
        let regular_flag1 = create_test_flag("regular_flag_1");
        let regular_flag2 = create_test_flag("feature_flag_2");

        let flag_list = FeatureFlagList {
            flags: vec![regular_flag1, regular_flag2],
        };

        // Should record usage when only regular flags are present
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_mixed_flags() {
        let survey_flag = create_test_flag(&format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));
        let regular_flag = create_test_flag("regular_flag");

        let flag_list = FeatureFlagList {
            flags: vec![survey_flag, regular_flag],
        };

        // Should record usage when there's at least one regular flag, even with survey flags
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_empty_flags() {
        let flag_list = FeatureFlagList { flags: vec![] };

        // Should NOT record usage when there are no flags at all
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_flag_key_edge_cases() {
        // Test flag that contains the prefix but doesn't start with it
        let flag_with_prefix_inside =
            create_test_flag(&format!("prefix-{SURVEY_TARGETING_FLAG_PREFIX}middle"));
        // Test flag that starts with prefix but has extra content
        let survey_flag_with_suffix =
            create_test_flag(&format!("{SURVEY_TARGETING_FLAG_PREFIX}survey-with-suffix",));

        let flag_list = FeatureFlagList {
            flags: vec![flag_with_prefix_inside, survey_flag_with_suffix],
        };

        // Should record usage: first flag doesn't START with prefix, second does start with prefix
        // Since we use any(), and the first flag should return true for "!starts_with()", overall result should be true
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_disabled_flags_not_billable() {
        let mut disabled_flag = create_test_flag("regular_flag");
        disabled_flag.active = false;

        let flag_list = FeatureFlagList {
            flags: vec![disabled_flag],
        };

        // Should NOT record usage when only disabled flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_mixed_active_and_disabled() {
        let mut disabled_flag = create_test_flag("disabled_flag");
        disabled_flag.active = false;
        let active_flag = create_test_flag("active_flag");

        let flag_list = FeatureFlagList {
            flags: vec![disabled_flag, active_flag],
        };

        // Should record usage when at least one active, non-survey flag is present
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_disabled_survey_flag() {
        let mut disabled_survey_flag =
            create_test_flag(&format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));
        disabled_survey_flag.active = false;

        let flag_list = FeatureFlagList {
            flags: vec![disabled_survey_flag],
        };

        // Should NOT record usage for disabled survey flags
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_only_disabled_and_survey_flags() {
        let mut disabled_flag = create_test_flag("disabled_flag");
        disabled_flag.active = false;
        let survey_flag = create_test_flag(&format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));

        let flag_list = FeatureFlagList {
            flags: vec![disabled_flag, survey_flag],
        };

        // Should NOT record usage when only disabled and survey flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_only_product_tour_flags() {
        let tour_flag1 = create_test_flag(&format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1"));
        let tour_flag2 = create_test_flag(&format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour2"));

        let flag_list = FeatureFlagList {
            flags: vec![tour_flag1, tour_flag2],
        };

        // Should NOT record usage when only product tour flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_product_tour_mixed_with_regular_flags() {
        let tour_flag = create_test_flag(&format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1"));
        let regular_flag = create_test_flag("regular_flag");

        let flag_list = FeatureFlagList {
            flags: vec![tour_flag, regular_flag],
        };

        // Should record usage when there's at least one regular flag, even with product tour flags
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_disabled_product_tour_flag() {
        let mut disabled_tour_flag =
            create_test_flag(&format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1"));
        disabled_tour_flag.active = false;

        let flag_list = FeatureFlagList {
            flags: vec![disabled_tour_flag],
        };

        // Should NOT record usage for disabled product tour flags
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_only_survey_and_product_tour_flags() {
        let survey_flag = create_test_flag(&format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));
        let tour_flag = create_test_flag(&format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1"));

        let flag_list = FeatureFlagList {
            flags: vec![survey_flag, tour_flag],
        };

        // Should NOT record usage when only survey and product tour flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_product_tour_flag_key_edge_cases() {
        // Test flag that contains the prefix but doesn't start with it
        let flag_with_prefix_inside = create_test_flag(&format!(
            "prefix-{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}middle"
        ));
        // Test flag that starts with prefix but has extra content
        let tour_flag_with_suffix = create_test_flag(&format!(
            "{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour-with-suffix"
        ));

        let flag_list = FeatureFlagList {
            flags: vec![flag_with_prefix_inside, tour_flag_with_suffix],
        };

        // Should record usage: first flag doesn't START with prefix, second does start with prefix
        assert!(should_record_usage(&flag_list));
    }
}
