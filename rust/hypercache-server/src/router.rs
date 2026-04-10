use std::{future::ready, sync::Arc};

use axum::{
    http::{Method, StatusCode},
    routing::{any, get},
    Router,
};
use common_hypercache::HyperCacheReader;
use common_metrics::{setup_metrics_recorder, track_metrics};
use health::readiness_handler;
use tower::limit::ConcurrencyLimitLayer;
use tower_http::{
    cors::{AllowHeaders, AllowOrigin, CorsLayer},
    trace::TraceLayer,
};

use crate::{
    api::{remote_config, surveys},
    config::Config,
};

#[derive(Clone)]
pub struct State {
    pub surveys_hypercache_reader: Arc<HyperCacheReader>,
    pub config_hypercache_reader: Arc<HyperCacheReader>,
}

pub fn router(
    surveys_hypercache_reader: Arc<HyperCacheReader>,
    config_hypercache_reader: Arc<HyperCacheReader>,
    config: Config,
) -> Router {
    let state = State {
        surveys_hypercache_reader,
        config_hypercache_reader,
    };

    // Permissive CORS policy matching the feature-flags service
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS, Method::HEAD])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true)
        .allow_origin(AllowOrigin::mirror_request());

    // Liveness: always healthy — this service has no background loops to monitor.
    // If axum is serving requests, the process is alive.
    let status_router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(readiness_handler))
        .route("/_liveness", get(|| ready("OK")));

    let app_router = Router::new()
        // Surveys endpoints
        .route("/surveys", any(surveys::surveys_endpoint))
        .route("/surveys/", any(surveys::surveys_endpoint))
        .route("/api/surveys", any(surveys::surveys_endpoint))
        .route("/api/surveys/", any(surveys::surveys_endpoint))
        // Remote config endpoints
        .route("/array/:token/config", any(remote_config::config_endpoint))
        .route(
            "/array/:token/config.js",
            any(remote_config::config_js_endpoint),
        )
        // Explicit 404 for sourcemap requests to avoid high-cardinality unmatched paths in metrics
        .route(
            "/array/:token/config.js.map",
            any(|| ready(StatusCode::NOT_FOUND)),
        )
        .layer(ConcurrencyLimitLayer::new(config.max_concurrency));

    let router = Router::new()
        .merge(status_router)
        .merge(app_router)
        .layer(TraceLayer::new_for_http())
        .layer(cors)
        .layer(axum::middleware::from_fn(track_metrics))
        .with_state(state);

    if *config.enable_metrics {
        let recorder_handle = setup_metrics_recorder();
        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    }
}

pub async fn index() -> &'static str {
    "hypercache-server"
}
