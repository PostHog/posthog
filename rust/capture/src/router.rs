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
use health::HealthRegistry;
use tower::limit::ConcurrencyLimitLayer;
use tower_http::cors::{AllowHeaders, AllowOrigin, CorsLayer};
use tower_http::trace::TraceLayer;

use crate::ai_s3::BlobStorage;
use crate::event_restrictions::EventRestrictionService;
use crate::test_endpoint;
use crate::v0_request::DataType;
use crate::{ai_endpoint, sinks, time::TimeSource, v0_endpoint};
use common_redis::Client;
use limiters::token_dropper::TokenDropper;

use crate::config::CaptureMode;
use crate::limiters::CaptureQuotaLimiter;
use crate::metrics_middleware::{apply_request_timeout, track_metrics};
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
    pub event_restriction_service: Option<EventRestrictionService>,
    pub event_size_limit: usize,
    pub historical_cfg: HistoricalConfig,
    pub is_mirror_deploy: bool,
    pub verbose_sample_percent: f32,
    pub ai_max_sum_of_parts_bytes: usize,
    pub ai_blob_storage: Option<Arc<dyn BlobStorage>>,
    pub body_chunk_read_timeout: Option<Duration>,
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

        let days_stale = ChronoDuration::days(self.historical_rerouting_threshold_days);
        let threshold = Utc::now() - days_stale;
        timestamp <= threshold
    }
}

async fn index() -> &'static str {
    "capture"
}

