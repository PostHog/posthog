use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    billing::{aggregator::classify_redis_error, AggregatorMode, BillingAggregator},
    flags::{
        flag_analytics::{increment_request_count, is_billable_flag_key},
        flag_models::FeatureFlagList,
        flag_request::FlagRequestType,
    },
    metrics::consts::{FLAG_BILLING_INCREMENT_TIME, FLAG_REQUEST_REDIS_ERROR},
};
use common_metrics::{histogram, inc};
use common_redis::{Client as RedisClient, CustomRedisError};
use limiters::redis::ServiceName;
use std::collections::HashMap;
use std::sync::Arc;
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

/// Records a billable request against the production billing keyspace.
///
/// Caller is responsible for the predicate (skip_writes, billable flags,
/// internal requests, etc.) — by the time this is called the request is
/// known to be billable.
///
/// Behavior depends on the aggregator's mode:
///
/// - **No aggregator, or `AggregatorMode::Shadow`**: the authoritative write
///   is the synchronous per-request `increment_request_count`. The shadow
///   tee fires only when the synchronous write succeeds — recording a
///   request the production keyspace did not capture would surface as a
///   false "aggregator over-counted" signal during reconciliation, masking
///   any real over-count bug in the aggregator. Tying the two writes
///   together keeps the reconciliation invariant a strict equality: if
///   shadow > prod and `flag_request_redis_error` is flat, the aggregator
///   is the cause.
/// - **`AggregatorMode::Authoritative`**: the aggregator *is* the
///   authoritative writer. We skip `increment_request_count` (no
///   per-request Redis I/O on this path) and `aggregator.record()` is the
///   only billing write. The reconciliation invariant from shadow mode no
///   longer applies — pending records live in process memory until the
///   next flush, so `flags_billing_pending_records` and
///   `flags_billing_seconds_since_successful_flush` become
///   billing-critical signals.
pub async fn record_billing_increment(
    redis: Arc<dyn RedisClient + Send + Sync>,
    aggregator: Option<&Arc<BillingAggregator>>,
    team_id: i32,
    request_type: FlagRequestType,
    library: Library,
) {
    if let Some(aggregator) = aggregator {
        if aggregator.mode() == AggregatorMode::Authoritative {
            // billing_duration_ms measures in-process record latency (not Redis
            // RTT) for dashboard continuity across cutover.
            let start = Instant::now();
            aggregator.record(team_id, request_type, Some(library));
            let elapsed_ms = start.elapsed().as_millis() as u64;
            with_canonical_log(|log| log.billing_duration_ms = Some(elapsed_ms));
            return;
        }
    }

    let start = Instant::now();
    let result = increment_request_count(redis, team_id, 1, request_type, Some(library)).await;
    let elapsed_ms = start.elapsed().as_millis() as u64;

    record_billing_increment_timing(&result, elapsed_ms);
    // No-op outside a canonical-log scope (e.g. /flags/definitions), so safe
    // to call from every site.
    with_canonical_log(|log| log.billing_duration_ms = Some(elapsed_ms));

    match result {
        Ok(()) => {
            if let Some(aggregator) = aggregator {
                aggregator.record(team_id, request_type, Some(library));
            }
        }
        Err(e) => {
            // Bounded `error_type` label (e.g. "timeout"/"transport") —
            // never the raw error message. The full `CustomRedisError::Display`
            // can include unbounded transport details that would explode
            // metric cardinality if used as a Prometheus label.
            inc(
                FLAG_REQUEST_REDIS_ERROR,
                &[(
                    "error_type".to_string(),
                    classify_redis_error(&e).to_string(),
                )],
                1,
            );
        }
    }
}

/// Records usage metrics for feature flag requests. Survey and product tour
/// targeting flags are not billable. The `library` parameter is detected
/// once at the start of request processing and reused.
pub async fn record_usage(
    context: &RequestContext,
    filtered_flags: &FeatureFlagList,
    team_id: i32,
    library: Library,
    is_internal: bool,
) {
    if *context.state.config.skip_writes {
        return;
    }
    // Skip billing for internal requests.
    if is_internal {
        return;
    }
    if !contains_billable_flags(filtered_flags) {
        return;
    }

    record_billing_increment(
        context.state.redis_client.clone(),
        context.state.billing_aggregator.as_ref(),
        team_id,
        FlagRequestType::Decide,
        library,
    )
    .await;
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
    use crate::billing::BillingAggregatorConfig;
    use crate::flags::feature_flag_list::PreparedFlags;
    use crate::flags::flag_analytics::{
        PRODUCT_TOUR_TARGETING_FLAG_PREFIX, SURVEY_TARGETING_FLAG_PREFIX,
    };
    use crate::flags::flag_models::FeatureFlag;
    use crate::mock;
    use crate::utils::mock::MockInto;
    use common_redis::MockRedisClient;
    use rstest::rstest;

    use std::collections::HashSet;

    /// Pins the cutover branch in `record_billing_increment`: in `Authoritative`
    /// mode the per-request HINCRBY is skipped (aggregator is the only writer);
    /// in `Shadow` mode the per-request HINCRBY runs and the aggregator tees the
    /// record on success.
    #[rstest]
    #[case::authoritative(AggregatorMode::Authoritative, false)]
    #[case::shadow(AggregatorMode::Shadow, true)]
    #[tokio::test]
    async fn record_billing_increment_routes_by_mode(
        #[case] mode: AggregatorMode,
        #[case] expect_per_request_redis_call: bool,
    ) {
        let per_request_redis = Arc::new(MockRedisClient::new());
        let aggregator_redis = Arc::new(MockRedisClient::new());
        let aggregator = BillingAggregator::for_tests_with_mode(
            aggregator_redis,
            BillingAggregatorConfig::default(),
            mode,
        );

        record_billing_increment(
            per_request_redis.clone(),
            Some(&aggregator),
            42,
            FlagRequestType::Decide,
            Library::PosthogJs,
        )
        .await;

        assert_eq!(
            !per_request_redis.get_calls().is_empty(),
            expect_per_request_redis_call,
            "per-request Redis call expectation mismatch for mode {mode:?}"
        );
        assert_eq!(
            aggregator.pending_total(),
            1,
            "aggregator must hold the recorded count regardless of mode"
        );
    }

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
}
