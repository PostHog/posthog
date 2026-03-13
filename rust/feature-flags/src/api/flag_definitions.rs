use crate::{
    api::{
        auth,
        errors::{ClientFacingError, FlagError},
    },
    flags::{
        flag_analytics::{increment_request_count, is_billable_flag_key},
        flag_request::FlagRequestType,
        flag_service::FlagService,
    },
    handler::types::Library,
    metrics::consts::{
        FLAG_DEFINITIONS_AUTH_COUNTER, FLAG_DEFINITIONS_CACHE_HIT_COUNTER,
        FLAG_DEFINITIONS_CACHE_MISS_COUNTER, FLAG_DEFINITIONS_ETAG_COUNTER,
    },
    router::State as AppState,
    team::team_models::Team,
};
use axum::{
    debug_handler,
    extract::{Query, State},
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Json, Response},
};
use common_hypercache::{HyperCacheError, KeyType};
use common_metrics::inc;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::{info, warn};

/// Response for flag definitions endpoint
/// This is returned as raw JSON from cache to avoid deserialization overhead
pub type FlagDefinitionsResponse = Value;

/// Query parameters for the flag definitions endpoint
#[derive(Debug, Deserialize, Serialize)]
pub struct FlagDefinitionsQueryParams {
    /// Team API token - required to specify which team's flags to return
    pub token: String,
}

/// Flag definitions endpoint handler
///
/// This endpoint provides flag definitions for client-side evaluation.
///
/// **HTTP Method:** GET only (HEAD and OPTIONS also supported)
///
/// **Required Query Parameter:**
/// - `token`: Team API token (e.g., `phc_...`) - specifies which team's flags to return
///
/// **Authentication Methods (one required via Authorization header):**
/// 1. Team secret API tokens (secret_api_token, secret_api_token_backup)
/// 2. Personal API keys with feature_flag:read or feature_flag:write scopes
///
/// The authentication must have access to the team specified by the token parameter.
///
/// **Response:**
/// The response is retrieved directly from Redis cache using Django's cache keys.
/// No database fallback is provided - if the cache is empty, an error is returned.
/// The response always includes cohort definitions.
///
/// **ETag support:**
/// Supports `If-None-Match` header for conditional requests. Returns 304 Not Modified
/// when the client's ETag matches the current cache state, avoiding redundant data transfer.
/// ETags are stored by Django in Redis alongside the cached data.
#[debug_handler]
pub async fn flags_definitions(
    State(state): State<AppState>,
    Query(params): Query<FlagDefinitionsQueryParams>,
    headers: HeaderMap,
    method: Method,
) -> Result<Response, FlagError> {
    info!(
        method = %method,
        token = %params.token,
        "Processing flag definitions request"
    );

    // Only GET is supported for this read-only endpoint
    // HEAD and OPTIONS are handled for HTTP compliance
    if method != Method::GET {
        return Ok(handle_non_get_method(&method));
    }

    // Fetch team using the token from query parameter
    let team = fetch_team_by_token(&state, &params.token).await?;

    // Authenticate against the specified team
    authenticate_flag_definitions(&state, &team, &headers).await?;

    // Check rate limit for this team
    state.flag_definitions_limiter.check_rate_limit(team.id)?;

    // Check billing quota — matches Django's DECIDE_FEATURE_FLAG_QUOTA_CHECK behavior
    if state
        .feature_flags_billing_limiter
        .is_limited(&params.token)
        .await
    {
        return Err(FlagError::ClientFacing(ClientFacingError::BillingLimit));
    }

    let client_etag = extract_etag_from_header(headers.get("if-none-match"));
    let team_key = KeyType::team(team.clone());
    let current_etag = get_etag_from_redis(&state, &team_key).await;

    // If client sent a matching ETag, short-circuit with 304 (skip full data fetch)
    if let (Some(ref client_val), Some(ref current_val)) = (&client_etag, &current_etag) {
        if client_val == current_val {
            inc(
                FLAG_DEFINITIONS_ETAG_COUNTER,
                &[("result".to_string(), "hit".to_string())],
                1,
            );
            return Ok(not_modified_response(current_val));
        }
    }

    let etag_result = if client_etag.is_some() {
        "miss"
    } else {
        "none"
    };
    inc(
        FLAG_DEFINITIONS_ETAG_COUNTER,
        &[("result".to_string(), etag_result.to_string())],
        1,
    );

    // Retrieve cached response from HyperCache (always with cohorts)
    let cached_response = get_from_cache(&state, &team_key, team.id).await?;

    // Record usage for billing, filtering out non-billable flags (surveys, product tours).
    // Placed after the ETag/304 path intentionally: 304 responses skip billing,
    // matching Django's /local_evaluation behavior.
    if !*state.config.skip_writes && has_billable_flags(&cached_response) {
        let library = Library::from_headers(&headers);
        if let Err(e) = increment_request_count(
            state.redis_client.clone(),
            team.id,
            1,
            FlagRequestType::FlagDefinitions,
            Some(library),
        )
        .await
        {
            inc(
                "flag_request_redis_error",
                &[("error".to_string(), e.to_string())],
                1,
            );
        }
    }

    Ok(ok_response_with_etag(
        cached_response,
        current_etag.as_deref(),
    ))
}

