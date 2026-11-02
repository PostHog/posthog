//! K8s readiness probe handler.

use axum::http::StatusCode;
use tokio_util::sync::CancellationToken;

/// K8s readiness probe handler. Returns 200 while the app is running, 503 once it
/// drains or shuts down. K8s stops routing traffic to the pod when readiness fails.
/// No per-component logic — readiness is purely "is the app accepting work?"
/// (see tests `readiness_200_until_shutdown_then_503`, `prestop_drain_serves_until_max`)
#[derive(Clone)]
pub struct ReadinessHandler {
    drain_token: CancellationToken,
}

impl ReadinessHandler {
    pub(crate) fn new(drain_token: CancellationToken) -> Self {
        Self { drain_token }
    }

    /// False once the app drains or shuts down; no I/O. A server can use it to ask
    /// clients to reconnect through the Service to a pod that stays.
    pub fn is_ready(&self) -> bool {
        !self.drain_token.is_cancelled()
    }

    /// Returns OK or SERVICE_UNAVAILABLE based on [`is_ready`](Self::is_ready); no I/O.
    pub async fn check(&self) -> StatusCode {
        if self.is_ready() {
            StatusCode::OK
        } else {
            StatusCode::SERVICE_UNAVAILABLE
        }
    }
}
