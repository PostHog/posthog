//! Observability HTTP surface (TDD §2.3):
//! - `GET /_health`  liveness — always 200; the `lifecycle` monitor owns health internally
//!   and triggers coordinated shutdown on stall rather than relying on K8s liveness kills.
//! - `GET /_ready`   readiness — 200 while running, 503 once graceful shutdown begins.
//! - `GET /metrics`  Prometheus exposition (only when the recorder is installed).
//! - `GET /`         service identity.

use std::future::ready;

use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use lifecycle::{LivenessHandler, ReadinessHandler};
use metrics_exporter_prometheus::PrometheusHandle;

/// Build the observability router. Pass `metrics = None` to omit `/metrics`.
pub fn router(
    service_name: &'static str,
    readiness: ReadinessHandler,
    liveness: LivenessHandler,
    metrics: Option<PrometheusHandle>,
) -> Router {
    let mut app = Router::new()
        .route("/", get(move || async move { service_name }))
        .route(
            "/_health",
            get(move || {
                let liveness = liveness.clone();
                async move { liveness.check().into_response() }
            }),
        )
        .route(
            "/_ready",
            get(move || {
                let readiness = readiness.clone();
                async move { readiness.check().await }
            }),
        );

    if let Some(handle) = metrics {
        app = app.route("/metrics", get(move || ready(handle.render())));
    }

    app
}
