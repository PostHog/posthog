//! Which paths each capture mode registers.
//!
//! capture-ai loads only the `ai` restriction slice
//! (`Pipeline::for_capture_mode`), so any analytics route registered there
//! would accept traffic no restriction ever governs. The ingress only sends
//! `/i/v0/ai*` to that deployment today, but the router is the thing that has
//! to hold if the ingress is ever changed, so it is asserted directly here.
//!
//! The pipeline-level gate in `events::analytics` covers the other half: an
//! event name off the AI allowlist arriving on a path that IS registered.

#[path = "common/integration_utils.rs"]
mod integration_utils;

use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;
use capture::config::CaptureMode;
use capture::quota_limiters::CaptureQuotaLimiter;
use capture::router::router;
use capture::sinks::print::PrintSink;
use capture::time::TimeSource;
use chrono::{DateTime, Utc};
use common_redis::MockRedisClient;
use integration_utils::{test_lifecycle_handlers, DEFAULT_CONFIG, DEFAULT_TEST_TIME};
use limiters::token_dropper::TokenDropper;
use rstest::rstest;
use serde_json::json;
use std::sync::Arc;
use std::time::Duration;

struct FixedTime {
    time: DateTime<Utc>,
}

impl TimeSource for FixedTime {
    fn current_time(&self) -> DateTime<Utc> {
        self.time
    }
}

fn setup_router_for_mode(capture_mode: CaptureMode) -> Router {
    let (readiness, liveness, _monitor) = test_lifecycle_handlers();
    let redis = Arc::new(MockRedisClient::new());
    let mut cfg = DEFAULT_CONFIG.clone();
    cfg.capture_mode = capture_mode;
    let quota_limiter =
        CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60 * 60 * 24 * 7));

    router(
        FixedTime {
            time: DateTime::parse_from_rfc3339(DEFAULT_TEST_TIME)
                .expect("invalid fixed time")
                .with_timezone(&Utc),
        },
        readiness,
        liveness,
        Arc::new(PrintSink {}),
        redis,
        None, // global_rate_limiter_token_distinctid
        quota_limiter,
        TokenDropper::default(),
        None, // event_restriction_service
        None, // recorder_handle
        capture_mode,
        None,
        25 * 1024 * 1024,
        false,
        1_i64,
        false,
        0.0_f32,
        26_214_400,
        None,
        256,              // body_read_chunk_size_kb
        10 * 1024 * 1024, // capture_v1_max_compressed_body_bytes
        50 * 1024 * 1024, // capture_v1_max_decompressed_body_bytes
        None,             // overflow_limiter
        None,             // ai_events_overflow_limiter
        None,             // ai_byte_rate_limiter
        None,             // replay_overflow_limiter
        None,             // v1_sink_router
        8,                // capture_v1_scatter_gather_min_batch
        None,             // ai_gateway_signing_secret
        false,            // ai_events_overflow_enabled
        None,             // ingestion_warning_emitter
    )
}

/// A single `$ai_generation`, valid on any path that accepts a batch.
fn ai_batch_payload() -> String {
    json!({
        "api_key": "phc_route_surface_token",
        "batch": [{
            "event": "$ai_generation",
            "distinct_id": "test_user",
            "properties": {},
        }],
    })
    .to_string()
}

/// A route is "registered" when the router does not 404 it. The handler may
/// still reject the payload for its own reasons, which is not what this file
/// is about, so any non-404 counts as registered.
async fn is_registered(router: Router, path: &str) -> bool {
    let res = TestClient::new(router)
        .post(path)
        .body(ai_batch_payload())
        .header("Content-Type", "application/json")
        .send()
        .await;
    res.status() != StatusCode::NOT_FOUND
}

/// capture-ai must serve the AI batch path and nothing analytics-shaped.
#[rstest]
#[case::ai_batch("/i/v0/ai/batch", true)]
#[case::ai_batch_trailing_slash("/i/v0/ai/batch/", true)]
#[case::ai_multipart("/i/v0/ai", true)]
#[case::ai_otel("/i/v0/ai/otel", true)]
#[case::analytics_batch("/batch", false)]
#[case::analytics_event("/e", false)]
#[case::analytics_capture("/capture", false)]
#[case::analytics_track("/track", false)]
#[case::analytics_engage("/engage", false)]
#[case::analytics_v1("/i/v1/analytics/events", false)]
#[tokio::test]
async fn ai_mode_registers_only_the_ai_paths(#[case] path: &str, #[case] expected: bool) {
    assert_eq!(
        is_registered(setup_router_for_mode(CaptureMode::Ai), path).await,
        expected,
        "capture-ai registration for {path} should be {expected}"
    );
}

/// The analytics deployment keeps every path it had, including the AI ones it
/// serves for teams whose traffic is not split out to capture-ai.
#[rstest]
#[case::analytics_batch("/batch")]
#[case::analytics_event("/e")]
#[case::analytics_capture("/capture")]
#[case::ai_batch("/i/v0/ai/batch")]
#[case::ai_multipart("/i/v0/ai")]
#[case::ai_otel("/i/v0/ai/otel")]
#[tokio::test]
async fn events_mode_still_registers_every_path(#[case] path: &str) {
    assert!(
        is_registered(setup_router_for_mode(CaptureMode::Events), path).await,
        "capture-analytics must keep serving {path}"
    );
}

/// Import keeps the AI batch path (it dispatches to the gated batch handler)
/// and must keep refusing the two AI handlers that build their own context
/// with `historical_migration: false`, which would sidestep the import gates.
#[rstest]
#[case::analytics_batch("/batch", true)]
#[case::ai_batch("/i/v0/ai/batch", true)]
#[case::ai_multipart("/i/v0/ai", false)]
#[case::ai_otel("/i/v0/ai/otel", false)]
#[tokio::test]
async fn import_mode_keeps_the_batch_paths_only(#[case] path: &str, #[case] expected: bool) {
    assert_eq!(
        is_registered(setup_router_for_mode(CaptureMode::Import), path).await,
        expected,
        "capture-import registration for {path} should be {expected}"
    );
}
