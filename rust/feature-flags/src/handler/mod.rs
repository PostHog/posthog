pub mod authentication;
pub mod billing;
pub mod cookieless;
pub mod decoding;
pub mod evaluation;
pub mod flags;
pub mod properties;
pub mod response_builder;
pub mod session_recording;
pub mod types;

pub use types::*;

use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    flags::flag_service::FlagService,
};

/// Primary entry point for feature flag requests.
/// 1) Parses and authenticates the request,
/// 2) Fetches the team and feature flags,
/// 3) Prepares property overrides,
/// 4) Evaluates the requested flags,
/// 5) Returns a [`FlagsPlusConfigResponse`] or an error.
pub async fn process_request(context: RequestContext) -> Result<FlagsResponse, FlagError> {
    let flag_service = FlagService::new(context.state.redis.clone(), context.state.reader.clone());

    let (original_distinct_id, verified_token, request) =
        authentication::parse_and_authenticate(&context, &flag_service).await?;

    // Check billing limits early
    if let Some(quota_response) = billing::check_limits(&context, &verified_token).await? {
        return Ok(quota_response);
    }

    let team = flag_service
        .get_team_from_cache_or_pg(&verified_token)
        .await?;
    let distinct_id =
        cookieless::handle_distinct_id(&context, &request, &team, original_distinct_id).await?;

    let filtered_flags = flags::fetch_and_filter(&flag_service, team.project_id, &request).await?;
    let property_overrides = properties::prepare_overrides(&context, &request)?;

    let flags_response = flags::evaluate_for_request(
        &context.state,
        team.id,
        team.project_id,
        distinct_id,
        filtered_flags.clone(),
        property_overrides.person_properties,
        property_overrides.group_properties,
        property_overrides.groups,
        property_overrides.hash_key,
        context.request_id,
    )
    .await;

    let response = response_builder::build_response(flags_response, &context, &team).await?;

    billing::record_usage(&context, &filtered_flags, team.id).await;

    Ok(response)
}

#[cfg(test)]
mod tests;
