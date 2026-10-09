//! Observability HTTP surface: `/_health`, `/_ready`, `/metrics`, `/`.
//!
//! `/_health` always returns 200: the `lifecycle` monitor owns health internally and triggers
//! coordinated shutdown on stall, rather than relying on K8s liveness kills. So the startup and
//! liveness probes stay on it, and a slow boot only holds `/_ready` closed.

use std::future::ready;
use std::sync::Arc;

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use lifecycle::{LivenessHandler, ReadinessHandler};
use metrics_exporter_prometheus::PrometheusHandle;

use crate::consumers::readiness::BootReadiness;

/// Build the observability router. Pass `metrics = None` to omit `/metrics`.
pub fn router(
    service_name: &'static str,
    readiness: ReadinessHandler,
    boot: Arc<BootReadiness>,
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
                let boot = boot.clone();
                async move { ready_response(&readiness, &boot).await }
            }),
        );

    if let Some(handle) = metrics {
        app = app.route("/metrics", get(move || ready(handle.render())));
    }

    app
}

/// 503 while lifecycle is shutting down, then 503 with the reason while the pod cannot carry live
/// traffic yet, else 200.
async fn ready_response(readiness: &ReadinessHandler, boot: &BootReadiness) -> Response {
    let lifecycle = readiness.check().await;
    if lifecycle != StatusCode::OK {
        return lifecycle.into_response();
    }
    match boot.check() {
        Ok(()) => StatusCode::OK.into_response(),
        Err(not_ready) => (StatusCode::SERVICE_UNAVAILABLE, not_ready.to_string()).into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::filters::manager::CatalogHandle;
    use crate::filters::FilterCatalog;

    async fn status_and_body(response: Response) -> (StatusCode, String) {
        let status = response.status();
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .unwrap();
        (status, String::from_utf8(body.to_vec()).unwrap())
    }

    #[tokio::test]
    async fn ready_is_503_with_the_reason_until_boot_recovery_ends() {
        let manager = lifecycle::Manager::builder("health-test")
            .with_trap_signals(false)
            .build();
        let readiness = manager.readiness_handler();
        let boot = BootReadiness::new(Arc::new(CatalogHandle::from_catalog(FilterCatalog::new())));

        assert_eq!(
            status_and_body(ready_response(&readiness, &boot).await).await,
            (
                StatusCode::SERVICE_UNAVAILABLE,
                "events consumer boot recovery in progress".to_string()
            ),
        );

        boot.mark_live();
        assert_eq!(
            ready_response(&readiness, &boot).await.status(),
            StatusCode::OK
        );
    }
}
