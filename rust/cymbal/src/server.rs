use std::sync::Arc;

use axum::{routing::get, Router};
use common_metrics::{serve, track_metrics};
use metrics_exporter_prometheus::{Matcher, PrometheusBuilder, PrometheusHandle};
use tracing::info;

use crate::{
    app_context::AppContext, config::Config, metric_consts::PROCESS_REQUEST_DURATION_SECONDS,
    router::get_router,
};

fn setup_metrics_routes(router: Router) -> Router {
    let recorder_handle = setup_metrics_recorder();

    router
        .route(
            "/metrics",
            get(move || std::future::ready(recorder_handle.render())),
        )
        .layer(axum::middleware::from_fn(track_metrics))
}

fn setup_metrics_recorder() -> PrometheusHandle {
    const DEFAULT_BUCKETS: &[f64] = &[
        1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
    ];
    const PROCESS_REQUEST_DURATION_BUCKETS_SECONDS: &[f64] = &[
        0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0,
    ];

    PrometheusBuilder::new()
        .set_buckets(DEFAULT_BUCKETS)
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Full(PROCESS_REQUEST_DURATION_SECONDS.to_string()),
            PROCESS_REQUEST_DURATION_BUCKETS_SECONDS,
        )
        .unwrap()
        .install_recorder()
        .unwrap()
}

pub async fn start_server(config: Config, context: Arc<AppContext>) -> () {
    let router = get_router(context);
    let router = setup_metrics_routes(router);
    let bind = format!("{}:{}", config.host, config.port);
    info!("Server started and listening on {}", bind);
    serve(router, &bind)
        .await
        .expect("failed to start serving metrics");
}
