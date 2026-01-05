use std::{future::ready, sync::Arc};

use axum::{
    extract::State,
    response::IntoResponse,
    routing::{get, post},
    Router,
};
use common_metrics::{serve, setup_metrics_routes};
use health::HealthStatus;
use reqwest::StatusCode;
use tracing::info;

use crate::{app_context::AppContext, config::Config, router::process_exception_list};

async fn index() -> &'static str {
    "error tracking service"
}

async fn liveness(State(ctx): State<Arc<AppContext>>) -> HealthStatus {
    ready(ctx.health_registry.get_status()).await
}

async fn not_found() -> impl IntoResponse {
    (StatusCode::NOT_FOUND, "Not Found")
}

pub async fn start_server(config: &Config, context: Arc<AppContext>) -> () {
    let config = config.clone();
    let router = Router::<Arc<AppContext>>::new()
        .route("/", get(index))
        .route(
            "/:team_id/exception_list/process",
            post(process_exception_list),
        )
        .route("/_readiness", get(index))
        .route("/_liveness", get(liveness))
        .fallback(not_found)
        .with_state(context.clone());

    let router = setup_metrics_routes(router);
    let bind = format!("{}:{}", config.host, config.port);
    info!("Server started and listening on {}", bind);
    serve(router, &bind)
        .await
        .expect("failed to start serving metrics");
}
