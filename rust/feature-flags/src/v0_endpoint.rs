use std::collections::HashMap;

use axum::{debug_handler, Json};
use bytes::Bytes;
// TODO: stream this instead
use axum::extract::{MatchedPath, Query, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;
use tracing::instrument;

use crate::api::FlagValue;
use crate::{
    api::{FlagError, FlagsResponse},
    router,
    v0_request::{FlagRequest, FlagsQueryParams},
};

/// Feature flag evaluation endpoint.
/// Only supports a specific shape of data, and rejects any malformed data.

#[instrument(
    skip_all,
    fields(
        path,
        token,
        batch_size,
        user_agent,
        content_encoding,
        content_type,
        version,
        compression,
        historical_migration
    )
)]
#[debug_handler]
pub async fn flags(
    state: State<router::State>,
    InsecureClientIp(ip): InsecureClientIp,
    meta: Query<FlagsQueryParams>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<Json<FlagsResponse>, FlagError> {
    let user_agent = headers
        .get("user-agent")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    let content_encoding = headers
        .get("content-encoding")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));

    tracing::Span::current().record("user_agent", user_agent);
    tracing::Span::current().record("content_encoding", content_encoding);
    tracing::Span::current().record("version", meta.version.clone());
    tracing::Span::current().record("method", method.as_str());
    tracing::Span::current().record("path", path.as_str().trim_end_matches('/'));
    tracing::Span::current().record("ip", ip.to_string());

    let request = match headers
        .get("content-type")
        .map_or("", |v| v.to_str().unwrap_or(""))
    {
        "application/json" => {
            tracing::Span::current().record("content_type", "application/json");
            FlagRequest::from_bytes(body)
        }
        ct => {
            return Err(FlagError::RequestDecodingError(format!(
                "unsupported content type: {}",
                ct
            )));
        }
    }?;

    let token = request
        .extract_and_verify_token(state.redis.clone(), state.postgres.clone())
        .await?;

    let distinct_id = request.extract_distinct_id()?;

    tracing::Span::current().record("token", &token);
    tracing::Span::current().record("distinct_id", &distinct_id);

    tracing::debug!("request: {:?}", request);

    // TODO: Some actual processing for evaluating the feature flag

    Ok(Json(FlagsResponse {
        error_while_computing_flags: false,
        feature_flags: HashMap::from([
            (
                "beta-feature".to_string(),
                FlagValue::String("variant-1".to_string()),
            ),
            ("rollout-flag".to_string(), FlagValue::Boolean(true)),
        ]),
    }))
}
