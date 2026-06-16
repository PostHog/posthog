use axum::Router;

use super::constants::{CAPTURE_V1_PATH, CAPTURE_V1_PATH_TRAILING};
use crate::router::State;

/// Route declarations only. The shared v1 middleware stack (headers, metrics,
/// timeout, CORS, limits) is owned by `crate::v1::router`.
pub fn routes() -> Router<State> {
    Router::new()
        .route(
            CAPTURE_V1_PATH,
            axum::routing::post(super::handler::handle_request),
        )
        .route(
            CAPTURE_V1_PATH_TRAILING,
            axum::routing::post(super::handler::handle_request),
        )
}
