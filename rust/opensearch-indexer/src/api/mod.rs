use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::{routing::get, Router};
use health::HealthRegistry;

pub fn root_router(liveness: HealthRegistry) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/_readiness", get(readiness))
        .route(
            "/_liveness",
            get(move || {
                let liveness = liveness.clone();
                async move { liveness.get_status() }
            }),
        )
}

async fn index() -> &'static str {
    "opensearch-indexer"
}

async fn readiness() -> impl IntoResponse {
    StatusCode::OK
}
