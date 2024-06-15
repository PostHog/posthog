use axum::{routing::get, Router};
use health::HealthRegistry;
use std::future::ready;

pub fn app(liveness: HealthRegistry) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())))
}

pub async fn index() -> &'static str {
    "rusty-hook janitor"
}
