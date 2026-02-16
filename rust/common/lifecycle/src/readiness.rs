//! K8s readiness probe handler.

use axum::http::StatusCode;
use tokio_util::sync::CancellationToken;

/// Axum-compatible readiness probe; returns 200 if not shutting down, 503 if shutdown has begun.
#[derive(Clone)]
pub struct ReadinessHandler {
    shutdown_token: CancellationToken,
}

impl ReadinessHandler {
    pub fn new(shutdown_token: CancellationToken) -> Self {
        Self { shutdown_token }
    }

    /// Returns OK or SERVICE_UNAVAILABLE based on shutdown token; no I/O.
    pub async fn check(&self) -> StatusCode {
        if self.shutdown_token.is_cancelled() {
            StatusCode::SERVICE_UNAVAILABLE
        } else {
            StatusCode::OK
        }
    }
}
