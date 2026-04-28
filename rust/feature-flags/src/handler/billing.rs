use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    flags::{
        flag_analytics::{increment_request_count, is_billable_flag_key},
        flag_models::FeatureFlagList,
        flag_request::FlagRequestType,
    },
    metrics::consts::FLAG_BILLING_INCREMENT_TIME,
};
use common_metrics::{histogram, inc};
use common_redis::CustomRedisError;
use limiters::redis::ServiceName;
use std::collections::HashMap;
use std::time::Instant;

use super::canonical_log::with_canonical_log;
use super::types::{Library, RequestContext};

/// Emit the `flags_billing_increment_time_ms` histogram for a completed
/// `increment_request_count` call, bucketing the Redis result into
/// `outcome="ok" | "timeout" | "error"` to isolate the happy path from
/// Redis timeouts.
pub fn record_billing_increment_timing(result: &Result<(), CustomRedisError>, elapsed_ms: u64) {
    let outcome = match result {
        Ok(()) => "ok",
        Err(CustomRedisError::Timeout) => "timeout",
        Err(_) => "error",
    };
    histogram(
        FLAG_BILLING_INCREMENT_TIME,
        &[("outcome".to_string(), outcome.to_string())],
        elapsed_ms as f64,
    );
}

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
        let start = Instant::now();
        let result = increment_request_count(
            context.state.redis_client.clone(),
            team_id,
            1,
            FlagRequestType::Decide,
            Some(library),
        )
        .await;
        let elapsed_ms = start.elapsed().as_millis() as u64;

        record_billing_increment_timing(&result, elapsed_ms);
        with_canonical_log(|log| log.billing_duration_ms = Some(elapsed_ms));

        if let Err(e) = result {
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
    use crate::flags::flag_models::FeatureFlag;
    use crate::mock;
    use crate::utils::mock::MockInto;

    use std::collections::HashSet;

    #[test]
    fn test_should_record_usage_only_survey_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1")),
            mock!(FeatureFlag, id: 2, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey2")),
        ]
        .mock_into();

        // Should NOT record usage when only survey flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_only_regular_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: "regular_flag_1".mock_into()),
            mock!(FeatureFlag, id: 2, key: "feature_flag_2".mock_into()),
        ]
        .mock_into();

        // Should record usage when only regular flags are present
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_mixed_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1")),
            mock!(FeatureFlag, id: 2, key: "regular_flag".mock_into()),
        ]
        .mock_into();

        // Should record usage when there's at least one regular flag, even with survey flags
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_empty_flags() {
        let flag_list: FeatureFlagList = vec![].mock_into();

        // Should NOT record usage when there are no flags at all
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_flag_key_edge_cases() {
        // Test flag that contains the prefix but doesn't start with it
        // Test flag that starts with prefix but has extra content
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("prefix-{SURVEY_TARGETING_FLAG_PREFIX}middle")),
            mock!(FeatureFlag, id: 2, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey-with-suffix")),
        ]
        .mock_into();

        // Should record usage: first flag doesn't START with prefix, second does start with prefix
        // Since we use any(), and the first flag should return true for "!starts_with()", overall result should be true
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_filtered_out_flags_not_billable() {
        let disabled_flag = mock!(FeatureFlag, id: 1, key: "regular_flag".mock_into());

        let flag_list = mock!(FeatureFlagList,
            flags: vec![disabled_flag.clone()],
            filtered_out_flag_ids: HashSet::from([disabled_flag.id])
        );

        // Should NOT record usage when only filtered-out flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_mixed_active_and_filtered_out() {
        let disabled_flag = mock!(FeatureFlag, id: 1, key: "disabled_flag".mock_into());
        let active_flag = mock!(FeatureFlag, id: 2, key: "active_flag".mock_into());

        let flag_list = mock!(FeatureFlagList,
            flags: vec![disabled_flag.clone(), active_flag],
            filtered_out_flag_ids: HashSet::from([disabled_flag.id])
        );

        // Should record usage when at least one non-filtered, non-survey flag is present
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_filtered_out_survey_flag() {
        let disabled_survey_flag =
            mock!(FeatureFlag, id: 1, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));

        let flag_list = mock!(FeatureFlagList,
            flags: vec![disabled_survey_flag.clone()],
            filtered_out_flag_ids: HashSet::from([disabled_survey_flag.id])
        );

        // Should NOT record usage for filtered-out survey flags
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_only_filtered_out_and_survey_flags() {
        let disabled_flag = mock!(FeatureFlag, id: 1, key: "disabled_flag".mock_into());
        let survey_flag =
            mock!(FeatureFlag, id: 2, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));

        let flag_list = mock!(FeatureFlagList,
            flags: vec![disabled_flag.clone(), survey_flag],
            filtered_out_flag_ids: HashSet::from([disabled_flag.id])
        );

        // Should NOT record usage when only filtered-out and survey flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_only_product_tour_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1")),
            mock!(FeatureFlag, id: 2, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour2")),
        ]
        .mock_into();

        // Should NOT record usage when only product tour flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_product_tour_mixed_with_regular_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1")),
            mock!(FeatureFlag, id: 2, key: "regular_flag".mock_into()),
        ]
        .mock_into();

        // Should record usage when there's at least one regular flag, even with product tour flags
        assert!(should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_filtered_out_product_tour_flag() {
        let disabled_tour_flag =
            mock!(FeatureFlag, id: 1, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1"));

        let flag_list = mock!(FeatureFlagList,
            flags: vec![disabled_tour_flag.clone()],
            filtered_out_flag_ids: HashSet::from([disabled_tour_flag.id])
        );

        // Should NOT record usage for filtered-out product tour flags
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_only_survey_and_product_tour_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1")),
            mock!(FeatureFlag, id: 2, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1")),
        ]
        .mock_into();

        // Should NOT record usage when only survey and product tour flags are present
        assert!(!should_record_usage(&flag_list));
    }

    #[test]
    fn test_should_record_usage_product_tour_flag_key_edge_cases() {
        // Test flag that contains the prefix but doesn't start with it
        // Test flag that starts with prefix but has extra content
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("prefix-{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}middle")),
            mock!(FeatureFlag, id: 2, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour-with-suffix")),
        ]
        .mock_into();

        // Should record usage: first flag doesn't START with prefix, second does start with prefix
        assert!(should_record_usage(&flag_list));
    }
}
