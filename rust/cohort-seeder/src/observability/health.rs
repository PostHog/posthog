//! Observability leaf: the liveness/readiness HTTP router served alongside the Prometheus scrape
//! endpoint. Depends on `lifecycle`, `axum`, and the Prometheus exporter, never on another seeder module.

use std::future::ready;

use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use lifecycle::{LivenessHandler, ReadinessHandler};
use metrics_exporter_prometheus::PrometheusHandle;

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
