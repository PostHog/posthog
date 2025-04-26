use crate::api::{
    auth::find_personal_api_key_with_source, errors::FlagDefinitionsError,
    flag_definition_types::FlagDefinitionsResponse, request_handler::RequestContext,
};

pub async fn process_flags_definitions_request(
    context: RequestContext,
) -> Result<FlagDefinitionsResponse, FlagDefinitionsError> {
    let (personal_api_key, _) = find_personal_api_key_with_source(&context.request)?;

    let response = FlagDefinitionsResponse {
        request_id: context.request.id,
        msg: format!(
            "Hello world! Your personal api key is: {}",
            personal_api_key
        ),
    };

    return Ok(response);
}