async fn readiness() -> axum::http::StatusCode {
    use crate::metrics_middleware::ShutdownStatus;

    let shutdown_status = crate::metrics_middleware::get_shutdown_status();
    let is_running_or_unknown =
        shutdown_status == ShutdownStatus::Running || shutdown_status == ShutdownStatus::Unknown;

    if is_running_or_unknown && std::path::Path::new("/tmp/shutdown").exists() {
        crate::metrics_middleware::set_shutdown_status(ShutdownStatus::Prestop);
        tracing::info!("Shutdown status change: PRESTOP");
    }

    if is_running_or_unknown {
        axum::http::StatusCode::OK
    } else {
        axum::http::StatusCode::SERVICE_UNAVAILABLE
    }
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
    event_restriction_service: Option<EventRestrictionService>,
    metrics: bool,
    capture_mode: CaptureMode,
    deploy_role: String,
    concurrency_limit: Option<usize>,
    event_size_limit: usize,
    enable_historical_rerouting: bool,
    historical_rerouting_threshold_days: i64,
    is_mirror_deploy: bool,
    verbose_sample_percent: f32,
    ai_max_sum_of_parts_bytes: usize,
    ai_blob_storage: Option<Arc<dyn BlobStorage>>,
    request_timeout_seconds: Option<u64>,
    body_chunk_read_timeout_ms: Option<u64>,
) -> Router {
    let state = State {
        sink: Arc::new(sink),
        timesource: Arc::new(timesource),
        redis,
        quota_limiter: Arc::new(quota_limiter),
        event_size_limit,
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
        .route("/_readiness", get(readiness))
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
    router = apply_request_timeout(router, request_timeout_seconds);

    let router = router
        .layer(TraceLayer::new_for_http())
        .layer(cors)
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
    use super::*;

    use std::time::Duration as StdDuration;

    use axum::http::StatusCode;
    use axum_test_helper::TestClient;

    async fn slow_handler() -> &'static str {
        // Sleep for 2 seconds to ensure timeout with 1 second timeout
        tokio::time::sleep(StdDuration::from_secs(2)).await;
        "slow response"
    }

    async fn fast_handler() -> &'static str {
        "fast response"
    }

    #[tokio::test]
    async fn test_timeout_returns_408() {
        // Use a 1 second timeout - the slow handler sleeps for 2 seconds, so it should timeout
        // Create router with test route included before timeout middleware is applied
        let router = Router::new().route("/slow", get(slow_handler));
        let router = apply_request_timeout(router, Some(1));

        let client = TestClient::new(router);
        let response = client.get("/slow").send().await;

        assert_eq!(response.status(), StatusCode::GATEWAY_TIMEOUT);
        let body = response.text().await;
        assert_eq!(body, "Request timeout");
    }

    #[tokio::test]
    async fn test_normal_request_completes_within_timeout() {
        // Use a longer timeout (1 second) so normal requests complete
        let router = Router::new().route("/fast", get(fast_handler));
        let router = apply_request_timeout(router, Some(1));

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
        let router = apply_request_timeout(router, Some(1));

        let client = TestClient::new(router);
        let start = std::time::Instant::now();
        let response = client.get("/slow").send().await;
        let elapsed = start.elapsed();

        assert_eq!(response.status(), StatusCode::GATEWAY_TIMEOUT);
        // Should timeout around 1 second (within 1.5 seconds, accounting for test overhead)
        assert!(elapsed >= StdDuration::from_millis(900)); // At least 900ms
        assert!(elapsed < StdDuration::from_millis(1500)); // But less than 1.5s
    }

    #[tokio::test]
    async fn test_no_timeout_when_none_specified() {
        // Test when None is specified - should complete without timeout
        let router = Router::new().route("/slow", get(slow_handler));
        let router = apply_request_timeout(router, None);

        let client = TestClient::new(router);
        let start = std::time::Instant::now();
        let response = client.get("/slow").send().await;
        let elapsed = start.elapsed();

        assert_eq!(response.status(), StatusCode::OK);
        // Should complete within 2 seconds since no timeout is specified
        assert!(elapsed >= StdDuration::from_millis(2000)); // At least 2 seconds
    }

    #[tokio::test]
    async fn test_timeout_on_incomplete_request() {
        // Test with 1 second timeout - simulate slow body transfer (slowloris style)
        // Send complete headers but incomplete/slow body so handler starts but times out during body reading
        use std::net::SocketAddr;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        use tokio::net::{TcpListener, TcpStream};

        async fn body_reading_handler(body: axum::body::Body) -> &'static str {
            // This handler reads body as a stream, which will hang if body is incomplete
            // The timeout middleware should trigger while waiting for body chunks
            use futures::StreamExt;

            let mut stream = body.into_data_stream();
            // Try to read all chunks - this will hang if body is incomplete
            while stream.next().await.is_some() {
                // Process chunks
            }
            "should never reach here"
        }

        let router = Router::new().route("/test", post(body_reading_handler));
        let router = apply_request_timeout(router, Some(1));

        // Bind to a random port
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();

        // Spawn the server
        let server_handle = tokio::spawn(async move {
            axum::serve(
                listener,
                router.into_make_service_with_connect_info::<SocketAddr>(),
            )
            .await
            .unwrap();
        });

        // Give server time to start
        tokio::time::sleep(StdDuration::from_millis(100)).await;

        // Connect and send complete headers but incomplete body
        let mut stream = TcpStream::connect(addr).await.unwrap();

        // Send complete request line and headers
        stream.write_all(b"POST /test HTTP/1.1\r\n").await.unwrap();
        stream.write_all(b"Host: localhost\r\n").await.unwrap();
        stream
            .write_all(b"Content-Length: 10000\r\n")
            .await
            .unwrap(); // Claim large body
        stream
            .write_all(b"Content-Type: application/json\r\n")
            .await
            .unwrap();
        stream.write_all(b"\r\n").await.unwrap(); // Complete headers - this triggers request parsing

        // Send just a tiny bit of body data, then wait
        stream.write_all(b"{").await.unwrap();

        // Keep connection alive but don't send more data
        // The handler is waiting for the remaining 9999 bytes
        tokio::time::sleep(StdDuration::from_millis(1200)).await;

        // Try to read response - should get timeout response
        let mut buf = [0u8; 1024];
        let read_result = stream.read(&mut buf).await;

        // Should receive timeout response (408 Request Timeout)
        if let Ok(bytes_read) = read_result {
            if bytes_read > 0 {
                let response = String::from_utf8_lossy(&buf[..bytes_read]);
                assert!(response.contains("408") || response.contains("Request timeout"));
            }
        }

        // Clean up
        server_handle.abort();
    }

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
        let result = extract_body_with_timeout(body, 1024 * 1024, timeout, "/test").await;

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
        let result = extract_body_with_timeout(body, 1024 * 1024, None, "/test").await;

        assert!(result.is_ok());
        assert_eq!(result.unwrap(), r#"{"event": "test"}"#.as_bytes());
    }
}
