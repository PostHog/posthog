use std::{future::ready, sync::Arc};

use axum::{
    http::Method,
    routing::{get, post},
    Router,
};
use common_metrics::{setup_metrics_recorder, track_metrics};
use health::HealthRegistry;
use tower::limit::ConcurrencyLimitLayer;
use tower_http::{
    cors::{AllowHeaders, AllowOrigin, CorsLayer},
    trace::TraceLayer,
};

use crate::{
    api::endpoint,
    client::{
        database::Client as DatabaseClient, geoip::GeoIpClient, redis::Client as RedisClient,
    },
    cohort::cohort_cache_manager::CohortCacheManager,
    config::{Config, TeamIdsToTrack},
    metrics::metrics_utils::team_id_label_filter,
};

#[derive(Clone)]
pub struct State {
    pub redis: Arc<dyn RedisClient + Send + Sync>,
    pub reader: Arc<dyn DatabaseClient + Send + Sync>,
    pub writer: Arc<dyn DatabaseClient + Send + Sync>,
    pub cohort_cache_manager: Arc<CohortCacheManager>,
    pub geoip: Arc<GeoIpClient>,
    pub team_ids_to_track: TeamIdsToTrack,
}

pub fn router<R, D>(
    redis: Arc<R>,
    reader: Arc<D>,
    writer: Arc<D>,
    cohort_cache: Arc<CohortCacheManager>,
    geoip: Arc<GeoIpClient>,
    liveness: HealthRegistry,
    config: Config,
) -> Router
where
    R: RedisClient + Send + Sync + 'static,
    D: DatabaseClient + Send + Sync + 'static,
{
    let state = State {
        redis,
        reader,
        writer,
        cohort_cache_manager: cohort_cache,
        geoip,
        team_ids_to_track: config.team_ids_to_track.clone(),
    };

    // Very permissive CORS policy, as old SDK versions
    // and reverse proxies might send funky headers.
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true)
        .allow_origin(AllowOrigin::mirror_request());

    let status_router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())));

    let flags_router = Router::new()
        .route("/flags", post(endpoint::flags).get(endpoint::flags))
        .route("/flags/", post(endpoint::flags).get(endpoint::flags))
        .layer(ConcurrencyLimitLayer::new(config.max_concurrency));

    let router = Router::new()
        .merge(status_router)
        .merge(flags_router)
        .layer(TraceLayer::new_for_http())
        .layer(cors)
        .layer(axum::middleware::from_fn(track_metrics))
        .with_state(state);

    // Don't install metrics unless asked to
    // Global metrics recorders can play poorly with e.g. tests
    if config.enable_metrics {
        common_metrics::set_label_filter(team_id_label_filter(config.team_ids_to_track.clone()));
        let recorder_handle = setup_metrics_recorder();
        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    }
}

pub async fn index() -> &'static str {
    "feature flags"
}
