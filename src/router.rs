use std::sync::Arc;

use axum::{routing::post, Router};
use tower_http::trace::TraceLayer;

use crate::{capture, sink, time::TimeSource};

#[derive(Clone)]
pub struct State {
    pub sink: Arc<dyn sink::EventSink + Send + Sync>,
    pub timesource: Arc<dyn TimeSource + Send + Sync>,
}

pub fn router<
    TZ: TimeSource + Send + Sync + 'static,
    S: sink::EventSink + Send + Sync + 'static,
>(
    timesource: TZ,
    sink: S,
) -> Router {
    let state = State {
        sink: Arc::new(sink),
        timesource: Arc::new(timesource),
    };

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
        .with_state(state)
}
