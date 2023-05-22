use crate::capture;
use axum::{routing::post, Router};
use tower_http::trace::TraceLayer;

pub fn router() -> Router {
    Router::new()
        // TODO: use NormalizePathLayer::trim_trailing_slash
        .route("/capture", post(capture::event))
        .route("/capture/", post(capture::event))
        .route("/batch", post(capture::event))
        .route("/batch/", post(capture::event))
        .route("/e", post(capture::event))
        .route("/e/", post(capture::event))
        .route("/engage", post(capture::event))
        .route("/engage/", post(capture::event))
        .layer(TraceLayer::new_for_http())
}
