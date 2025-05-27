use axum::{
    http::{Method, StatusCode},
    routing::{get, post},
    Router,
};
use health::HealthRegistry;
use std::{future::ready, sync::Arc};

use common_database::Client as DatabaseClient;
use common_metrics::{setup_metrics_recorder, track_metrics};
use common_redis::Client as RedisClient;
use tower_http::{
    cors::{AllowHeaders, AllowOrigin, CorsLayer},
    trace::TraceLayer,
};

use crate::api::endpoints::{external_redirect_url, external_store_url, internal_redirect_url};

#[derive(Clone)]
pub struct AppState {
    pub db_reader_client: Arc<dyn DatabaseClient + Send + Sync>,
    pub external_redis_client: Arc<dyn RedisClient + Send + Sync>,
    pub internal_redis_client: Arc<dyn RedisClient + Send + Sync>,
    pub default_domain_for_public_store: String,
}

pub fn router<D, R>(
    db_reader_client: Arc<D>,
    external_redis_client: Arc<R>,
    internal_redis_client: Arc<R>,
    default_domain_for_public_store: String,
    liveness: HealthRegistry,
    enable_metrics: bool,
) -> Router
where
    D: DatabaseClient + Send + Sync + 'static,
    R: RedisClient + Send + Sync + 'static,
{
    let state = AppState {
        db_reader_client,
        external_redis_client,
        internal_redis_client,
        default_domain_for_public_store,
    };

    // Very permissive CORS policy, as old SDK versions
    // and reverse proxies might send funky headers.
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true)
        .allow_origin(AllowOrigin::mirror_request());

    let status_router = Router::new()
        .route("/_readiness", get(|| ready(StatusCode::OK)))
        .route("/_liveness", get(move || ready(liveness.get_status())));

    let links_external_router = Router::new()
        .route("/ph/:short_code", get(external_redirect_url))
        .route("/ph/:short_code/", get(external_redirect_url))
        .route("/ph", post(external_store_url))
        .route("/ph/", post(external_store_url));

    let links_internal_router = Router::new()
        .route("/:short_code", get(internal_redirect_url))
        .route("/:short_code/", get(internal_redirect_url));

    let router = Router::new()
        .merge(status_router)
        .merge(links_external_router)
        .merge(links_internal_router)
        .layer(TraceLayer::new_for_http())
        .layer(axum::middleware::from_fn(track_metrics))
        .layer(cors)
        .with_state(state);

    if enable_metrics {
        let recorder_handle = setup_metrics_recorder();
        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    }
}
