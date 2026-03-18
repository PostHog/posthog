use std::{
    sync::atomic::{AtomicUsize, Ordering},
    time::{Duration, Instant},
};

use axum::{
    body::Body,
    extract::{MatchedPath, Request},
    http::StatusCode,
    middleware::Next,
    response::IntoResponse,
    routing::Router,
};
use metrics::gauge;

// Re-exporting from health crate for backwards compatibility
pub use health::{get_shutdown_status, set_shutdown_status, ShutdownStatus};

// Global atomic counter for active connections
static ACTIVE_CONNECTIONS: AtomicUsize = AtomicUsize::new(0);

// Guard to ensure connection count is decremented even on panic
struct ConnectionGuard;

impl Drop for ConnectionGuard {
    fn drop(&mut self) {
        let connections = ACTIVE_CONNECTIONS
            .fetch_sub(1, Ordering::Relaxed)
            .saturating_sub(1);
        gauge!(
            METRIC_CAPTURE_ACTIVE_CONNECTIONS,
            "shutdown_status" => get_shutdown_status().as_str()
        )
        .set(connections as f64);
    }
}
const METRIC_CAPTURE_ACTIVE_CONNECTIONS: &str = "capture_active_connections";
const METRIC_HTTP_REQUESTS_TOTAL: &str = "http_requests_total";
const METRIC_HTTP_REQUESTS_DURATION_SECONDS: &str = "http_requests_duration_seconds";
const METRIC_CAPTURE_REQUEST_TIMED_OUT: &str = "middleware_request_timed_out_total";
const METRIC_CAPTURE_TIMEOUT_MIDDLEWARE_PASS: &str = "middleware_pass_total";

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

    // Track active connections with shutdown status label
    let connections = ACTIVE_CONNECTIONS.fetch_add(1, Ordering::Relaxed) + 1;
    gauge!(
        METRIC_CAPTURE_ACTIVE_CONNECTIONS,
        "shutdown_status" => get_shutdown_status().as_str()
    )
    .set(connections as f64);
    let _guard = ConnectionGuard;

    // Run the rest of the request handling first, so we can measure it and get response
    // codes.
    let response = next.run(req).await;

    let latency = start.elapsed().as_secs_f64();
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

pub fn apply_request_timeout<S>(
    router: Router<S>,
    request_timeout_seconds: Option<u64>,
) -> Router<S>
where
    S: Clone + Send + Sync + 'static,
{
    if let Some(request_timeout_seconds) = request_timeout_seconds {
        let timeout_duration = Duration::from_secs(request_timeout_seconds);
        tracing::info!(
            "Applying request timeout middleware with duration: {:?}",
            timeout_duration
        );

        return router.layer(axum::middleware::from_fn(
            move |req: axum::extract::Request, next: axum::middleware::Next| async move {
                let start = std::time::Instant::now();
                let method = req.method().to_string();
                let path = req.uri().path().to_string();
                let client_ip = req
                    .headers()
                    .get("X-Forwarded-For")
                    .and_then(|v| v.to_str().ok())
                    .and_then(|s| s.split(',').next())
                    .map_or_else(|| "UNKNOWN".to_string(), |s| s.trim().to_string());
                let request_id = req
                    .headers()
                    .get("X-REQUEST-ID")
                    .and_then(|v| v.to_str().ok())
                    .map_or_else(|| "UNKNOWN".to_string(), |s| s.to_string());
                let content_type = req
                    .headers()
                    .get("Content-Type")
                    .and_then(|v| v.to_str().ok())
                    .map_or_else(|| "UNKNOWN".to_string(), |s| s.to_string());
                let content_length = req
                    .headers()
                    .get("Content-Length")
                    .and_then(|v| v.to_str().ok())
                    .map_or_else(|| "UNKNOWN".to_string(), |s| s.to_string());
                let user_agent = req
                    .headers()
                    .get("User-Agent")
                    .and_then(|v| v.to_str().ok())
                    .map_or_else(|| "UNKNOWN".to_string(), |s| s.to_string());
                let envoy_ip = req
                    .headers()
                    .get("X-Envoy-External-Address")
                    .and_then(|v| v.to_str().ok())
                    .map_or_else(|| "UNKNOWN".to_string(), |s| s.to_string());

                match tokio::time::timeout(timeout_duration, next.run(req)).await {
                    Ok(response) => {
                        let elapsed = start.elapsed();
                        let threshold_exceeded = elapsed.as_secs() > request_timeout_seconds;

                        let mut tags = vec![
                            ("method", method.clone()),
                            ("path", path.clone()),
                            ("status", response.status().as_u16().to_string()),
                        ];
                        if threshold_exceeded {
                            tags.push(("threshold", "exceeded".to_string()));
                        } else {
                            tags.push(("threshold", "respected".to_string()));
                        }
                        metrics::counter!(METRIC_CAPTURE_TIMEOUT_MIDDLEWARE_PASS, &tags)
                            .increment(1);

                        response
                    }
                    Err(_) => {
                        let elapsed = start.elapsed();
                        let threshold_exceeded = elapsed.as_secs() > request_timeout_seconds;

                        let mut tags = vec![("method", method.clone()), ("path", path.clone())];
                        if threshold_exceeded {
                            tags.push(("threshold", "exceeded".to_string()));
                        } else {
                            tags.push(("threshold", "respected".to_string()));
                        }
                        metrics::counter!(METRIC_CAPTURE_REQUEST_TIMED_OUT, &tags).increment(1);

                        tracing::warn!(
                            method = method,
                            path = path,
                            request_id = request_id,
                            client_ip = client_ip,
                            envoy_ip = envoy_ip,
                            content_type = content_type,
                            content_length = content_length,
                            user_agent = user_agent,
                            timeout_threshold_seconds = request_timeout_seconds,
                            threshold_exceeded = threshold_exceeded,
                            elapsed_seconds = elapsed.as_secs_f64(),
                            "Request timed out"
                        );

                        // This should be a 408 Request Timeout, but we need to set it to
                        // a >500 status code to avoid breaking SDK integrations.
                        (StatusCode::GATEWAY_TIMEOUT, "Request timeout").into_response()
                    }
                }
            },
        ));
    }

    // no timeout configured
    tracing::info!("No request timeout middleware applied");
    router
}
