use std::{
    sync::atomic::{AtomicUsize, Ordering},
    time::Instant,
};

use axum::{
    body::Body,
    extract::{MatchedPath, Request},
    middleware::Next,
    response::IntoResponse,
};
use metrics::{gauge, histogram};

// Global atomic counter for active connections
static ACTIVE_CONNECTIONS: AtomicUsize = AtomicUsize::new(0);
pub const METRIC_CAPTURE_REQUEST_SIZE_BYTES: &str = "capture_request_size_bytes";
const METRIC_CAPTURE_ACTIVE_CONNECTIONS: &str = "capture_active_connections";
const METRIC_HTTP_REQUESTS_TOTAL: &str = "http_requests_total";
const METRIC_HTTP_REQUESTS_DURATION_SECONDS: &str = "http_requests_duration_seconds";

/// Middleware to record some common HTTP metrics
/// Generic over B to allow for arbitrary body types (eg Vec<u8>, Streams, a deserialized thing, etc)
/// Someday tower-http might provide a metrics middleware: https://github.com/tower-rs/tower-http/issues/57
pub async fn track_metrics(req: Request<Body>, next: Next) -> impl IntoResponse {
    let start = Instant::now();

    let path = if let Some(matched_path) = req.extensions().get::<MatchedPath>() {
        matched_path.as_str().to_owned()
    } else {
        req.uri().path().to_owned()
    };

    let method = req.method().clone();

    // Track active connections
    let connections = ACTIVE_CONNECTIONS.fetch_add(1, Ordering::Relaxed) + 1;
    gauge!(METRIC_CAPTURE_ACTIVE_CONNECTIONS).set(connections as f64);

    // Track request content length
    let content_length = req
        .headers()
        .get("content-length")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(0);

    if content_length > 0 {
        // Record request size with context
        histogram!(
            METRIC_CAPTURE_REQUEST_SIZE_BYTES,
            "endpoint" => path.clone(),
        )
        .record(content_length as f64);
    }

    // Run the rest of the request handling first, so we can measure it and get response
    // codes.
    let response = next.run(req).await;

    let latency = start.elapsed().as_secs_f64();
    // Clean up connection count
    let connections = ACTIVE_CONNECTIONS.fetch_sub(1, Ordering::Relaxed) - 1;
    gauge!(METRIC_CAPTURE_ACTIVE_CONNECTIONS).set(connections as f64);

    let status = response.status().as_u16().to_string();

    let labels = [
        ("method", method.to_string()),
        ("path", path),
        ("status", status),
    ];

    metrics::counter!(METRIC_HTTP_REQUESTS_TOTAL, &labels).increment(1);
    metrics::histogram!(METRIC_HTTP_REQUESTS_DURATION_SECONDS, &labels).record(latency);

    response
}
