use crate::{
    api::errors::FlagError,
    flags::{flag_request::FlagRequest, flag_service::FlagService},
    team::team_models::Team,
};
use tracing::debug;

use super::{decoding, types::RequestContext};

pub async fn parse_and_authenticate(
    context: &RequestContext,
    flag_service: &FlagService,
) -> Result<(Option<String>, Team, FlagRequest), FlagError> {
    let request = decoding::decode_request(&context.headers, context.body.clone(), &context.meta)?;
    let token = request.extract_token()?;

    // Fetch the team (with caching) and validate the token exists
    let team = flag_service
        .get_team_from_cache_or_pg(&token)
        .await
        .map_err(|e| match e {
            FlagError::RowNotFound => {
                debug!(token = %token, "Token not found in database during authentication");
                FlagError::TokenValidationError
            }
            other => other,
        })?;

    // Only validate distinct_id if flags are NOT disabled
    let distinct_id = if request.is_flags_disabled() {
        None
    } else {
        Some(request.extract_distinct_id()?)
    };

    Ok((distinct_id, team, request))
}
