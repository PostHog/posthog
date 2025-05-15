use axum::{
    routing::{get, post},
    Router,
};
use health::HealthRegistry;
use std::{future::ready, sync::Arc};

use common_database::Client as DatabaseClient;
use common_metrics::{setup_metrics_recorder, track_metrics};
use common_redis::Client as RedisClient;
use tower_http::trace::TraceLayer;

use crate::api::endpoints::{external_redirect_url, external_store_url, internal_redirect_url};

#[derive(Clone)]
pub struct AppState {
    pub db_reader_client: Arc<dyn DatabaseClient + Send + Sync>,
    pub external_redis_client: Arc<dyn RedisClient + Send + Sync>,
    pub internal_redis_client: Arc<dyn RedisClient + Send + Sync>,
}

pub fn router<D, R>(
    db_reader_client: Arc<D>,
    external_redis_client: Arc<R>,
    internal_redis_client: Arc<R>,
    liveness: HealthRegistry,
) -> Router
where
    D: DatabaseClient + Send + Sync + 'static,
    R: RedisClient + Send + Sync + 'static,
{
    let state = AppState {
        db_reader_client,
        external_redis_client,
        internal_redis_client,
    };

    let status_router =
        Router::new().route("/_liveness", get(move || ready(liveness.get_status())));

    let links_public_router = Router::new()
        .route("/ph/:origin_key", get(external_redirect_url))
        .route("/ph/:origin_key/", get(external_redirect_url))
        .route("/ph", post(external_store_url))
        .route("/ph/", post(external_store_url));

    let links_private_router = Router::new()
        .route("/:origin_key", get(internal_redirect_url))
        .route("/:origin_key/", get(internal_redirect_url));

    let router = Router::new()
        .merge(status_router)
        .merge(links_public_router)
        .merge(links_private_router)
        .layer(TraceLayer::new_for_http())
        .layer(axum::middleware::from_fn(track_metrics))
        .with_state(state);

    let recorder_handle = setup_metrics_recorder();
    router.route("/metrics", get(move || ready(recorder_handle.render())))
}