fn format_weak_etag(raw: &str) -> String {
    format!("W/\"{}\"", raw)
}

/// Build a 304 Not Modified response with ETag and Cache-Control headers.
fn not_modified_response(etag: &str) -> Response {
    (
        StatusCode::NOT_MODIFIED,
        [
            ("etag", format_weak_etag(etag)),
            ("cache-control", "private, must-revalidate".to_string()),
        ],
    )
        .into_response()
}

/// Build a 200 OK JSON response, attaching ETag and Cache-Control if available.
fn ok_response_with_etag(data: Value, etag: Option<&str>) -> Response {
    match etag {
        Some(etag_val) => (
            StatusCode::OK,
            [
                ("content-type", "application/json".to_string()),
                ("etag", format_weak_etag(etag_val)),
                ("cache-control", "private, must-revalidate".to_string()),
            ],
            Json(data),
        )
            .into_response(),
        None => Json(data).into_response(),
    }
}

/// Extract the raw ETag value from an `If-None-Match` header.
///
/// Handles both strong ETags (`"abc123"`) and weak ETags (`W/"abc123"`) per RFC 7232.
/// Returns `None` if the header is absent or empty.
fn extract_etag_from_header(header: Option<&axum::http::HeaderValue>) -> Option<String> {
    let value = header?.to_str().ok()?;
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return None;
    }

    let etag = if trimmed.starts_with("W/\"") {
        // Weak ETag: W/"abc123" → strip W/ prefix, then strip quotes
        &trimmed[2..]
    } else {
        trimmed
    };

    let etag = etag.trim_matches('"');
    if etag.is_empty() {
        None
    } else {
        Some(etag.to_string())
    }
}

/// Read the ETag for a team's flag definitions from Redis.
///
/// Django stores ETags as separate Redis keys with an `:etag` suffix,
/// pickle-serialized via Django's cache framework. Returns `None` if the
/// ETag is unavailable (cache miss, Redis error, deserialization error)
/// — this gracefully degrades to always returning 200 with full data.
async fn get_etag_from_redis(state: &AppState, team_key: &KeyType) -> Option<String> {
    let config = state.flags_with_cohorts_hypercache_reader.config();
    let cache_key = config.get_redis_cache_key(team_key);
    let etag_key = format!("{}:etag", cache_key);

    match state.redis_client.get_raw_bytes(etag_key.clone()).await {
        Ok(raw_bytes) => match serde_pickle::from_slice::<String>(&raw_bytes, Default::default()) {
            Ok(etag) if !etag.is_empty() => Some(etag),
            Ok(_) => None,
            Err(e) => {
                warn!(
                    etag_key = %etag_key,
                    error = %e,
                    "Failed to deserialize ETag from Redis"
                );
                None
            }
        },
        Err(e) => {
            warn!(
                etag_key = %etag_key,
                error = %e,
                "Failed to read ETag from Redis"
            );
            inc(
                FLAG_DEFINITIONS_ETAG_COUNTER,
                &[("result".to_string(), "redis_error".to_string())],
                1,
            );
            None
        }
    }
}

