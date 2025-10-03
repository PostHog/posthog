pub mod authentication;
pub mod billing;
pub mod config_response_builder;
pub mod cookieless;
pub mod decoding;
pub mod error_tracking;
pub mod evaluation;
pub mod flags;
pub mod properties;
pub mod session_recording;
pub mod types;

pub use types::*;

use crate::{
    api::{
        errors::FlagError,
        types::{
            EvaluationReasonResponse, EvaluationReasonsResponse, FlagEvaluationWithReason,
            FlagsResponse,
        },
    },
    flags::flag_service::FlagService,
    metrics::consts::{FLAG_REQUESTS_COUNTER, FLAG_REQUESTS_LATENCY, FLAG_REQUEST_FAULTS_COUNTER},
};
use common_database::PostgresReader;
use std::collections::HashMap;
use tracing::{info, instrument, warn};

#[cfg(test)]
use crate::handler::test_metrics::{histogram, inc};

// In production, use the real metrics functions
#[cfg(not(test))]
use common_metrics::{histogram, inc};

/// Primary entry point for feature flag requests.
/// 1) Parses and authenticates the request,
/// 2) Fetches the team and feature flags,
/// 3) Prepares property overrides,
/// 4) Evaluates the requested flags,
/// 5) Returns a [`FlagsResponse`] or an error.
#[instrument(skip_all, fields(request_id = %context.request_id))]
pub async fn process_request(context: RequestContext) -> Result<FlagsResponse, FlagError> {
    let start_time = std::time::Instant::now();
    let (result, metrics_data) = process_request_inner(context).await;
    let total_duration = start_time.elapsed();

    record_metrics(&result, metrics_data, total_duration);

    result
}

struct MetricsData {
    team_id: Option<i32>,
    flags_disabled: Option<bool>,
}

fn record_metrics(
    result: &Result<FlagsResponse, FlagError>,
    data: MetricsData,
    duration: std::time::Duration,
) {
    let team_id = data
        .team_id
        .map(|id| id.to_string())
        .unwrap_or_else(|| "not_available".to_string());

    let flags_disabled = data
        .flags_disabled
        .map(|disabled| disabled.to_string())
        .unwrap_or_else(|| "not_available".to_string());

    let labels = [
        ("flags_disabled".to_string(), flags_disabled),
        ("team_id".to_string(), team_id.clone()),
    ];

    inc(FLAG_REQUESTS_COUNTER, &labels, 1);
    histogram(FLAG_REQUESTS_LATENCY, &labels, duration.as_millis() as f64);

    if let Err(ref e) = result {
        if e.is_5xx() {
            inc(
                FLAG_REQUEST_FAULTS_COUNTER,
                &[("team_id".to_string(), team_id)],
                1,
            );
        }
    }
}

/// Handler for evaluation_reasons endpoint - processes request and returns flag values with evaluation reasons
#[instrument(skip_all, fields(request_id = %context.request_id))]
pub async fn process_evaluation_reasons_request(
    context: RequestContext,
) -> Result<EvaluationReasonsResponse, FlagError> {
    // Extract the database client before moving context
    let pg_client = context.state.database_pools.non_persons_reader.clone();

    // Process the request and get both the response and team info
    let (flags_response, team_info) = process_request_with_team(context).await?;

    // Convert active flags to evaluation reasons format
    let active_evaluation_reasons: HashMap<String, FlagEvaluationWithReason> = flags_response
        .flags
        .into_iter()
        .map(|(key, flag_details)| {
            let evaluation_with_reason = FlagEvaluationWithReason {
                value: flag_details.to_value(),
                evaluation: EvaluationReasonResponse {
                    reason: flag_details.reason.code, // The internal field is "code", but we serialize it as "reason" for Python compatibility
                    condition_index: flag_details.reason.condition_index,
                    description: flag_details.reason.description,
                },
            };
            (key, evaluation_with_reason)
        })
        .collect();

    // Fetch disabled flags and merge with active flags
    // This matches the Python behavior in posthog/api/feature_flag.py lines 1518-1529
    let evaluation_reasons = match team_info.project_id {
        Some(project_id) => {
            merge_with_disabled_flags(pg_client, project_id, active_evaluation_reasons).await
        }
        None => active_evaluation_reasons,
    };

    Ok(EvaluationReasonsResponse(evaluation_reasons))
}

