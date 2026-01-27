mod exception_list;

use axum::routing::{get, post};
use axum::{extract::State, response::IntoResponse, Router};

pub use exception_list::*;
use health::HealthStatus;
use reqwest::StatusCode;
use std::future::ready;
use std::sync::Arc;

use crate::app_context::AppContext;

async fn index() -> &'static str {
    "error tracking service"
}

async fn liveness(State(ctx): State<Arc<AppContext>>) -> HealthStatus {
    ready(ctx.health_registry.get_status()).await
}

async fn not_found() -> impl IntoResponse {
    (StatusCode::NOT_FOUND, "Not Found")
}

pub fn get_router(context: Arc<AppContext>) -> Router {
    Router::new()
        .route("/", get(index))
        .route(
            "/:team_id/exception_list/process",
            post(process_exception_list),
        )
        .route("/_readiness", get(index))
        .route("/_liveness", get(liveness))
        .fallback(not_found)
        .with_state(context.clone())
}
