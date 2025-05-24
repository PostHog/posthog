use axum::{
    http::{Method, StatusCode},
    routing::{get, post},
    Router,
};
use std::future::ready;

use common_metrics::{setup_metrics_recorder, track_metrics};
use tower_http::{
    cors::{AllowHeaders, AllowOrigin, CorsLayer},
    trace::TraceLayer,
};

use crate::api::endpoints::{external_redirect_url, external_store_url, internal_redirect_url};
use crate::state::State;

pub fn router(state: State) -> Router {
    let enable_metrics = state.enable_metrics;

    // Very permissive CORS policy, as old SDK versions
    // and reverse proxies might send funky headers.
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true)
        .allow_origin(AllowOrigin::mirror_request());

    let liveness = state.liveness.clone();
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
