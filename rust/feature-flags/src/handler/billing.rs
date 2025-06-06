use crate::{
    api::{
        errors::FlagError,
        types::{ConfigResponse, FlagsResponse},
    },
    flags::{
        flag_analytics::{increment_request_count, SURVEY_TARGETING_FLAG_PREFIX},
        flag_models::FeatureFlagList,
        flag_request::FlagRequestType,
    },
};
use common_metrics::inc;
use limiters::redis::ServiceName;
use std::collections::HashMap;

use super::types::RequestContext;

pub async fn check_limits(
    context: &RequestContext,
    verified_token: &str,
) -> Result<Option<FlagsResponse>, FlagError> {
    let billing_limited = context
        .state
        .billing_limiter
        .is_limited(verified_token)
        .await;

    if billing_limited {
        return Ok(Some(FlagsResponse {
            errors_while_computing_flags: false,
            flags: HashMap::new(),
            quota_limited: Some(vec![ServiceName::FeatureFlags.as_string()]),
            request_id: context.request_id,
            config: ConfigResponse::default(),
        }));
    }
    Ok(None)
}

pub async fn record_usage(
    context: &RequestContext,
    filtered_flags: &FeatureFlagList,
    team_id: i32,
) {
    if filtered_flags
        .flags
        .iter()
        .any(|f| !f.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX))
    {
        if let Err(e) = increment_request_count(
            context.state.redis.clone(),
            team_id,
            1,
            FlagRequestType::Decide,
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

/// Helper function to determine if usage should be recorded
/// This function is extracted for testing purposes
pub fn should_record_usage(filtered_flags: &FeatureFlagList) -> bool {
    filtered_flags
        .flags
        .iter()
        .any(|f| !f.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX))
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
            ensure_experience_continuity: false,
            version: Some(1),
        }
    }

    #[test]
    fn test_should_record_usage_only_survey_flags() {
        let survey_flag1 = create_test_flag(&format!("{}survey1", SURVEY_TARGETING_FLAG_PREFIX));
        let survey_flag2 = create_test_flag(&format!("{}survey2", SURVEY_TARGETING_FLAG_PREFIX));

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
        let survey_flag = create_test_flag(&format!("{}survey1", SURVEY_TARGETING_FLAG_PREFIX));
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
            create_test_flag(&format!("prefix-{}middle", SURVEY_TARGETING_FLAG_PREFIX));
        // Test flag that starts with prefix but has extra content
        let survey_flag_with_suffix = create_test_flag(&format!(
            "{}survey-with-suffix",
            SURVEY_TARGETING_FLAG_PREFIX
        ));

        let flag_list = FeatureFlagList {
            flags: vec![flag_with_prefix_inside, survey_flag_with_suffix],
        };

        // Should record usage: first flag doesn't START with prefix, second does start with prefix
        // Since we use any(), and the first flag should return true for "!starts_with()", overall result should be true
        assert!(should_record_usage(&flag_list));
    }
}
