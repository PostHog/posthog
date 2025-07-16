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

use common_metrics::inc;
pub use types::*;

use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    flags::flag_service::FlagService,
    metrics::consts::FLAG_REQUESTS_COUNTER,
};
use tracing::{info, warn};

/// Primary entry point for feature flag requests.
/// 1) Parses and authenticates the request,
/// 2) Fetches the team and feature flags,
/// 3) Prepares property overrides,
/// 4) Evaluates the requested flags,
/// 5) Returns a [`FlagsResponse`] or an error.
pub async fn process_request(context: RequestContext) -> Result<FlagsResponse, FlagError> {
    async move {
        let start_time = std::time::Instant::now();

        let flag_service = FlagService::new(
            context.state.redis_reader.clone(),
            context.state.redis_writer.clone(),
            context.state.reader.clone(),
        );

        let (original_distinct_id, verified_token, request) =
            authentication::parse_and_authenticate(&context, &flag_service).await?;

        let distinct_id_for_logging = original_distinct_id.clone();

        tracing::debug!(
            "Authentication completed for distinct_id: {}",
            original_distinct_id
        );

        let team = flag_service
            .get_team_from_cache_or_pg(&verified_token)
            .await?;

        tracing::debug!(
            "Team fetched: team_id={}, project_id={}",
            team.id,
            team.project_id
        );

        // Check quota limits - don't return early, just use quota limited response if needed
        let flags_response = if let Some(quota_limited_response) =
            billing::check_limits(&context, &verified_token).await?
        {
            warn!("Request quota limited");
            quota_limited_response
        } else {
            let distinct_id =
                cookieless::handle_distinct_id(&context, &request, &team, original_distinct_id)
                    .await?;

            tracing::debug!("Distinct ID resolved: {}", distinct_id);

            let filtered_flags =
                flags::fetch_and_filter(&flag_service, team.project_id, &context.meta).await?;

            tracing::debug!("Flags filtered: {} flags found", filtered_flags.flags.len());

            let property_overrides = properties::prepare_overrides(&context, &request)?;

            // Evaluate flags (this will return empty if is_flags_disabled is true)
            let response = flags::evaluate_for_request(
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

            // Only record billing if flags are not disabled
            if !request.is_flags_disabled() {
                billing::record_usage(&context, &filtered_flags, team.id).await;
            }
            inc(
                FLAG_REQUESTS_COUNTER,
                &[
                    (
                        "flags_disabled".to_string(),
                        request.is_flags_disabled().to_string(),
                    ),
                    ("team_id".to_string(), team.id.to_string()),
                ],
                1,
            );

            response
        };

        // build the rest of the FlagsResponse, since the caller may have passed in `&config=true` and may need additional fields
        // beyond just feature flags
        let response =
            config_response_builder::build_response(flags_response, &context, &team).await?;

        let total_duration = start_time.elapsed();

        // Comprehensive request summary
        info!(
            request_id = %context.request_id,
            distinct_id = %distinct_id_for_logging,
            team_id = team.id,
            project_id = team.project_id,
            flags_count = response.flags.len(),
            flags_disabled = request.is_flags_disabled(),
            quota_limited = response.quota_limited.is_some(),
            duration_ms = total_duration.as_millis(),
            slow_request = total_duration.as_millis() > 1000,
            "Request completed"
        );

        Ok(response)
    }
    .await
}

#[cfg(test)]
mod tests;
