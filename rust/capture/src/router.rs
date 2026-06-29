use std::future::ready;
use std::sync::Arc;
use std::time::Duration;

use axum::extract::DefaultBodyLimit;
use axum::http::Method;
use axum::{
    routing::{get, post},
    Router,
};
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use lifecycle::{LivenessHandler, ReadinessHandler};
use tower::limit::ConcurrencyLimitLayer;
use tower_http::cors::{AllowHeaders, AllowOrigin, CorsLayer};
use tower_http::trace::TraceLayer;

use crate::ai_s3::BlobStorage;
use crate::event_restrictions::EventRestrictionService;
use crate::global_rate_limiter::GlobalRateLimiter;
use crate::otel;
use crate::test_endpoint;
use crate::v0_request::DataType;
use crate::{ai_endpoint, sinks, time::TimeSource, v0_endpoint};
use common_redis::Client;
use limiters::overflow::OverflowLimiter;
use limiters::redis::RedisLimiter;
use limiters::token_dropper::TokenDropper;

use crate::config::CaptureMode;
use crate::metrics_middleware::track_metrics;
use crate::prometheus::setup_metrics_recorder;
use crate::quota_limiters::CaptureQuotaLimiter;

const EVENT_BODY_SIZE: usize = 2 * 1024 * 1024; // 2MB
pub const BATCH_BODY_SIZE: usize = 20 * 1024 * 1024; // 20MB, up from the default 2MB used for normal event payloads
const RECORDING_BODY_SIZE: usize = 25 * 1024 * 1024; // 25MB, up from the default 2MB used for normal event payloads

#[derive(Clone)]
pub struct State {
    pub sink: Arc<dyn sinks::Event + Send + Sync>,
    pub timesource: Arc<dyn TimeSource + Send + Sync>,
    pub redis: Arc<dyn Client + Send + Sync>,
    pub global_rate_limiter_token_distinctid: Option<Arc<GlobalRateLimiter>>,
    pub quota_limiter: Arc<CaptureQuotaLimiter>,
    pub token_dropper: Arc<TokenDropper>,
    /// Restriction service scoped to all pipelines this capture deployment
    /// produces to (e.g. `[Analytics, ErrorTracking]` for the events
    /// deployment). Callers select the pipeline per event when looking up
    /// restrictions — see `events::analytics::process_events`.
    pub event_restriction_service: Option<EventRestrictionService>,
    pub event_payload_size_limit: usize,
    pub historical_cfg: HistoricalConfig,
    pub is_mirror_deploy: bool,
    pub verbose_sample_percent: f32,
    pub ai_max_sum_of_parts_bytes: usize,
    pub ai_blob_storage: Option<Arc<dyn BlobStorage>>,
    pub body_chunk_read_timeout: Option<Duration>,
    pub body_read_chunk_size_kb: usize,
    pub capture_v1_max_compressed_body_bytes: usize,
    pub capture_v1_max_decompressed_body_bytes: usize,
    /// In-process overflow limiter (governor-backed) for `DataType::AnalyticsMain`
    /// events. When present, every handler that emits analytics events runs
    /// the shared `events::overflow_stamping::stamp_overflow_reason` helper,
    /// which calls `is_limited` per event and stamps
    /// `ProcessedEventMetadata::overflow_reason` with `ForceLimited` or
    /// `RateLimited { .. }` so the kafka sink can route to the overflow topic.
    /// Call sites that consult this limiter:
    /// * `events::analytics::process_events` (analytics batch path)
    /// * `ai_endpoint::ai_handler` (`/i/v0/ai`)
    /// * `otel::otel_handler` (`/i/v0/ai/otel`)
    ///
    /// This lives in `State` (not in the sink) so routing policy sits in the
    /// pipeline alongside every other routing decision, and so the sink stays
    /// a pure mechanism layer with cheap Arc-based clones.
    pub overflow_limiter: Option<Arc<OverflowLimiter>>,
    /// Redis-backed replay overflow limiter for session recording sessions.
    /// When present, the recordings pipeline calls `is_limited(session_id)`
    /// and stamps `ProcessedEventMetadata::overflow_reason = ReplayLimited` so
    /// the kafka sink can route to the replay overflow topic. Same rationale
    /// as `overflow_limiter` above.
    pub replay_overflow_limiter: Option<Arc<RedisLimiter>>,
    /// V1 sink router for the new capture analytics pipeline.
    /// When present, the v1 analytics handler publishes events through this.
    pub v1_sink_router: Option<Arc<crate::v1::sinks::Router>>,
    pub capture_v1_scatter_gather_min_batch: usize,
    pub ai_gateway_signing_secret: Option<String>,
}

#[derive(Clone, Copy)]
pub struct HistoricalConfig {
    pub enable_historical_rerouting: bool,
    pub historical_rerouting_threshold_days: i64,
}

