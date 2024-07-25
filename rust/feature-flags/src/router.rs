use std::sync::Arc;

use axum::{routing::post, Router};

use crate::{database::Client as DatabaseClient, redis::Client as RedisClient, v0_endpoint};

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

// TODO, eventually we can differentiate read and write postgres clients, if needed
// I _think_ everything is read-only, but I'm not 100% sure yet
// here's how that client would look
// use std::sync::Arc;

// use axum::{routing::post, Router};

// use crate::{database::Client as DatabaseClient, redis::Client as RedisClient, v0_endpoint};

// #[derive(Clone)]
// pub struct State {
//     pub redis: Arc<dyn RedisClient + Send + Sync>,
//     pub postgres_read: Arc<dyn DatabaseClient + Send + Sync>,
//     pub postgres_write: Arc<dyn DatabaseClient + Send + Sync>,
// }

// pub fn router<R, D>(
//     redis: Arc<R>,
//     postgres_read: Arc<D>,
//     postgres_write: Arc<D>,
// ) -> Router
// where
//     R: RedisClient + Send + Sync + 'static,
//     D: DatabaseClient + Send + Sync + 'static,
// {
//     let state = State {
//         redis,
//         postgres_read,
//         postgres_write,
//     };

//     Router::new()
//         .route("/flags", post(v0_endpoint::flags).get(v0_endpoint::flags))
//         .with_state(state)
// }
