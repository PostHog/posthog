use crate::api::{
    auth::{authenticate_personal_api_key, AuthError},
    flag_definition_types::FlagDefinitionsResponse,
    permissions::has_permission,
    request_handler::RequestContext,
};

pub async fn process_flags_definitions_request(
    context: &RequestContext,
) -> Result<FlagDefinitionsResponse, AuthError> {
    let api_key =
        authenticate_personal_api_key(context.state.reader.as_ref(), &context.request).await?;

    if let Err(e) = has_permission(&api_key, "feature_flag", &["feature_flag:read"]) {
        return Err(AuthError::InvalidScopes(e.to_string()));
    }

    // TODO: Query the flag definitions from the cache/database

    let response = FlagDefinitionsResponse {
        request_id: context.request.id,
        msg: format!(
            "Hello world! Your personal api key is authenticated and valid for team: {:?}",
            api_key.team_id
        ),
    };

    return Ok(response);
}
