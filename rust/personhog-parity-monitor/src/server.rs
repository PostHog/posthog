use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use common_metrics::setup_metrics_routes;
use health::HealthRegistry;

use crate::join::SampleRing;

const DEBUG_API_SECRET_HEADER: &str = "x-debug-api-secret";

/// The mismatch ring carries distinct ids, so it answers only with the shared secret.
pub fn router(
    health: HealthRegistry,
    samples: SampleRing,
    debug_api_secret: Option<String>,
) -> Router {
    let readiness = health.clone();
    let router = Router::new()
        .route(
            "/_readiness",
            get(move || {
                let health = readiness.clone();
                async move { health.get_status() }
            }),
        )
        .route(
            "/_liveness",
            get(move || {
                let health = health.clone();
                async move { health.get_status() }
            }),
        )
        .route(
            "/debug/mismatches",
            get(move |headers: HeaderMap| {
                let samples = samples.clone();
                let secret = debug_api_secret.clone();
                async move { mismatches(&headers, secret.as_deref(), &samples) }
            }),
        );
    setup_metrics_routes(router)
}

fn mismatches(headers: &HeaderMap, secret: Option<&str>, samples: &SampleRing) -> Response {
    let Some(secret) = secret else {
        return StatusCode::NOT_FOUND.into_response();
    };
    let presented = headers
        .get(DEBUG_API_SECRET_HEADER)
        .and_then(|value| value.to_str().ok());
    if presented != Some(secret) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    Json(samples.snapshot()).into_response()
}
