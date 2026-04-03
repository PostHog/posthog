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