/// Handles non-GET HTTP methods (HEAD, OPTIONS, and unsupported methods)
fn handle_non_get_method(method: &Method) -> Response {
    match *method {
        Method::HEAD => (
            StatusCode::OK,
            [("content-type", "application/json")],
            axum::body::Body::empty(),
        )
            .into_response(),
        Method::OPTIONS => {
            (StatusCode::NO_CONTENT, [("allow", "GET, OPTIONS, HEAD")]).into_response()
        }
        _ => (
            StatusCode::METHOD_NOT_ALLOWED,
            [("allow", "GET, OPTIONS, HEAD")],
        )
            .into_response(),
    }
}

/// Fetches a team by its API token, delegating to FlagService for consistent
/// negative caching, metrics, and error handling across all endpoints.
async fn fetch_team_by_token(state: &AppState, token: &str) -> Result<Team, FlagError> {
    let flag_service = FlagService::new(
        state.redis_client.clone(),
        state.database_pools.non_persons_reader.clone(),
        state.team_hypercache_reader.clone(),
        state.flags_hypercache_reader.clone(),
        state.team_negative_cache.clone(),
    );
    flag_service.verify_token_and_get_team(token).await
}

/// Retrieves the cached response using the pre-initialized HyperCacheReader
///
/// Always uses the cache with cohorts included to match Django's behavior and ensure
/// consistency across all clients accessing the same team's data. The cohorts are required
/// for proper local evaluation of flags that depend on cohort membership.
///
/// Emits metrics on both cache hit (with source label) and cache miss (with reason label)
/// to support dashboards and alerting during the migration from Django.
async fn get_from_cache(
    state: &AppState,
    team_key: &KeyType,
    team_id: i32,
) -> Result<FlagDefinitionsResponse, FlagError> {
    let result = state
        .flags_with_cohorts_hypercache_reader
        .get_with_source(team_key)
        .await;

    match result {
        Ok((data, source)) => {
            let source_name = source.as_log_str();
            inc(
                FLAG_DEFINITIONS_CACHE_HIT_COUNTER,
                &[("source".to_string(), source_name.to_string())],
                1,
            );
            info!(
                team_id = team_id,
                source = source_name,
                "Cache hit for flag definitions"
            );
            Ok(data)
        }
        Err(e) => {
            let reason = match &e {
                HyperCacheError::CacheMiss => "cache_miss",
                HyperCacheError::S3(_) => "s3_error",
                HyperCacheError::Redis(_) => "redis_error",
                HyperCacheError::Json(_) => "json_parse_error",
                HyperCacheError::Timeout(_) => "timeout",
            };
            inc(
                FLAG_DEFINITIONS_CACHE_MISS_COUNTER,
                &[("reason".to_string(), reason.to_string())],
                1,
            );
            warn!(
                team_id = team_id,
                reason = reason,
                error = %e,
                "Flag definitions cache miss"
            );
            Err(FlagError::from(e))
        }
    }
}

/// Authenticates flag definitions requests using team secret API tokens or personal API keys
///
/// Validates that the authentication credential has access to the specified team.
///
/// Supports two authentication methods:
/// 1. Team secret API tokens (secret_api_token, secret_api_token_backup) from Authorization header
/// 2. Personal API keys with feature_flag:read or feature_flag:write scopes
///
/// Priority: Secret API tokens take precedence over personal API keys when both are provided.
///
/// Returns Ok(()) if authentication succeeds, Err otherwise
async fn authenticate_flag_definitions(
    state: &AppState,
    team: &Team,
    headers: &HeaderMap,
) -> Result<(), FlagError> {
    // Try team secret token first (from Authorization header only)
    // Secret tokens have priority over personal API keys
    if let Some(token) = auth::extract_team_secret_token(headers) {
        let result = auth::validate_secret_api_token_for_team(state, &token, team.id).await;
        if result.is_ok() {
            inc(
                FLAG_DEFINITIONS_AUTH_COUNTER,
                &[("method".to_string(), "secret_api_key".to_string())],
                1,
            );
        }
        return result;
    }

    // Try personal API key (with scope validation)
    if let Some(key) = auth::extract_personal_api_key(headers)? {
        let result = auth::validate_personal_api_key_with_scopes_for_team(state, &key, team).await;
        if result.is_ok() {
            inc(
                FLAG_DEFINITIONS_AUTH_COUNTER,
                &[("method".to_string(), "personal_api_key".to_string())],
                1,
            );
        }
        return result;
    }

    Err(FlagError::NoAuthenticationProvided)
}

