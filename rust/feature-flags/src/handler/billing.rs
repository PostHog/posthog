use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    flags::{
        flag_analytics::is_billable_flag_key, flag_models::FeatureFlagList,
        flag_request::FlagRequestType,
    },
};
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

/// Records usage metrics for feature flag requests. Survey and product tour
/// targeting flags are not billable. The `library` parameter is detected
/// once at the start of request processing and reused. The aggregator's
/// periodic flush is the only writer of these counts —
/// `flags_billing_pending_records` and
/// `flags_billing_seconds_since_successful_flush` are billing-critical
/// signals.
pub fn record_usage(
    context: &RequestContext,
    filtered_flags: &FeatureFlagList,
    team_id: i32,
    library: Library,
    is_internal: bool,
) {
    if should_record_billable_request(
        *context.state.config.skip_writes,
        is_internal,
        filtered_flags,
    ) {
        context
            .state
            .billing_aggregator
            .record(team_id, FlagRequestType::Decide, Some(library));
    }
}

/// Predicate gate for `record_usage`. Extracted so the predicate ordering
/// (`skip_writes` → internal-request → billable-flag) can be unit-tested
/// without standing up a full `RequestContext`. Internal requests must
/// short-circuit before the billable-flag check so an internal request with
/// billable flags doesn't slip past.
pub(crate) fn should_record_billable_request(
    skip_writes: bool,
    is_internal: bool,
    filtered_flags: &FeatureFlagList,
) -> bool {
    !skip_writes && !is_internal && contains_billable_flags(filtered_flags)
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::feature_flag_list::PreparedFlags;
    use crate::flags::flag_analytics::{
        PRODUCT_TOUR_TARGETING_FLAG_PREFIX, SURVEY_TARGETING_FLAG_PREFIX,
    };
    use crate::flags::flag_models::FeatureFlag;
    use crate::mock;
    use crate::utils::mock::MockInto;

    use std::collections::HashSet;

    #[test]
    fn test_contains_billable_flags_only_survey_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1")),
            mock!(FeatureFlag, id: 2, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey2")),
        ]
        .mock_into();

        // Should NOT record usage when only survey flags are present
        assert!(!contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_only_regular_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: "regular_flag_1".mock_into()),
            mock!(FeatureFlag, id: 2, key: "feature_flag_2".mock_into()),
        ]
        .mock_into();

        // Should record usage when only regular flags are present
        assert!(contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_mixed_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1")),
            mock!(FeatureFlag, id: 2, key: "regular_flag".mock_into()),
        ]
        .mock_into();

        // Should record usage when there's at least one regular flag, even with survey flags
        assert!(contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_empty_flags() {
        let flag_list: FeatureFlagList = vec![].mock_into();

        // Should NOT record usage when there are no flags at all
        assert!(!contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_flag_key_edge_cases() {
        // Test flag that contains the prefix but doesn't start with it
        // Test flag that starts with prefix but has extra content
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("prefix-{SURVEY_TARGETING_FLAG_PREFIX}middle")),
            mock!(FeatureFlag, id: 2, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey-with-suffix")),
        ]
        .mock_into();

        // Should record usage: first flag doesn't START with prefix, second does start with prefix
        // Since we use any(), and the first flag should return true for "!starts_with()", overall result should be true
        assert!(contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_filtered_out_flags_not_billable() {
        let disabled_flag = mock!(FeatureFlag, id: 1, key: "regular_flag".mock_into());

        let flag_list = mock!(FeatureFlagList,
            flags: PreparedFlags::seal(vec![disabled_flag.clone()]),
            filtered_out_flag_ids: HashSet::from([disabled_flag.id])
        );

        // Should NOT record usage when only filtered-out flags are present
        assert!(!contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_mixed_active_and_filtered_out() {
        let disabled_flag = mock!(FeatureFlag, id: 1, key: "disabled_flag".mock_into());
        let active_flag = mock!(FeatureFlag, id: 2, key: "active_flag".mock_into());

        let flag_list = mock!(FeatureFlagList,
            flags: PreparedFlags::seal(vec![disabled_flag.clone(), active_flag]),
            filtered_out_flag_ids: HashSet::from([disabled_flag.id])
        );

        // Should record usage when at least one non-filtered, non-survey flag is present
        assert!(contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_filtered_out_survey_flag() {
        let disabled_survey_flag =
            mock!(FeatureFlag, id: 1, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));

        let flag_list = mock!(FeatureFlagList,
            flags: PreparedFlags::seal(vec![disabled_survey_flag.clone()]),
            filtered_out_flag_ids: HashSet::from([disabled_survey_flag.id])
        );

        // Should NOT record usage for filtered-out survey flags
        assert!(!contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_only_filtered_out_and_survey_flags() {
        let disabled_flag = mock!(FeatureFlag, id: 1, key: "disabled_flag".mock_into());
        let survey_flag =
            mock!(FeatureFlag, id: 2, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"));

        let flag_list = mock!(FeatureFlagList,
            flags: PreparedFlags::seal(vec![disabled_flag.clone(), survey_flag]),
            filtered_out_flag_ids: HashSet::from([disabled_flag.id])
        );

        // Should NOT record usage when only filtered-out and survey flags are present
        assert!(!contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_only_product_tour_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1")),
            mock!(FeatureFlag, id: 2, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour2")),
        ]
        .mock_into();

        // Should NOT record usage when only product tour flags are present
        assert!(!contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_product_tour_mixed_with_regular_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1")),
            mock!(FeatureFlag, id: 2, key: "regular_flag".mock_into()),
        ]
        .mock_into();

        // Should record usage when there's at least one regular flag, even with product tour flags
        assert!(contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_filtered_out_product_tour_flag() {
        let disabled_tour_flag =
            mock!(FeatureFlag, id: 1, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1"));

        let flag_list = mock!(FeatureFlagList,
            flags: PreparedFlags::seal(vec![disabled_tour_flag.clone()]),
            filtered_out_flag_ids: HashSet::from([disabled_tour_flag.id])
        );

        // Should NOT record usage for filtered-out product tour flags
        assert!(!contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_only_survey_and_product_tour_flags() {
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1")),
            mock!(FeatureFlag, id: 2, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour1")),
        ]
        .mock_into();

        // Should NOT record usage when only survey and product tour flags are present
        assert!(!contains_billable_flags(&flag_list));
    }

    #[test]
    fn test_contains_billable_flags_product_tour_flag_key_edge_cases() {
        // Test flag that contains the prefix but doesn't start with it
        // Test flag that starts with prefix but has extra content
        let flag_list: FeatureFlagList = vec![
            mock!(FeatureFlag, id: 1, key: format!("prefix-{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}middle")),
            mock!(FeatureFlag, id: 2, key: format!("{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}tour-with-suffix")),
        ]
        .mock_into();

        // Should record usage: first flag doesn't START with prefix, second does start with prefix
        assert!(contains_billable_flags(&flag_list));
    }

    /// Pin the predicate ordering for `record_usage`: any of `skip_writes`,
    /// `is_internal`, or "no billable flags" must skip the aggregator write.
    /// Integration tests cover `skip_writes` but not `is_internal` (no header
    /// path), so this unit test is the only guard for that branch.
    #[test]
    fn should_record_billable_request_obeys_each_guard() {
        let billable: FeatureFlagList =
            vec![mock!(FeatureFlag, id: 1, key: "billable-flag".mock_into())].mock_into();
        let non_billable: FeatureFlagList =
            vec![mock!(FeatureFlag, id: 1, key: format!("{SURVEY_TARGETING_FLAG_PREFIX}survey1"))]
                .mock_into();

        assert!(should_record_billable_request(false, false, &billable));
        assert!(!should_record_billable_request(true, false, &billable));
        assert!(!should_record_billable_request(false, true, &billable));
        assert!(!should_record_billable_request(false, false, &non_billable));
    }
}
