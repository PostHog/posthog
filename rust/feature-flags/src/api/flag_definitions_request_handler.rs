use crate::{
    api::{errors::FlagDefinitionsError, flag_definition_types::FlagDefinitionsResponse, request_handler::{FlagsQueryParams, RequestContext}},
};
use axum::http::HeaderMap;
use bytes::Bytes;

pub async fn process_flags_definitions_request(
    context: RequestContext,
) -> Result<FlagDefinitionsResponse, FlagDefinitionsError> {
    let personal_api_key =
        decode_personal_api_token(&context.headers, context.body, &context.meta)?;

    let response = FlagDefinitionsResponse {
        request_id: context.request_id,
        msg: format!(
            "Hello world! Your personal api key is: {}",
            personal_api_key
        ),
    };

    return Ok(response);
}

pub fn decode_personal_api_token(
    headers: &HeaderMap,
    body: Bytes,
    query: &FlagsQueryParams,
) -> Result<String, FlagDefinitionsError> {
    // Per the docs: https://posthog.com/docs/api
    // We try to read the personal API token from these three places in order.
    // We use the first one we find.
    // The bearer token: Authorization: "Bearer ${POSTHOG_PERSONAL_API_KEY}"
    // The request body: { "personal_api_key": "..."}
    // The query param: ?personal_api_key=...

    // We try to read the personal API token from the bearer token first.
    let bearer_token = headers
        .get("Authorization")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.split_whitespace().nth(1).unwrap_or("").to_string());

    if let Some(bearer_token) = bearer_token {
        return Ok(bearer_token);
    }

    // We try to read the personal API token from the request body.
    if !body.is_empty() {
        let request_body = String::from_utf8(body.to_vec())
            .map_err(|e| FlagDefinitionsError::RequestDecodingError(e.to_string()))?;

        let request_body_json: serde_json::Value = serde_json::from_str(&request_body)
            .map_err(|e| FlagDefinitionsError::RequestDecodingError(e.to_string()))?;

        let personal_api_token = request_body_json
            .get("personal_api_key")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        if let Some(personal_api_token) = personal_api_token {
            return Ok(personal_api_token);
        }
    }

    // Try to read it from the query string parameters.
    let personal_api_token = query.personal_api_key.clone();

    if let Some(personal_api_token) = personal_api_token {
        return Ok(personal_api_token);
    }

    return Err(FlagDefinitionsError::NoPersonalApiKeyError);
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderValue;

    #[test]
    fn test_decode_personal_api_token_from_bearer() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "Authorization",
            HeaderValue::from_static("Bearer test-token"),
        );
        let body = Bytes::new();
        let query = FlagsQueryParams {
            version: None,
            compression: None,
            lib_version: None,
            sent_at: None,
            personal_api_key: None,
        };

        let result = decode_personal_api_token(&headers, body, &query).unwrap();
        assert_eq!(result, "test-token");
    }

    #[test]
    fn test_decode_personal_api_token_from_body() {
        let headers = HeaderMap::new();
        let body = Bytes::from(r#"{"personal_api_key": "test-token"}"#);
        let query = FlagsQueryParams {
            version: None,
            compression: None,
            lib_version: None,
            sent_at: None,
            personal_api_key: None,
        };

        let result = decode_personal_api_token(&headers, body, &query).unwrap();
        assert_eq!(result, "test-token");
    }

    #[test]
    fn test_decode_personal_api_token_from_query() {
        let headers = HeaderMap::new();
        let body = Bytes::new();
        let query = FlagsQueryParams {
            version: None,
            compression: None,
            lib_version: None,
            sent_at: None,
            personal_api_key: Some("test-token".to_string()),
        };

        let result = decode_personal_api_token(&headers, body, &query).unwrap();
        assert_eq!(result, "test-token");
    }

    #[test]
    fn test_decode_personal_api_token_priority() {
        // Test that bearer token takes precedence over body and query
        let mut headers = HeaderMap::new();
        headers.insert(
            "Authorization",
            HeaderValue::from_static("Bearer bearer-token"),
        );
        let body = Bytes::from(r#"{"personal_api_key": "body-token"}"#);
        let query = FlagsQueryParams {
            version: None,
            compression: None,
            lib_version: None,
            sent_at: None,
            personal_api_key: Some("query-token".to_string()),
        };

        let result = decode_personal_api_token(&headers, body, &query).unwrap();
        assert_eq!(result, "bearer-token");
    }

    #[test]
    fn test_decode_personal_api_token_missing() {
        let headers = HeaderMap::new();
        let body = Bytes::new();
        let query = FlagsQueryParams {
            version: None,
            compression: None,
            lib_version: None,
            sent_at: None,
            personal_api_key: None,
        };

        let result = decode_personal_api_token(&headers, body, &query);
        assert!(matches!(
            result,
            Err(FlagDefinitionsError::NoPersonalApiKeyError)
        ));
    }

    #[test]
    fn test_decode_personal_api_token_invalid_body() {
        let headers = HeaderMap::new();
        let body = Bytes::from("invalid json");
        let query = FlagsQueryParams {
            version: None,
            compression: None,
            lib_version: None,
            sent_at: None,
            personal_api_key: None,
        };

        let result = decode_personal_api_token(&headers, body, &query);
        assert!(matches!(
            result,
            Err(FlagDefinitionsError::RequestDecodingError(_))
        ));
    }
}
