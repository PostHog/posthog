//! Liveness probe handler and internal health monitoring types.

use std::sync::Arc;

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};

/// Internal reference to a component's health state, used by the monitor's
/// health poll task. Not part of the public API.
#[derive(Clone)]
pub(crate) struct LivenessComponentRef {
    pub tag: String,
    pub healthy_until_ms: Arc<std::sync::atomic::AtomicI64>,
    pub stall_threshold: u32,
    pub health_gauge: metrics::Gauge,
}

/// K8s liveness probe handler. **Intentionally always returns 200.**
///
/// Health monitoring is handled internally by the lifecycle library's monitor loop,
/// not by K8s liveness probes. This is a deliberate design choice: when a component
/// stalls, the library triggers coordinated graceful shutdown instead of letting K8s
/// surprise-kill the pod via a failed liveness check.
#[derive(Clone)]
pub struct LivenessHandler;

impl LivenessHandler {
    pub(crate) fn new() -> Self {
        Self
    }

    pub fn check(&self) -> LivenessStatus {
        LivenessStatus
    }
}

/// Always-healthy liveness response. This is intentional — see [`LivenessHandler`].
pub struct LivenessStatus;

impl IntoResponse for LivenessStatus {
    fn into_response(self) -> Response {
        (StatusCode::OK, "ok").into_response()
    }
}
