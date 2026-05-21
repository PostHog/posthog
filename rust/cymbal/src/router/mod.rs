mod event;

use axum::routing::{get, post};
use axum::{extract::State, response::IntoResponse, Router};

pub use event::*;

use health::HealthStatus;
use reqwest::StatusCode;
use std::future::ready;
use std::sync::atomic::Ordering;
use std::sync::Arc;

use crate::app_context::AppContext;

async fn index() -> &'static str {
    "error tracking service"
}

async fn liveness(State(ctx): State<Arc<AppContext>>) -> HealthStatus {
    ready(ctx.health_registry.get_status()).await
}

async fn readiness(State(ctx): State<Arc<AppContext>>) -> impl IntoResponse {
    if ctx.cache_warmed.load(Ordering::Relaxed) {
        (StatusCode::OK, "ready")
    } else {
        (StatusCode::SERVICE_UNAVAILABLE, "warming cache")
    }
}

async fn not_found() -> impl IntoResponse {
    (StatusCode::NOT_FOUND, "Not Found")
}

pub fn get_router(context: Arc<AppContext>) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/process", post(process_events))
        .route("/_readiness", get(readiness))
        .route("/_liveness", get(liveness))
        .fallback(not_found)
        .with_state(context.clone())
}
