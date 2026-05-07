use axum::http::HeaderMap;

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
    is_internal_request_inner(
        context.state.config.internal_request_token.as_deref(),
        &context.headers,
    )
}

fn is_internal_request_inner(internal_token: Option<&str>, headers: &HeaderMap) -> bool {
    use subtle::ConstantTimeEq;

    let Some(internal_token) = internal_token else {
        // No internal token configured, so no requests are internal
        return false;
    };

    // Trim the configured token so stray whitespace (common in K8s secret mounts
    // and CI-generated env files) doesn't silently break comparison.
    let internal_token = internal_token.trim();

    // Empty token should never be considered valid
    if internal_token.is_empty() {
        return false;
    }

    match crate::api::auth::extract_bearer_token(headers) {
        // Trim the wire token symmetrically with the configured one, otherwise
        // a stray newline on either side breaks comparison silently. Use a
        // constant-time compare to avoid leaking the configured token via
        // response-time differences.
        Some(auth_token) => {
            let auth_token = auth_token.trim();
            !auth_token.is_empty()
                && auth_token
                    .as_bytes()
                    .ct_eq(internal_token.as_bytes())
                    .into()
        }
        None => false,
    }
}

#[cfg(test)]
mod tests {
    use super::is_internal_request_inner;
    use axum::http::{HeaderMap, HeaderValue};

    #[test]
    fn test_no_internal_token_configured() {
        assert!(!is_internal_request_inner(None, &HeaderMap::new()));
    }

    #[test]
    fn test_blank_internal_token_configured() {
        assert!(!is_internal_request_inner(Some(""), &HeaderMap::new()));
    }

    #[test]
    fn test_whitespace_internal_token_configured() {
        assert!(!is_internal_request_inner(Some("   "), &HeaderMap::new()));
    }

    #[test]
    fn test_missing_authorization_header() {
        assert!(!is_internal_request_inner(
            Some("valid_token"),
            &HeaderMap::new()
        ));
    }

    #[test]
    fn test_empty_bearer_value() {
        let mut headers = HeaderMap::new();
        headers.insert("authorization", HeaderValue::from_str("Bearer ").unwrap());
        assert!(!is_internal_request_inner(Some("valid_token"), &headers));
    }

    #[test]
    fn test_whitespace_bearer_value() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_str("Bearer    ").unwrap(),
        );
        assert!(!is_internal_request_inner(Some("valid_token"), &headers));
    }

    #[test]
    fn test_non_matching_bearer_token() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_str("Bearer wrong_token").unwrap(),
        );
        assert!(!is_internal_request_inner(Some("correct_token"), &headers));
    }

    #[test]
    fn test_matching_bearer_token() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_str("Bearer secret_token").unwrap(),
        );
        assert!(is_internal_request_inner(Some("secret_token"), &headers));
    }

    #[test]
    fn test_case_sensitive_token_match() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_str("Bearer secret_token").unwrap(),
        );
        // Should be case sensitive - different case means no match
        assert!(!is_internal_request_inner(Some("Secret_Token"), &headers));
    }

    #[test]
    fn test_malformed_authorization_header() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_str("NotBearer valid_token").unwrap(),
        );
        assert!(!is_internal_request_inner(Some("valid_token"), &headers));
    }

    #[test]
    fn test_configured_token_with_trailing_whitespace_matches() {
        // Simulates K8s secret mount / env file leaving a trailing newline on the configured value.
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_str("Bearer secret_token").unwrap(),
        );
        assert!(is_internal_request_inner(Some("secret_token\n"), &headers));
    }

    #[test]
    fn test_different_length_tokens_do_not_match() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_str("Bearer secret").unwrap(),
        );
        assert!(!is_internal_request_inner(Some("secret_token"), &headers));
    }
}