/// Checks whether the cached flag definitions contain any billable flags.
///
/// Returns false if all flags are survey or product tour targeting flags,
/// matching Django's `local_evaluation` billing filter. The cached response
/// has a `"flags"` array where each entry has a `"key"` field.
fn has_billable_flags(response: &Value) -> bool {
    let Some(flags) = response.get("flags").and_then(|f| f.as_array()) else {
        return false;
    };

    flags.iter().any(|flag| {
        let key = flag.get("key").and_then(|k| k.as_str()).unwrap_or("");
        is_billable_flag_key(key)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use serde_json::json;

    #[rstest]
    #[case::regular_flags(json!({"flags": [{"key": "my-feature"}, {"key": "another-flag"}]}), true)]
    #[case::only_survey_flags(json!({"flags": [{"key": "survey-targeting-abc"}, {"key": "survey-targeting-xyz"}]}), false)]
    #[case::only_product_tour_flags(json!({"flags": [{"key": "product-tour-targeting-abc"}]}), false)]
    #[case::mixed_survey_and_regular(json!({"flags": [{"key": "survey-targeting-abc"}, {"key": "my-feature"}]}), true)]
    #[case::empty_flags_array(json!({"flags": []}), false)]
    #[case::no_flags_key(json!({"cohorts": {}}), false)]
    #[case::only_survey_and_tour_flags(json!({"flags": [{"key": "survey-targeting-abc"}, {"key": "product-tour-targeting-xyz"}]}), false)]
    fn test_has_billable_flags(#[case] response: Value, #[case] expected: bool) {
        assert_eq!(has_billable_flags(&response), expected);
    }

    #[test]
    fn test_extract_etag_from_header_weak() {
        let val = axum::http::HeaderValue::from_static("W/\"a1b2c3d4e5f6g7h8\"");
        assert_eq!(
            extract_etag_from_header(Some(&val)),
            Some("a1b2c3d4e5f6g7h8".to_string())
        );
    }

    #[test]
    fn test_extract_etag_from_header_strong() {
        let val = axum::http::HeaderValue::from_static("\"a1b2c3d4e5f6g7h8\"");
        assert_eq!(
            extract_etag_from_header(Some(&val)),
            Some("a1b2c3d4e5f6g7h8".to_string())
        );
    }

    #[test]
    fn test_extract_etag_from_header_none() {
        assert_eq!(extract_etag_from_header(None), None);
    }

    #[test]
    fn test_extract_etag_from_header_empty() {
        let val = axum::http::HeaderValue::from_static("");
        assert_eq!(extract_etag_from_header(Some(&val)), None);
    }

    #[test]
    fn test_extract_etag_from_header_bare_value() {
        let val = axum::http::HeaderValue::from_static("a1b2c3d4e5f6g7h8");
        assert_eq!(
            extract_etag_from_header(Some(&val)),
            Some("a1b2c3d4e5f6g7h8".to_string())
        );
    }

    #[test]
    fn test_extract_etag_from_header_empty_weak() {
        let val = axum::http::HeaderValue::from_static("W/\"\"");
        assert_eq!(extract_etag_from_header(Some(&val)), None);
    }

    #[test]
    fn test_extract_etag_from_header_wildcard_treated_as_literal() {
        // RFC 7232 allows `*` to match any ETag, but we treat it as a literal
        // value. This means it will never match a stored ETag, which is safe —
        // the client just gets a 200 with full data instead of a 304.
        let val = axum::http::HeaderValue::from_static("*");
        assert_eq!(extract_etag_from_header(Some(&val)), Some("*".to_string()));
    }

    #[test]
    fn test_extract_etag_from_header_multiple_etags_no_special_handling() {
        // RFC 7232 allows comma-separated ETags, but we don't parse them
        // individually. The whole value is treated as a single string, so it
        // won't match any stored ETag — the client gets a 200 with full data.
        let val = axum::http::HeaderValue::from_static("\"etag1\", \"etag2\"");
        assert_eq!(
            extract_etag_from_header(Some(&val)),
            Some("etag1\", \"etag2".to_string())
        );
    }
}
