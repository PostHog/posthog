use std::future::ready;
use std::sync::Arc;

use axum::extract::DefaultBodyLimit;
use axum::http::{Method, StatusCode};
use axum::{
    response::IntoResponse,
    routing::{get, post},
    Router,
};
use chrono::{DateTime, Duration, Utc};
use health::HealthRegistry;
use std::time::Duration as StdDuration;
use tower::limit::ConcurrencyLimitLayer;
use tower_http::cors::{AllowHeaders, AllowOrigin, CorsLayer};
use tower_http::trace::TraceLayer;

use crate::metrics_middleware::track_metrics;
use crate::test_endpoint;
use crate::v0_request::DataType;
use crate::{ai_endpoint, sinks, time::TimeSource, v0_endpoint};
use common_redis::Client;
use limiters::token_dropper::TokenDropper;

use crate::config::CaptureMode;
use crate::limiters::CaptureQuotaLimiter;
use crate::prometheus::setup_metrics_recorder;

const EVENT_BODY_SIZE: usize = 2 * 1024 * 1024; // 2MB
pub const BATCH_BODY_SIZE: usize = 20 * 1024 * 1024; // 20MB, up from the default 2MB used for normal event payloads
const RECORDING_BODY_SIZE: usize = 25 * 1024 * 1024; // 25MB, up from the default 2MB used for normal event payloads

#[derive(Clone)]
pub struct State {
    pub sink: Arc<dyn sinks::Event + Send + Sync>,
    pub timesource: Arc<dyn TimeSource + Send + Sync>,
    pub redis: Arc<dyn Client + Send + Sync>,
    pub quota_limiter: Arc<CaptureQuotaLimiter>,
    pub token_dropper: Arc<TokenDropper>,
    pub event_size_limit: usize,
    pub historical_cfg: HistoricalConfig,
    pub capture_mode: CaptureMode,
    pub is_mirror_deploy: bool,
    pub verbose_sample_percent: f32,
    pub ai_max_sum_of_parts_bytes: usize,
}

#[derive(Clone)]
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

        let days_stale = Duration::days(self.historical_rerouting_threshold_days);
        let threshold = Utc::now() - days_stale;
        timestamp <= threshold
    }
}

async fn index() -> &'static str {
    "capture"
}

pub fn apply_request_timeout_middleware<S>(
    router: Router<S>,
    request_timeout_seconds: Option<u64>,
) -> Router<S>
where
    S: Clone + Send + Sync + 'static,
{
    if let Some(request_timeout_seconds) = request_timeout_seconds {
        let timeout_duration = StdDuration::from_secs(request_timeout_seconds);

        return router.layer(axum::middleware::from_fn(
            move |req: axum::extract::Request, next: axum::middleware::Next| async move {
                match tokio::time::timeout(timeout_duration, next.run(req)).await {
                    Ok(response) => response,
                    Err(_) => (StatusCode::REQUEST_TIMEOUT, "Request timeout").into_response(),
                }
            },
        ));
    }

    // no timeout configured
    router
}

#[allow(clippy::too_many_arguments)]
pub fn router<
    TZ: TimeSource + Send + Sync + 'static,
    S: sinks::Event + Send + Sync + 'static,
    R: Client + Send + Sync + 'static,
>(
    timesource: TZ,
    liveness: HealthRegistry,
    sink: S,
    redis: Arc<R>,
    quota_limiter: CaptureQuotaLimiter,
    token_dropper: TokenDropper,
    metrics: bool,
    capture_mode: CaptureMode,
    concurrency_limit: Option<usize>,
    event_size_limit: usize,
    enable_historical_rerouting: bool,
    historical_rerouting_threshold_days: i64,
    is_mirror_deploy: bool,
    verbose_sample_percent: f32,
    ai_max_sum_of_parts_bytes: usize,
    request_timeout_seconds: Option<u64>,
) -> Router {
    let state = State {
        sink: Arc::new(sink),
        timesource: Arc::new(timesource),
        redis,
        quota_limiter: Arc::new(quota_limiter),
        event_size_limit,
        token_dropper: Arc::new(token_dropper),
        historical_cfg: HistoricalConfig::new(
            enable_historical_rerouting,
            historical_rerouting_threshold_days,
        ),
        capture_mode: capture_mode.clone(),
        is_mirror_deploy,
        verbose_sample_percent,
        ai_max_sum_of_parts_bytes,
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
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())));

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

    let mut router = match capture_mode {
        CaptureMode::Events => Router::new()
            .merge(batch_router)
            .merge(event_router)
            .merge(test_router)
            .merge(ai_router),
        CaptureMode::Recordings => Router::new().merge(recordings_router),
    };

    if let Some(limit) = concurrency_limit {
        router = router.layer(ConcurrencyLimitLayer::new(limit));
    }

    // add this prior to timeout middleware to ensure healthchecks are sensitive to load
    router = router.merge(status_router);

    // apply request timeout middleware if request_timeout_seconds is set
    router = apply_request_timeout_middleware(router, request_timeout_seconds);

    let router = router
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

