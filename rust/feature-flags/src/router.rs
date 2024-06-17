use std::sync::Arc;

use axum::{routing::post, Router};

use crate::{redis::Client as RedisClient, v0_endpoint, database::Client as DatabaseClient};

#[derive(Clone)]
pub struct State {
    pub redis: Arc<dyn RedisClient + Send + Sync>,
    // TODO: Add pgClient when ready
    pub postgres: Arc<dyn DatabaseClient + Send + Sync>,
}

pub fn router<R, D>(redis: Arc<R>, postgres: Arc<D>) -> Router
where
    R: RedisClient + Send + Sync + 'static,
    D: DatabaseClient + Send + Sync + 'static,
{
    let state = State { redis, postgres };

    Router::new()
        .route("/flags", post(v0_endpoint::flags).get(v0_endpoint::flags))
        .with_state(state)
}