impl HistoricalConfig {
    pub fn new(
        enable_historical_rerouting: bool,
        historical_rerouting_threshold_days: i64,
    ) -> Self {
        HistoricalConfig {
            enable_historical_rerouting,
            historical_rerouting_threshold_days,
        }
    }

    pub fn should_reroute(&self, data_type: DataType, timestamp: DateTime<Utc>) -> bool {
        if !self.enable_historical_rerouting {
            return false;
        }

        if data_type != DataType::AnalyticsMain {
            return false;
        }

        let days_stale = ChronoDuration::days(self.historical_rerouting_threshold_days);
        let threshold = Utc::now() - days_stale;
        timestamp <= threshold
    }
}

async fn index() -> &'static str {
    "capture"
}

#[allow(clippy::too_many_arguments)]
pub fn router<TZ: TimeSource + Send + Sync + 'static, R: Client + Send + Sync + 'static>(
    timesource: TZ,
    readiness: ReadinessHandler,
    liveness: LivenessHandler,
    sink: Arc<dyn sinks::Event + Send + Sync>,
    redis: Arc<R>,
    global_rate_limiter_token_distinctid: Option<Arc<GlobalRateLimiter>>,
    quota_limiter: CaptureQuotaLimiter,
    token_dropper: TokenDropper,
    event_restriction_service: Option<EventRestrictionService>,
    metrics: bool,
    capture_mode: CaptureMode,
    deploy_role: String,
    concurrency_limit: Option<usize>,
    event_payload_size_limit: usize,
    enable_historical_rerouting: bool,
    historical_rerouting_threshold_days: i64,
    is_mirror_deploy: bool,
    verbose_sample_percent: f32,
    ai_max_sum_of_parts_bytes: usize,
    ai_blob_storage: Option<Arc<dyn BlobStorage>>,
    body_chunk_read_timeout_ms: Option<u64>,
    body_read_chunk_size_kb: usize,
    capture_v1_max_compressed_body_bytes: usize,
    capture_v1_max_decompressed_body_bytes: usize,
    overflow_limiter: Option<Arc<OverflowLimiter>>,
    replay_overflow_limiter: Option<Arc<RedisLimiter>>,
    v1_sink_router: Option<Arc<crate::v1::sinks::Router>>,
    capture_v1_scatter_gather_min_batch: usize,
    ai_gateway_signing_secret: Option<String>,
) -> Router {
    let state = State {
        sink,
        timesource: Arc::new(timesource),
        redis,
        global_rate_limiter_token_distinctid,
        quota_limiter: Arc::new(quota_limiter),
        event_payload_size_limit,
        token_dropper: Arc::new(token_dropper),
        event_restriction_service,
        historical_cfg: HistoricalConfig::new(
            enable_historical_rerouting,
            historical_rerouting_threshold_days,
        ),
        is_mirror_deploy,
        verbose_sample_percent,
        ai_max_sum_of_parts_bytes,
        ai_blob_storage,
        body_chunk_read_timeout: body_chunk_read_timeout_ms.map(Duration::from_millis),
        body_read_chunk_size_kb,
        capture_v1_max_compressed_body_bytes,
        capture_v1_max_decompressed_body_bytes,
        overflow_limiter,
        replay_overflow_limiter,
        v1_sink_router,
        capture_v1_scatter_gather_min_batch,
        ai_gateway_signing_secret,
    };

    // Very permissive CORS policy, as old SDK versions
    // and reverse proxies might send funky headers.
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true)
        .allow_origin(AllowOrigin::mirror_request());

    let test_router = Router::new()
        .route(
            "/test/black_hole",
            post(test_endpoint::test_black_hole)
                .get(test_endpoint::test_black_hole)
                .options(v0_endpoint::options),
        )
        .route(
            "/test/black_hole/",
            post(test_endpoint::test_black_hole)
                .get(test_endpoint::test_black_hole)
                .options(v0_endpoint::options),
        )
        .layer(DefaultBodyLimit::max(BATCH_BODY_SIZE));

    let batch_router = Router::new()
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
        .layer(DefaultBodyLimit::max(BATCH_BODY_SIZE)); // Have to use this, rather than RequestBodyLimitLayer, because we use `Bytes` in the handler (this limit applies specifically to Bytes body types)

    let event_router = Router::new()
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
            "/track",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .route(
            "/track/",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .route(
            "/engage",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .route(
            "/engage/",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .route(
            "/capture",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .route(
            "/capture/",
            post(v0_endpoint::event)
                .get(v0_endpoint::event)
                .options(v0_endpoint::options),
        )
        .layer(DefaultBodyLimit::max(EVENT_BODY_SIZE));

    let status_router = Router::new()
        .route("/", get(index))
        .route(
            "/_readiness",
            get(move || {
                let r = readiness.clone();
                async move { r.check().await }
            }),
        )
        .route(
            "/_liveness",
            get(move || {
                let l = liveness.clone();
                async move { l.check() }
            }),
        );

    let recordings_router = Router::new()
        .route(
            "/s",
            post(v0_endpoint::recording)
                .get(v0_endpoint::recording)
                .options(v0_endpoint::options),
        )
        .route(
            "/s/",
            post(v0_endpoint::recording)
                .get(v0_endpoint::recording)
                .options(v0_endpoint::options),
        )
        .layer(DefaultBodyLimit::max(RECORDING_BODY_SIZE));

    // AI endpoint body limit is 110% of max sum of parts to account for multipart overhead
    let ai_body_limit = (state.ai_max_sum_of_parts_bytes as f64 * 1.1) as usize;

    let ai_router = Router::new()
        .route(
            "/i/v0/ai",
            post(ai_endpoint::ai_handler).options(ai_endpoint::options),
        )
        .route(
            "/i/v0/ai/",
            post(ai_endpoint::ai_handler).options(ai_endpoint::options),
        )
        .layer(DefaultBodyLimit::max(ai_body_limit));

    let otel_router = Router::new()
        .route(
            "/i/v0/ai/otel",
            post(otel::otel_handler).options(otel::options),
        )
        .route(
            "/i/v0/ai/otel/",
            post(otel::otel_handler).options(otel::options),
        )
        .layer(DefaultBodyLimit::max(otel::OTEL_BODY_SIZE));

    let mut router = match capture_mode {
        CaptureMode::Events | CaptureMode::Ai => Router::new()
            .merge(batch_router)
            .merge(event_router)
            .merge(test_router)
            .merge(ai_router)
            .merge(otel_router),
        CaptureMode::Recordings => Router::new().merge(recordings_router),
    };

    if let Some(limit) = concurrency_limit {
        router = router.layer(ConcurrencyLimitLayer::new(limit));
    }

    // keep healthchecks outside the concurrency limit so they stay responsive under load
    router = router.merge(status_router);

    // Legacy CORS is applied before the v1 router is merged so it stays
    // scoped to v0/status routes; v1 ships its own policy.
    router = router.layer(cors);

    // The v1 analytics endpoint is only routable when a v1 sink is
    // configured. Without a sink the handler can't publish, so we keep
    // the path unregistered (404) rather than advertising an endpoint
    // that can only ever return 503. This also isolates the route to
    // deployments that opt in via CAPTURE_V1_SINKS.
    //
    // Merged after every legacy layer above: the v1 router owns its full
    // middleware stack (CORS, limits) and applies the same per-route
    // concurrency cap to its own routes.
    if matches!(capture_mode, CaptureMode::Events | CaptureMode::Ai)
        && state.v1_sink_router.is_some()
    {
        router = router.merge(crate::v1::router::router(crate::v1::router::RouterConfig {
            concurrency_limit,
            max_compressed_body_bytes: state.capture_v1_max_compressed_body_bytes,
        }));
    }

    let router = router
        .layer(TraceLayer::new_for_http())
        .layer(axum::middleware::from_fn(track_metrics))
        .with_state(state);

    // Don't install metrics unless asked to
    // Installing a global recorder when capture is used as a library (during tests etc)
    // does not work well.
    if metrics {
        let recorder_handle = setup_metrics_recorder(deploy_role, capture_mode.as_tag());
        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration as StdDuration;

    #[tokio::test]
    async fn test_body_chunk_timeout_fires_on_stalled_upload() {
        use crate::extractors::extract_body_with_timeout;
        use axum::body::Body;
        use bytes::Bytes;
        use futures::{stream, StreamExt};

        // Create a stream that yields one chunk then stalls
        let chunks: Vec<Result<Bytes, std::io::Error>> = vec![Ok(Bytes::from("partial data"))];
        let slow_stream = stream::iter(chunks).chain(stream::pending());
        let body = Body::from_stream(slow_stream);

        // Use a short chunk timeout
        let timeout = Some(StdDuration::from_millis(100));
        let result = extract_body_with_timeout(body, 1024 * 1024, timeout, 256, "/test").await;

        // Should get a BodyReadTimeout error
        assert!(matches!(
            result,
            Err(crate::api::CaptureError::BodyReadTimeout)
        ));
    }

    #[tokio::test]
    async fn test_body_chunk_timeout_disabled_when_none() {
        use crate::extractors::extract_body_with_timeout;
        use axum::body::Body;

        // Normal body with no timeout
        let body = Body::from(r#"{"event": "test"}"#);
        let result = extract_body_with_timeout(body, 1024 * 1024, None, 256, "/test").await;

        assert!(result.is_ok());
        assert_eq!(result.unwrap(), r#"{"event": "test"}"#.as_bytes());
    }
}
