use std::sync::Arc;

use axum::{routing::post, Router};

use crate::{redis::Client, v0_endpoint};

#[derive(Clone)]
pub struct State {
    pub redis: Arc<dyn Client + Send + Sync>,
    // TODO: Add pgClient when ready
}

pub fn router<R: Client + Send + Sync + 'static>(redis: Arc<R>) -> Router {
    let state = State { redis };

    Router::new()
        .route("/flags", post(v0_endpoint::flags).get(v0_endpoint::flags))
        .with_state(state)
}
