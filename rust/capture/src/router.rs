use std::future::ready;
use std::sync::Arc;

use axum::http::Method;
use axum::{
    routing::{get, post},
    Router,
};
use health::HealthRegistry;
use tower_http::cors::{AllowHeaders, AllowOrigin, CorsLayer};
use tower_http::trace::TraceLayer;

use crate::{
    limiters::billing::BillingLimiter, redis::Client, sinks, time::TimeSource, v0_endpoint,
};

use crate::prometheus::{setup_metrics_recorder, track_metrics};

#[derive(Clone)]
pub struct State {
    pub sink: Arc<dyn sinks::Event + Send + Sync>,
    pub timesource: Arc<dyn TimeSource + Send + Sync>,
    pub redis: Arc<dyn Client + Send + Sync>,
    pub billing: BillingLimiter,
}

async fn index() -> &'static str {
    "capture"
}

pub fn router<
    TZ: TimeSource + Send + Sync + 'static,
    S: sinks::Event + Send + Sync + 'static,
    R: Client + Send + Sync + 'static,
>(
    timesource: TZ,
    liveness: HealthRegistry,
    sink: S,
    redis: Arc<R>,
    billing: BillingLimiter,
    metrics: bool,
) -> Router {
    let state = State {
        sink: Arc::new(sink),
        timesource: Arc::new(timesource),
        redis,
        billing,
    };

    // Very permissive CORS policy, as old SDK versions
    // and reverse proxies might send funky headers.
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true)
        .allow_origin(AllowOrigin::mirror_request());

    let router = Router::new()
        // TODO: use NormalizePathLayer::trim_trailing_slash
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())))
        .route(
            "/e",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .route(
            "/e/",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .route(
            "/batch",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .route(
            "/batch/",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .route(
            "/i/v0/e",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .route(
            "/i/v0/e/",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .layer(TraceLayer::new_for_http())
        .layer(cors)
        .layer(axum::middleware::from_fn(track_metrics))
        .with_state(state);

    // Don't install metrics unless asked to
    // Installing a global recorder when capture is used as a library (during tests etc)
    // does not work well.
    if metrics {
        let recorder_handle = setup_metrics_recorder();
        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    }
}
