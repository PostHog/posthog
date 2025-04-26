use crate::api::{errors::FlagDefinitionsError, request_handler::RequestInfo};

#[derive(Debug, PartialEq, Eq)]
pub enum ApiKeySource {
    AuthorizationHeader,
    Body,
    Query,
}

pub fn find_personal_api_key_with_source(
    request: &RequestInfo,
) -> Result<(String, ApiKeySource), FlagDefinitionsError> {
    // Per the docs: https://posthog.com/docs/api
    // We try to read the personal API token from these three places in order.
    // We use the first one we find.
    // The bearer token: Authorization: "Bearer ${POSTHOG_PERSONAL_API_KEY}"
    // The request body: { "personal_api_key": "..."}
    // The query param: ?personal_api_key=...
    // Then we return the key along with where we found it.

    let body = &request.body;
    let headers = &request.headers;
    let query = &request.meta;

    // We try to read the personal API token from the bearer token first.
    let bearer_token = headers
        .get("Authorization")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.split_whitespace().nth(1).unwrap_or("").to_string());

    if let Some(bearer_token) = bearer_token {
        return Ok((bearer_token, ApiKeySource::AuthorizationHeader));
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
            return Ok((personal_api_token, ApiKeySource::Body));
        }
    }

    // Try to read it from the query string parameters.
    let personal_api_token = query.personal_api_key.clone();

    if let Some(personal_api_token) = personal_api_token {
        return Ok((personal_api_token, ApiKeySource::Query));
    }

    return Err(FlagDefinitionsError::NoPersonalApiKeyError);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::request_handler::{FlagsQueryParams, RequestInfo};
    use axum::http::{HeaderMap, HeaderValue, Method};
    use bytes::Bytes;
    use uuid::Uuid;

    #[test]
    fn test_find_personal_api_key_with_source_from_bearer() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "Authorization",
            HeaderValue::from_static("Bearer test-token"),
        );

        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers,
            body: Bytes::new(),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: None,
            },
        };

        let (key, source) = find_personal_api_key_with_source(&request).unwrap();
        assert_eq!(key, "test-token");
        assert_eq!(source, ApiKeySource::AuthorizationHeader);
    }

    #[test]
    fn test_decode_personal_api_token_from_body() {
        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers: HeaderMap::new(),
            body: Bytes::from(r#"{"personal_api_key": "test-token"}"#),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: None,
            },
        };

        let (key, source) = find_personal_api_key_with_source(&request).unwrap();
        assert_eq!(key, "test-token");
        assert_eq!(source, ApiKeySource::Body);
    }

    #[test]
    fn test_decode_personal_api_token_from_query() {
        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers: HeaderMap::new(),
            body: Bytes::new(),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: Some("test-token".to_string()),
            },
        };

        let (key, source) = find_personal_api_key_with_source(&request).unwrap();
        assert_eq!(key, "test-token");
        assert_eq!(source, ApiKeySource::Query);
    }

    #[test]
    fn test_decode_personal_api_token_priority() {
        // Test that bearer token takes precedence over body and query
        let mut headers = HeaderMap::new();
        headers.insert(
            "Authorization",
            HeaderValue::from_static("Bearer bearer-token"),
        );
        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers,
            body: Bytes::from(r#"{"personal_api_key": "body-token"}"#),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: Some("query-token".to_string()),
            },
        };

        let (key, source) = find_personal_api_key_with_source(&request).unwrap();
        assert_eq!(key, "bearer-token");
        assert_eq!(source, ApiKeySource::AuthorizationHeader);
    }

    #[test]
    fn test_decode_personal_api_token_missing() {
        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers: HeaderMap::new(),
            body: Bytes::new(),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: None,
            },
        };

        let result = find_personal_api_key_with_source(&request);
        assert!(matches!(
            result,
            Err(FlagDefinitionsError::NoPersonalApiKeyError)
        ));
    }

    #[test]
    fn test_decode_personal_api_token_invalid_body() {
        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers: HeaderMap::new(),
            body: Bytes::from("invalid json"),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: None,
            },
        };

        let result = find_personal_api_key_with_source(&request);
        assert!(matches!(
            result,
            Err(FlagDefinitionsError::RequestDecodingError(_))
        ));
    }
}
