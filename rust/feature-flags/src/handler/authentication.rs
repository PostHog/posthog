use crate::{
    api::errors::FlagError,
    flags::{flag_request::FlagRequest, flag_service::FlagService},
    team::team_models::Team,
};

use super::{decoding, types::RequestContext};

pub async fn parse_and_authenticate(
    context: &RequestContext,
    flag_service: &FlagService,
) -> Result<(Option<String>, Team, FlagRequest), FlagError> {
    let request = decoding::decode_request(&context.headers, context.body.clone(), &context.meta)?;
    let token = request.extract_token()?;
    let team = flag_service.verify_token_and_get_team(&token).await?;

    // Only validate distinct_id if flags are NOT disabled
    let distinct_id = if request.is_flags_disabled() {
        None
    } else {
        Some(request.extract_distinct_id()?)
    };

    Ok((distinct_id, team, request))
}

/// Checks if the request is an internal request.
/// Returns true if the Authorization header contains a Bearer token that matches
/// the configured internal_request_token.
pub fn is_internal_request(context: &RequestContext) -> bool {
    // Check if DEBUG is enabled first (for local development)
    let debug_value = std::env::var("DEBUG").unwrap_or_default().to_lowercase();
    if debug_value == "true" || debug_value == "1" {
        return true;
    }

    let Some(internal_token) = &context.state.config.internal_request_token else {
        // No internal token configured, so no requests are internal
        return false;
    };

    // Empty token should never be considered valid
    if internal_token.trim().is_empty() {
        return false;
    }

    use crate::api::auth::extract_bearer_token;

    if let Some(auth_token) = extract_bearer_token(&context.headers) {
        // Ensure auth token is not empty either
        !auth_token.trim().is_empty() && auth_token == *internal_token
    } else {
        false
    }
}
