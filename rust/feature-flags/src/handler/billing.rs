use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    flags::{
        flag_analytics::{increment_request_count, is_billable_flag_key},
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
    if *context.state.config.skip_writes {
        return;
    }

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
/// Returns true if there are any non-filtered flags that are NOT survey or
/// product tour targeting flags. Deleted and inactive flags are already in
/// `filtered_out_flag_ids`, so no separate check is needed.
fn contains_billable_flags(filtered_flags: &FeatureFlagList) -> bool {
    filtered_flags.flags.iter().any(|flag| {
        !filtered_flags.filtered_out_flag_ids.contains(&flag.id) && is_billable_flag_key(&flag.key)
    })
}

/// Helper function to determine if usage should be recorded
/// This function is extracted for testing purposes
pub fn should_record_usage(filtered_flags: &FeatureFlagList) -> bool {
    contains_billable_flags(filtered_flags)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_analytics::{
        PRODUCT_TOUR_TARGETING_FLAG_PREFIX, SURVEY_TARGETING_FLAG_PREFIX,
    };
    use crate::flags::flag_models::{FeatureFlag, FlagFilters, FlagPropertyGroup};

    use std::collections::HashSet;

    static NEXT_FLAG_ID: std::sync::atomic::AtomicI32 = std::sync::atomic::AtomicI32::new(1);

    fn create_test_flag(key: &str) -> FeatureFlag {
        let id = NEXT_FLAG_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        FeatureFlag {
            id,
            team_id: 1,
            name: Some(key.to_string()),
            key: key.to_string(),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,

                holdout: None,
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
            ..Default::default()
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
            ..Default::default()
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
            ..Default::default()
        };

        // Should record usage when there's at least one regular flag, even with survey flags
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_empty_flags() {
        let flag_list = FeatureFlagList {
            flags: vec![],
            ..Default::default()
        };

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
            ..Default::default()
        };

        // Should record usage: first flag doesn't START with prefix, second does start with prefix
        // Since we use any(), and the first flag should return true for "!starts_with()", overall result should be true
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_filtered_out_flags_not_billable() {
        let disabled_flag = create_test_flag("regular_flag");

        let flag_list = FeatureFlagList {
            flags: vec![disabled_flag.clone()],
            filtered_out_flag_ids: HashSet::from([disabled_flag.id]),
            evaluation_metadata: None,
        };

        // Should NOT record usage when only filtered-out flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_mixed_active_and_filtered_out() {
        let disabled_flag = create_test_flag("disabled_flag");
        let active_flag = create_test_flag("active_flag");

        let flag_list = FeatureFlagList {
            flags: vec![disabled_flag.clone(), active_flag],
            filtered_out_flag_ids: HashSet::from([disabled_flag.id]),
            evaluation_metadata: None,
        };

        // Should record usage when at least one non-filtered, non-survey flag is present
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_filtered_out_survey_flag() {
        let disabled_survey_flag =
            create_test_flag(&format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));

        let flag_list = FeatureFlagList {
            flags: vec![disabled_survey_flag.clone()],
            filtered_out_flag_ids: HashSet::from([disabled_survey_flag.id]),
            evaluation_metadata: None,
        };

        // Should NOT record usage for filtered-out survey flags
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_only_filtered_out_and_survey_flags() {
        let disabled_flag = create_test_flag("disabled_flag");
        let survey_flag = create_test_flag(&format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));

        let flag_list = FeatureFlagList {
            flags: vec![disabled_flag.clone(), survey_flag],
            filtered_out_flag_ids: HashSet::from([disabled_flag.id]),
            evaluation_metadata: None,
        };

        // Should NOT record usage when only filtered-out and survey flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_only_product_tour_flags() {
        let tour_flag1 = create_test_flag(&format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1"));
        let tour_flag2 = create_test_flag(&format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour2"));

        let flag_list = FeatureFlagList {
            flags: vec![tour_flag1, tour_flag2],
            ..Default::default()
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
            ..Default::default()
        };

        // Should record usage when there's at least one regular flag, even with product tour flags
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_filtered_out_product_tour_flag() {
        let disabled_tour_flag =
            create_test_flag(&format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1"));

        let flag_list = FeatureFlagList {
            flags: vec![disabled_tour_flag.clone()],
            filtered_out_flag_ids: HashSet::from([disabled_tour_flag.id]),
            evaluation_metadata: None,
        };

        // Should NOT record usage for filtered-out product tour flags
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_only_survey_and_product_tour_flags() {
        let survey_flag = create_test_flag(&format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));
        let tour_flag = create_test_flag(&format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1"));

        let flag_list = FeatureFlagList {
            flags: vec![survey_flag, tour_flag],
            ..Default::default()
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
            ..Default::default()
        };

        // Should record usage: first flag doesn't START with prefix, second does start with prefix
        assert!(should_record_usage(&flag_list));
    }
}
