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
    api::{errors::FlagError, types::FlagsResponse},
    flags::flag_service::FlagService,
    metrics::consts::{FLAG_REQUESTS_COUNTER, FLAG_REQUESTS_LATENCY, FLAG_REQUEST_FAULTS_COUNTER},
};
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

async fn process_request_inner(
    context: RequestContext,
) -> (Result<FlagsResponse, FlagError>, MetricsData) {
    let mut metrics_data = MetricsData {
        team_id: None,
        flags_disabled: None,
    };

    let result = async {
        let flag_service = FlagService::new(
            context.state.redis_reader.clone(),
            context.state.redis_writer.clone(),
            context.state.database_pools.non_persons_reader.clone(),
        );

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

        metrics_data.team_id = Some(team.id);
        metrics_data.flags_disabled = Some(request.is_flags_disabled());

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

        Ok(response)
    }
    .await;

    (result, metrics_data)
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