#[cfg(test)]
mod tests {
    use super::*;

    use std::collections::HashMap;
    use std::time::Duration as StdDuration;

    use axum::http::StatusCode;
    use axum_test_helper::TestClient;
    use bytes::Bytes;
    use serde_json::json;

    async fn slow_handler() -> &'static str {
        // Sleep for 2 seconds to ensure timeout with 1 second timeout
        tokio::time::sleep(StdDuration::from_secs(2)).await;
        "slow response"
    }

    async fn fast_handler() -> &'static str {
        "fast response"
    }

    async fn indefinite_work_handler(body: Bytes) -> &'static str {
        loop {
            let _unused =
                serde_json::from_slice::<Vec<HashMap<String, String>>>(body.as_ref()).unwrap();
            tokio::task::yield_now().await;
        }

        #[allow(unreachable_code)]
        "done parsing large body"
    }

    #[tokio::test]
    async fn test_timeout_returns_408() {
        // Use a 1 second timeout - the slow handler sleeps for 2 seconds, so it should timeout
        // Create router with test route included before timeout middleware is applied
        let router = Router::new().route("/slow", get(slow_handler));
        let router = apply_request_timeout_middleware(router, Some(1));

        let client = TestClient::new(router);
        let response = client.get("/slow").send().await;

        assert_eq!(response.status(), StatusCode::REQUEST_TIMEOUT);
        let body = response.text().await;
        assert_eq!(body, "Request timeout");
    }

    #[tokio::test]
    async fn test_normal_request_completes_within_timeout() {
        // Use a longer timeout (1 second) so normal requests complete
        let router = Router::new().route("/fast", get(fast_handler));
        let router = apply_request_timeout_middleware(router, Some(1));

        let client = TestClient::new(router);
        let response = client.get("/fast").send().await;

        assert_eq!(response.status(), StatusCode::OK);
        let body = response.text().await;
        assert_eq!(body, "fast response");
    }

    #[tokio::test]
    async fn test_timeout_configuration_works() {
        // Test with 1 second timeout - should timeout on slow handler (which sleeps 2 seconds)
        let router = Router::new().route("/slow", get(slow_handler));
        let router = apply_request_timeout_middleware(router, Some(1));

        let client = TestClient::new(router);
        let start = std::time::Instant::now();
        let response = client.get("/slow").send().await;
        let elapsed = start.elapsed();

        assert_eq!(response.status(), StatusCode::REQUEST_TIMEOUT);
        // Should timeout around 1 second (within 1.5 seconds, accounting for test overhead)
        assert!(elapsed >= StdDuration::from_millis(900)); // At least 900ms
        assert!(elapsed < StdDuration::from_millis(1500)); // But less than 1.5s
    }

    #[tokio::test]
    async fn test_no_timeout_when_none_specified() {
        // Test with 1 second timeout - should timeout on slow handler (which sleeps 2 seconds)
        let router = Router::new().route("/slow", get(slow_handler));
        let router = apply_request_timeout_middleware(router, None);

        let client = TestClient::new(router);
        let start = std::time::Instant::now();
        let response = client.get("/slow").send().await;
        let elapsed = start.elapsed();

        assert_eq!(response.status(), StatusCode::OK);
        // Should complete within 2 seconds since no timeout is specified
        assert!(elapsed >= StdDuration::from_millis(2000)); // At least 2 seconds
    }

    #[tokio::test]
    async fn test_timeout_on_long_running_handler_payload() {
        // Test with 1 second timeout - should timeout parsing huge request body
        let router = Router::new().route("/long_running", post(indefinite_work_handler));
        let router = apply_request_timeout_middleware(router, Some(1));

        let client = TestClient::new(router);

        let mut data = vec![];
        for _ in 1..=1000 {
            let mut obj = HashMap::new();
            for i in 1..=100 {
                obj.insert(format!("key_{i}"), format!("value_{i}"));
            }
            data.push(obj);
        }
        let payload = Bytes::from(json!(data).to_string());

        let start = std::time::Instant::now();
        let response = client.post("/long_running").body(payload).send().await;
        let elapsed = start.elapsed();

        assert_eq!(response.status(), StatusCode::REQUEST_TIMEOUT);
        // Should timeout around 1 second (within 1.5 seconds, accounting for test overhead)
        assert!(elapsed >= StdDuration::from_millis(900)); // At least 900ms
        assert!(elapsed < StdDuration::from_millis(1500)); // But less than 1.5s
    }
}
