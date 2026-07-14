use axum::body::Body;
use axum::extract::{Path, State};
use axum::http::{header, StatusCode};
use axum::response::Response;

use crate::api::ApiError;
use crate::state::AppState;

/// Proxy `GET /api/pods/:name/debug/<rest>` to the pod's debug API. The
/// upstream body is piped through as a byte stream, which also carries SSE
/// (`/debug/events`) without buffering.
pub async fn proxy_debug(
    State(state): State<AppState>,
    Path((name, rest)): Path<(String, String)>,
) -> Result<Response, ApiError> {
    let target = state
        .pods
        .resolve_proxy_target(&state.config, &name)
        .await
        .map_err(|e| ApiError::unavailable(format!("pod discovery unavailable: {e:#}")))?
        .ok_or_else(|| ApiError::not_found(format!("no matching pod '{name}'")))?;

    let url = format!("http://{target}/debug/{rest}");
    let upstream =
        state.http.get(&url).send().await.map_err(|e| {
            ApiError::upstream(format!("debug API request to '{name}' failed: {e}"))
        })?;

    let status =
        StatusCode::from_u16(upstream.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
    let mut builder = Response::builder()
        .status(status)
        .header(header::CACHE_CONTROL, "no-cache");
    if let Some(content_type) = upstream.headers().get(header::CONTENT_TYPE) {
        builder = builder.header(header::CONTENT_TYPE, content_type);
    }
    builder
        .body(Body::from_stream(upstream.bytes_stream()))
        .map_err(|e| ApiError::upstream(format!("failed to build proxy response: {e}")))
}
