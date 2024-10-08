use std::{future::ready, sync::Arc};

use axum::{
    routing::{get, post},
    Router,
};
use common_metrics::setup_metrics_recorder;
use health::HealthRegistry;
use tower::limit::ConcurrencyLimitLayer;

use crate::{
    database::Client as DatabaseClient, geoip::GeoIpClient, redis::Client as RedisClient,
    v0_endpoint,
};

#[derive(Clone)]
pub struct State {
    pub redis: Arc<dyn RedisClient + Send + Sync>,
    pub postgres_reader: Arc<dyn DatabaseClient + Send + Sync>,
    pub postgres_writer: Arc<dyn DatabaseClient + Send + Sync>,
    pub geoip: Arc<GeoIpClient>,
}

pub fn router<R, D>(
    redis: Arc<R>,
    postgres_reader: Arc<D>,
    postgres_writer: Arc<D>,
    geoip: Arc<GeoIpClient>,
    liveness: HealthRegistry,
    metrics: bool,
    concurrency: usize,
) -> Router
where
    R: RedisClient + Send + Sync + 'static,
    D: DatabaseClient + Send + Sync + 'static,
{
    let state = State {
        redis,
        postgres_reader,
        postgres_writer,
        geoip,
    };

    let status_router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())));

    let flags_router = Router::new()
        .route("/flags", post(v0_endpoint::flags).get(v0_endpoint::flags))
        .layer(ConcurrencyLimitLayer::new(concurrency))
        .with_state(state);

    let router = Router::new().merge(status_router).merge(flags_router);

    // Don't install metrics unless asked to
    // Global metrics recorders can play poorly with e.g. tests
    if metrics {
        let recorder_handle = setup_metrics_recorder();
        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    }
}

pub async fn index() -> &'static str {
    "feature flags service"
}
