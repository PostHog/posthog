//! Observability HTTP surface: `/_health`, `/_ready`, `/metrics`, `/`.
//!
//! `/_health` always returns 200: the `lifecycle` monitor owns health internally and triggers
//! coordinated shutdown on stall, rather than relying on K8s liveness kills.

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
