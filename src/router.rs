use crate::capture;
use axum::{routing::post, Router};
use tower_http::trace::TraceLayer;

pub fn router() -> Router {
    Router::new()
        .route("/capture", post(capture::event))
        .route("/batch", post(capture::batch))
        .layer(TraceLayer::new_for_http())
}
