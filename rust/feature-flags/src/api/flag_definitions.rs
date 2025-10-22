use crate::{
    api::{auth, errors::FlagError},
    router::State as AppState,
    team::{team_models::Team, team_operations},
};
use axum::{
    debug_handler,
    extract::{Query, State},
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Json, Response},
};
use common_hypercache::{CacheSource, HyperCacheConfig, HyperCacheReader, KeyType};
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
        "Processing flag definitions request (always includes cohorts)"
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

    // Retrieve cached response from HyperCache (always with cohorts)
    let cached_response = get_from_cache(&state, &team).await?;

    Ok(Json(cached_response).into_response())
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

/// Fetches a team by its API token
/// Tries Redis cache first, then falls back to PostgreSQL
async fn fetch_team_by_token(state: &AppState, token: &str) -> Result<Team, FlagError> {
    let pg_reader = state.database_pools.non_persons_reader.clone();
    let token_str = token.to_string();

    team_operations::fetch_team_from_redis_with_fallback(
        state.redis_reader.clone(),
        state.redis_writer.clone(),
        token,
        || async move {
            Team::from_pg(pg_reader, &token_str)
                .await
                .map_err(|_| FlagError::TokenValidationError)
        },
    )
    .await
}

/// Retrieves the cached response using HyperCache (Redis + S3 fallback)
///
/// Always uses the cache with cohorts included to match Django's behavior and ensure
/// consistency across all clients accessing the same team's data. The cohorts are required
/// for proper local evaluation of flags that depend on cohort membership.
async fn get_from_cache(
    state: &AppState,
    team: &Team,
) -> Result<FlagDefinitionsResponse, FlagError> {
    // Configure HyperCache to use the flags_with_cohorts.json cache key
    // This ensures we always return cohort definitions along with flag definitions
    let hypercache_config = HyperCacheConfig::new(
        "feature_flags".to_string(),
        "flags_with_cohorts.json".to_string(),
        state.config.object_storage_region.clone(),
        state.config.object_storage_bucket.clone(),
    );

    // Set S3 endpoint if configured
    let mut config = hypercache_config;
    if !state.config.object_storage_endpoint.is_empty() {
        config.s3_endpoint = Some(state.config.object_storage_endpoint.clone());
    }

    // Create HyperCacheReader with the Redis client from state
    let hypercache_reader = HyperCacheReader::new(state.redis_reader.clone(), config)
        .await
        .map_err(|e| {
            warn!(team_id = team.id, error = %e, "Failed to create HyperCacheReader");
            FlagError::CacheMiss
        })?;

    // Use KeyType::team() to generate the proper cache key
    let team_key = KeyType::team(team.clone());

    // Try to get data from cache (Redis first, then S3 fallback)
    let (data, source) = hypercache_reader.get_with_source(&team_key).await?;

    let source_name = match source {
        CacheSource::Redis => "Redis",
        CacheSource::S3 => "S3",
    };
    info!(
        team_id = team.id,
        source = source_name,
        "Cache hit for flag definitions (with cohorts)"
    );

    Ok(data)
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
        return auth::validate_secret_api_token_for_team(state, &token, team.id).await;
    }

    // Try personal API key (with scope validation)
    if let Some(key) = auth::extract_personal_api_key(headers)? {
        return auth::validate_personal_api_key_with_scopes_for_team(state, &key, team).await;
    }

    Err(FlagError::NoAuthenticationProvided)
}