/// Fetches disabled flags and merges them with active flags
/// This is a best-effort operation - if it fails, we log the error and return only active flags
async fn merge_with_disabled_flags(
    pg_client: PostgresReader,
    project_id: i64,
    active_evaluation_reasons: HashMap<String, FlagEvaluationWithReason>,
) -> HashMap<String, FlagEvaluationWithReason> {
    match crate::flags::flag_models::FeatureFlagList::fetch_disabled_flags_from_pg(
        pg_client, project_id,
    )
    .await
    {
        Ok(disabled_flag_keys) => {
            // Create disabled flag entries for keys not in active flags
            let disabled_flags: HashMap<String, FlagEvaluationWithReason> = disabled_flag_keys
                .into_iter()
                .filter(|key| !active_evaluation_reasons.contains_key(key)) // Active flags take precedence
                .map(|key| {
                    let evaluation = FlagEvaluationWithReason {
                        value: crate::api::types::FlagValue::Boolean(false),
                        evaluation: EvaluationReasonResponse {
                            reason: "disabled".to_string(),
                            condition_index: None,
                            description: None,
                        },
                    };
                    (key, evaluation)
                })
                .collect();

            // Merge active and disabled flags
            // Active flags go first to ensure they take precedence if any key somehow appears in both
            active_evaluation_reasons
                .into_iter()
                .chain(disabled_flags)
                .collect()
        }
        Err(e) => {
            // Log the error but don't fail the entire request
            tracing::warn!(
                "Failed to fetch disabled flags for project {}: {}",
                project_id,
                e
            );
            active_evaluation_reasons
        }
    }
}

/// Team information returned from process_request_with_team
#[derive(Debug, Clone)]
pub struct TeamInfo {
    pub team_id: i32,
    pub project_id: Option<i64>,
}

/// Process request and return both the response and team information
/// This avoids duplicate authentication/team fetching when the evaluation_reasons endpoint needs team data
pub async fn process_request_with_team(
    context: RequestContext,
) -> Result<(FlagsResponse, TeamInfo), FlagError> {
    let start_time = std::time::Instant::now();
    let (result, metrics_data, team_info) = process_request_inner_with_team(context).await;
    let total_duration = start_time.elapsed();

    record_metrics(&result, metrics_data, total_duration);

    result.map(|response| (response, team_info))
}

async fn process_request_inner(
    context: RequestContext,
) -> (Result<FlagsResponse, FlagError>, MetricsData) {
    let (result, metrics_data, _) = process_request_inner_with_team(context).await;
    (result, metrics_data)
}

