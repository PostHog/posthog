//! K8s readiness probe handler.

use axum::http::StatusCode;
use tokio_util::sync::CancellationToken;

/// K8s readiness probe handler. Returns 200 while the app is running, 503 after shutdown
/// begins. K8s stops routing traffic to the pod when readiness fails. No per-component
/// logic — readiness is purely "is the app accepting work?"
/// (see test `readiness_200_until_shutdown_then_503`)
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
