use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::IntoResponse;
use tracing::{info, warn};

use crate::router::State as AppState;

pub async fn ai_handler(
    State(_state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> impl IntoResponse {
    // Log all headers
    info!("Received request to /ai endpoint");
    info!("Headers:");
    for (name, value) in headers.iter() {
        if let Ok(v) = value.to_str() {
            info!("  {}: {}", name, v);
        } else {
            warn!("  {}: <binary data>", name);
        }
    }

    // Log body size
    info!("Body size: {} bytes", body.len());

    // Try to log body as string if possible, otherwise log first 1000 bytes as hex
    if let Ok(body_str) = std::str::from_utf8(&body) {
        info!("Body (as string):\n{}", body_str);
    } else {
        let preview_len = std::cmp::min(1000, body.len());
        let hex_preview: String = body[..preview_len]
            .iter()
            .map(|b| format!("{:02x}", b))
            .collect::<Vec<_>>()
            .join(" ");
        info!("Body (hex preview, first {} bytes):\n{}", preview_len, hex_preview);
        if body.len() > preview_len {
            info!("... {} more bytes", body.len() - preview_len);
        }
    }

    // Return 200 OK
    StatusCode::OK
}

pub async fn options() -> impl IntoResponse {
    StatusCode::OK
}
