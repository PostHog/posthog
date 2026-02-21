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
}

/// K8s liveness probe handler. Always returns 200 — liveness means "the process
/// is reachable." Health monitoring is handled internally by the manager's monitor
/// loop, which triggers coordinated graceful shutdown when a component stalls,
/// rather than letting K8s surprise-kill the pod.
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

/// Always-healthy liveness status. Implements [`IntoResponse`] for axum.
pub struct LivenessStatus;

impl IntoResponse for LivenessStatus {
    fn into_response(self) -> Response {
        (StatusCode::OK, "ok").into_response()
    }
}