async fn process_request_inner_with_team(
    context: RequestContext,
) -> (Result<FlagsResponse, FlagError>, MetricsData, TeamInfo) {
    let flag_service = FlagService::new(
        context.state.redis_reader.clone(),
        context.state.redis_writer.clone(),
        context.state.database_pools.non_persons_reader.clone(),
    );

    // Process the request and capture team info
    let result = async {
        let (original_distinct_id, verified_token, request) =
            authentication::parse_and_authenticate(&context, &flag_service).await?;

        let distinct_id_for_logging = original_distinct_id
            .clone()
            .unwrap_or_else(|| "disabled".to_string());

        tracing::debug!(
            "Authentication completed for distinct_id: {}",
            distinct_id_for_logging
        );

        let team = flag_service
            .get_team_from_cache_or_pg(&verified_token)
            .await?;

        let team_info = TeamInfo {
            team_id: team.id,
            project_id: Some(team.project_id),
        };

        tracing::debug!(
            "Team fetched: team_id={}, project_id={}",
            team.id,
            team.project_id
        );

        // Early exit if flags are disabled
        let flags_response = if request.is_flags_disabled() {
            FlagsResponse::new(false, HashMap::new(), None, context.request_id)
        } else if let Some(quota_limited_response) =
            billing::check_limits(&context, &verified_token).await?
        {
            warn!("Request quota limited");
            quota_limited_response
        } else {
            let distinct_id = cookieless::handle_distinct_id(
                &context,
                &request,
                &team,
                original_distinct_id
                    .expect("distinct_id should be present when flags are not disabled"),
            )
            .await?;

            tracing::debug!("Distinct ID resolved: {}", distinct_id);

            let (filtered_flags, had_flag_errors) = flags::fetch_and_filter(
                &flag_service,
                team.project_id,
                &context.meta,
                &context.headers,
                None,
                request.evaluation_environments.as_ref(),
            )
            .await?;

            tracing::debug!("Flags filtered: {} flags found", filtered_flags.flags.len());

            let property_overrides = properties::prepare_overrides(&context, &request)?;

            // Evaluate flags (this will return empty if is_flags_disabled is true)
            let mut response = flags::evaluate_for_request(
                &context.state,
                team.id,
                team.project_id,
                distinct_id.clone(),
                filtered_flags.clone(),
                property_overrides.person_properties,
                property_overrides.group_properties,
                property_overrides.groups,
                property_overrides.hash_key,
                context.request_id,
                request.is_flags_disabled(),
                request.flag_keys.clone(),
            )
            .await;

            // Set error flag if there were deserialization errors
            if had_flag_errors {
                response.errors_while_computing_flags = true;
            }

            // Only record billing if flags are not disabled
            if !request.is_flags_disabled() {
                billing::record_usage(&context, &filtered_flags, team.id).await;
            }

            response
        };

        // build the rest of the FlagsResponse, since the caller may have passed in `&config=true` and may need additional fields
        // beyond just feature flags
        let response =
            config_response_builder::build_response(flags_response, &context, &team).await?;

        // Comprehensive request summary
        info!(
            request_id = %context.request_id,
            distinct_id = %distinct_id_for_logging,
            team_id = team.id,
            project_id = team.project_id,
            flags_count = response.flags.len(),
            flags_disabled = request.is_flags_disabled(),
            quota_limited = response.quota_limited.is_some(),
            "Request completed"
        );

        Ok((response, team_info, request.is_flags_disabled()))
    }
    .await;

    // Extract metrics data and transform result
    match result {
        Ok((response, team_info, flags_disabled)) => {
            let metrics_data = MetricsData {
                team_id: Some(team_info.team_id),
                flags_disabled: Some(flags_disabled),
            };
            (Ok(response), metrics_data, team_info)
        }
        Err(e) => {
            // Default team info for error case
            let team_info = TeamInfo {
                team_id: 0,
                project_id: None,
            };
            let metrics_data = MetricsData {
                team_id: None,
                flags_disabled: None,
            };
            (Err(e), metrics_data, team_info)
        }
    }
}

#[cfg(test)]
mod tests;

#[cfg(test)]
mod test_metrics {

    #[derive(Debug, Clone, PartialEq)]
    pub struct RecordedMetric {
        pub name: String,
        pub labels: Vec<(String, String)>,
        pub value: f64,
        pub metric_type: MetricType,
    }

    #[derive(Debug, Clone, PartialEq)]
    pub enum MetricType {
        Counter,
        Histogram,
    }

    // Thread-safe storage for captured metrics during tests
    // Using thread_local with RefCell for test isolation
    thread_local! {
        static RECORDED_METRICS: std::cell::RefCell<Vec<RecordedMetric>> = const { std::cell::RefCell::new(Vec::new()) };
    }

    pub fn inc(name: &str, labels: &[(String, String)], value: u64) {
        let metric = RecordedMetric {
            name: name.to_string(),
            labels: labels.to_vec(),
            value: value as f64,
            metric_type: MetricType::Counter,
        };
        RECORDED_METRICS.with(|metrics| {
            metrics.borrow_mut().push(metric);
        });
    }

    pub fn histogram(name: &str, labels: &[(String, String)], value: f64) {
        let metric = RecordedMetric {
            name: name.to_string(),
            labels: labels.to_vec(),
            value,
            metric_type: MetricType::Histogram,
        };
        RECORDED_METRICS.with(|metrics| {
            metrics.borrow_mut().push(metric);
        });
    }

    // Test helper functions
    pub fn clear_recorded_metrics() {
        RECORDED_METRICS.with(|metrics| {
            metrics.borrow_mut().clear();
        });
    }

    pub fn get_recorded_metrics() -> Vec<RecordedMetric> {
        RECORDED_METRICS.with(|metrics| metrics.borrow().clone())
    }
}

#[cfg(test)]
mod metrics_tests {
    use super::*;
    use crate::api::errors::ClientFacingError;
    use crate::handler::test_metrics::{clear_recorded_metrics, get_recorded_metrics, MetricType};
    use std::collections::HashMap;
    use uuid::Uuid;

