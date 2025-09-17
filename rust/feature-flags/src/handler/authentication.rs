use crate::{
    api::errors::FlagError,
    flags::{flag_request::FlagRequest, flag_service::FlagService},
};

use super::{decoding, types::RequestContext};

pub async fn parse_and_authenticate(
    context: &RequestContext,
    flag_service: &FlagService,
) -> Result<(Option<String>, String, FlagRequest), FlagError> {
    let request = decoding::decode_request(&context.headers, context.body.clone(), &context.meta)?;
    let token = request.extract_token()?;
    let verified_token = flag_service.verify_token(&token).await?;

    // Only validate distinct_id if flags are NOT disabled
    let distinct_id = if request.is_flags_disabled() {
        None
    } else {
        Some(request.extract_distinct_id()?)
    };

    Ok((distinct_id, verified_token, request))
}
