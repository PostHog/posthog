//! HTTP router, shared [`AppState`], and K8s probes (plan §2.2).
//!
//! There is deliberately **no compression layer** anywhere on this service —
//! compression middleware is the classic silent SSE killer. CORS is permissive
//! and GET-only because `remote_eval` streams are opened by browser `EventSource`.

use std::sync::Arc;

use axum::http::Method;
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use axum_client_ip::SecureClientIpSource;
use common_metrics::setup_metrics_routes_for_product;
use lifecycle::{LivenessHandler, ReadinessHandler};
use tokio_util::sync::CancellationToken;
use tower_http::cors::{AllowHeaders, AllowOrigin, CorsLayer};
use tower_http::trace::TraceLayer;

use crate::api::stream;
use crate::auth::Authenticator;
use crate::config::RuntimeConfig;
use crate::registry::TopicRegistry;

/// Shared handler state. Every field is `Arc`/token-cheap so the derive-`Clone`
/// that axum requires is a handful of refcount bumps per request.
#[derive(Clone)]
pub struct AppState {
    pub config: Arc<RuntimeConfig>,
    pub registry: Arc<TopicRegistry>,
    pub authenticator: Arc<Authenticator>,
    /// The pod shutdown token, `select!`-ed inside every stream so a drain closes
    /// open streams promptly instead of hanging to max-age (plan §2.11).
    pub shutdown_token: CancellationToken,
}

/// Build the gateway router. `enable_metrics` gates installing the global
/// Prometheus recorder + `/metrics` route (off in tests so the process-global
/// recorder is not clobbered — feature-flags precedent).
pub fn router(
    state: AppState,
    readiness: ReadinessHandler,
    liveness: LivenessHandler,
    ip_source: SecureClientIpSource,
    enable_metrics: bool,
) -> Router {
    // GET-only permissive CORS: browser EventSource connects cross-origin.
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::OPTIONS, Method::HEAD])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_origin(AllowOrigin::mirror_request());

    let app = Router::new()
        .route("/stream/v1", get(stream::stream_v1))
        .route(
            "/_readiness",
            get(move || {
                let readiness = readiness.clone();
                async move { readiness.check().await }
            }),
        )
        .route(
            "/_liveness",
            get(move || {
                let liveness = liveness.clone();
                async move { liveness.check().into_response() }
            }),
        )
        .route("/", get(index))
        // The IP source extension backs the `SecureClientIp` extractor used by
        // the definitions per-IP limiter (plan §2.5).
        .layer(ip_source.into_extension())
        .layer(cors)
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    if enable_metrics {
        setup_metrics_routes_for_product(app, "feature_flags")
    } else {
        app
    }
}

async fn index() -> &'static str {
    "flags-stream-gateway: realtime feature-flags streaming gateway\n"
}