    #[test]
    fn test_record_metrics_with_complete_data() {
        clear_recorded_metrics();

        let result = Ok(FlagsResponse::new(
            false,
            HashMap::new(),
            None,
            Uuid::new_v4(),
        ));
        let data = MetricsData {
            team_id: Some(123),
            flags_disabled: Some(false),
        };

        // Call the real record_metrics function - it will use our test metrics functions
        record_metrics(&result, data, std::time::Duration::from_millis(100));

        // Verify the metrics were recorded correctly
        let metrics = get_recorded_metrics();
        assert_eq!(
            metrics.len(),
            2,
            "Should record 2 metrics (counter and histogram)"
        );

        // Check the counter metric
        let counter = &metrics[0];
        assert_eq!(counter.name, FLAG_REQUESTS_COUNTER);
        assert_eq!(counter.metric_type, MetricType::Counter);
        assert_eq!(counter.value, 1.0);
        assert!(counter
            .labels
            .contains(&("team_id".to_string(), "123".to_string())));
        assert!(counter
            .labels
            .contains(&("flags_disabled".to_string(), "false".to_string())));

        // Check the histogram metric
        let histogram = &metrics[1];
        assert_eq!(histogram.name, FLAG_REQUESTS_LATENCY);
        assert_eq!(histogram.metric_type, MetricType::Histogram);
        assert_eq!(histogram.value, 100.0);
    }

    #[test]
    fn test_record_metrics_with_missing_data() {
        clear_recorded_metrics();

        let result = Ok(FlagsResponse::new(
            false,
            HashMap::new(),
            None,
            Uuid::new_v4(),
        ));
        let data = MetricsData {
            team_id: None,
            flags_disabled: None,
        };

        record_metrics(&result, data, std::time::Duration::from_millis(50));

        let metrics = get_recorded_metrics();
        assert_eq!(metrics.len(), 2);

        // Both metrics should use "not_available" for missing values
        for metric in &metrics {
            assert!(metric
                .labels
                .contains(&("team_id".to_string(), "not_available".to_string())));
            assert!(metric
                .labels
                .contains(&("flags_disabled".to_string(), "not_available".to_string())));
        }
    }

    #[test]
    fn test_record_metrics_with_5xx_error() {
        clear_recorded_metrics();

        let result = Err(FlagError::Internal("test error".to_string()));
        let data = MetricsData {
            team_id: Some(456),
            flags_disabled: Some(true),
        };

        record_metrics(&result, data, std::time::Duration::from_millis(200));

        let metrics = get_recorded_metrics();
        assert_eq!(
            metrics.len(),
            3,
            "Should record 3 metrics (counter, histogram, and fault counter)"
        );

        // Check the fault counter is recorded
        let fault_counter = metrics
            .iter()
            .find(|m| m.name == FLAG_REQUEST_FAULTS_COUNTER)
            .expect("Should have fault counter");

        assert_eq!(fault_counter.metric_type, MetricType::Counter);
        assert_eq!(fault_counter.value, 1.0);
        assert!(fault_counter
            .labels
            .contains(&("team_id".to_string(), "456".to_string())));
    }

    #[test]
    fn test_record_metrics_with_5xx_error_no_team_id() {
        clear_recorded_metrics();

        let result = Err(FlagError::DatabaseUnavailable);
        let data = MetricsData {
            team_id: None,
            flags_disabled: Some(false),
        };

        record_metrics(&result, data, std::time::Duration::from_millis(150));

        let metrics = get_recorded_metrics();
        assert_eq!(metrics.len(), 3); // counter, histogram, and fault counter

        // Should record fault counter with "not_available"
        let fault_counter = metrics
            .iter()
            .find(|m| m.name == FLAG_REQUEST_FAULTS_COUNTER)
            .expect("Should have fault counter");

        assert!(fault_counter
            .labels
            .contains(&("team_id".to_string(), "not_available".to_string())));
    }

    #[test]
    fn test_record_metrics_with_4xx_error() {
        clear_recorded_metrics();

        let result = Err(FlagError::ClientFacing(ClientFacingError::BadRequest(
            "bad".to_string(),
        )));
        let data = MetricsData {
            team_id: Some(789),
            flags_disabled: Some(false),
        };

        record_metrics(&result, data, std::time::Duration::from_millis(75));

        let metrics = get_recorded_metrics();
        assert_eq!(metrics.len(), 2); // Only counter and histogram, NO fault counter

        // Verify no fault counter was recorded
        let fault_counter = metrics
            .iter()
            .find(|m| m.name == FLAG_REQUEST_FAULTS_COUNTER);
        assert!(
            fault_counter.is_none(),
            "Should NOT record fault counter for 4XX errors"
        );
    }
}
