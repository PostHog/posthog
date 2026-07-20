//! Endpoint-level coverage for `$ai_*` routing on analytics deployments:
//! HTTP request -> router state -> `process_events` -> sink. The pipeline
//! tests in `events::analytics` exercise `process_events` directly, so they
//! cannot catch a regression in the router wiring (`ai_routing` /
//! `ai_events_overflow_enabled` not reaching the pipeline) or in the
//! endpoint-level batch handling of mixed `$ai_*` / non-AI payloads.

#[path = "common/integration_utils.rs"]
mod integration_utils;

use async_trait::async_trait;
use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;
use capture::api::CaptureError;
use capture::config::{AiRouting, CaptureMode};
use capture::quota_limiters::CaptureQuotaLimiter;
use capture::router::router;
use capture::sinks::Event;
use capture::time::TimeSource;
use capture::v0_request::{DataType, OverflowReason, ProcessedEvent};
use chrono::{DateTime, Utc};
use common_redis::MockRedisClient;
use integration_utils::{test_lifecycle_handlers, DEFAULT_CONFIG, DEFAULT_TEST_TIME};
use limiters::overflow::OverflowLimiter;
use limiters::token_dropper::TokenDropper;
use rstest::rstest;
use serde_json::json;
use std::collections::HashSet;
use std::num::NonZeroU32;
use std::sync::Arc;
use std::time::Duration;

const TOKEN: &str = "phc_ai_routing_test_token";
const DISTINCT_ID: &str = "test_user";

struct FixedTime {
    pub time: DateTime<Utc>,
}

impl TimeSource for FixedTime {
    fn current_time(&self) -> DateTime<Utc> {
        self.time
    }
}

#[derive(Clone)]
struct CapturingSink {
    events: Arc<tokio::sync::Mutex<Vec<ProcessedEvent>>>,
}

impl CapturingSink {
    fn new() -> Self {
        Self {
            events: Arc::new(tokio::sync::Mutex::new(Vec::new())),
        }
    }

    async fn get_events(&self) -> Vec<ProcessedEvent> {
        self.events.lock().await.clone()
    }
}

#[async_trait]
impl Event for CapturingSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.events.lock().await.push(event);
        Ok(())
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.events.lock().await.extend(events);
        Ok(())
    }
}

fn setup_analytics_router(
    ai_routing: AiRouting,
    ai_events_overflow_enabled: bool,
    overflow_limiter: Option<Arc<OverflowLimiter>>,
    ai_events_overflow_limiter: Option<Arc<OverflowLimiter>>,
) -> (Router, CapturingSink) {
    let (readiness, liveness, _monitor) = test_lifecycle_handlers();

    let sink = CapturingSink::new();
    let sink_clone = sink.clone();
    let timesource = FixedTime {
        time: DateTime::parse_from_rfc3339(DEFAULT_TEST_TIME)
            .expect("Invalid fixed time format")
            .with_timezone(&Utc),
    };
    let redis = Arc::new(MockRedisClient::new());

    let mut cfg = DEFAULT_CONFIG.clone();
    cfg.capture_mode = CaptureMode::Events;

    let quota_limiter =
        CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60 * 60 * 24 * 7));

    let router = router(
        timesource,
        readiness,
        liveness,
        Arc::new(sink),
        redis,
        None, // global_rate_limiter_token_distinctid
        quota_limiter,
        TokenDropper::default(),
        None, // event_restriction_service
        false,
        CaptureMode::Events,
        String::from("capture-analytics"),
        None,
        25 * 1024 * 1024,
        false,
        1_i64,
        false,
        0.0_f32,
        26_214_400,
        None, // no blob storage for analytics
        None,
        256,              // body_read_chunk_size_kb
        10 * 1024 * 1024, // capture_v1_max_compressed_body_bytes
        50 * 1024 * 1024, // capture_v1_max_decompressed_body_bytes
        overflow_limiter,
        ai_events_overflow_limiter,
        None, // replay_overflow_limiter
        None, // v1_sink_router
        8,    // capture_v1_scatter_gather_min_batch
        None, // ai_gateway_signing_secret
        ai_routing,
        ai_events_overflow_enabled,
    );

    (router, sink_clone)
}

fn mixed_batch_payload() -> String {
    json!({
        "api_key": TOKEN,
        "batch": [
            {
                "event": "$ai_generation",
                "distinct_id": DISTINCT_ID,
                "properties": {"$ai_model": "gpt-4"}
            },
            {
                "event": "$pageview",
                "distinct_id": DISTINCT_ID,
                "properties": {}
            }
        ]
    })
    .to_string()
}

async fn post_batch(client: &TestClient, payload: String) {
    let response = client
        .post("/batch")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(payload)
        .send()
        .await;
    assert_eq!(response.status(), StatusCode::OK);
}

fn allowlist(tokens: &[&str]) -> AiRouting {
    AiRouting::SecondaryAllowlist(tokens.iter().map(|t| t.to_string()).collect::<HashSet<_>>())
}

/// A mixed batch must split lanes per the deployment's routing mode: only
/// `$ai_*` events divert, only when the mode says so, and the `$pageview`
/// stays on the analytics lane in every mode. The `primary` case runs with
/// the overflow valve armed, pinning down that topic/valve config alone
/// (mode left at `primary`) diverts nothing.
#[rstest]
#[case::secondary(AiRouting::Secondary, false, DataType::AiEvents)]
#[case::allowlisted_token(allowlist(&[TOKEN]), false, DataType::AiEvents)]
#[case::unlisted_token(allowlist(&["phc_other"]), false, DataType::AnalyticsMain)]
#[case::primary_with_valve_armed(AiRouting::Primary, true, DataType::AnalyticsMain)]
#[tokio::test]
async fn mixed_batch_diverts_only_ai_events_per_routing_mode(
    #[case] ai_routing: AiRouting,
    #[case] ai_events_overflow_enabled: bool,
    #[case] expected_ai_data_type: DataType,
) {
    let (router, sink) = setup_analytics_router(ai_routing, ai_events_overflow_enabled, None, None);
    let client = TestClient::new(router);

    post_batch(&client, mixed_batch_payload()).await;

    let events = sink.get_events().await;
    assert_eq!(events.len(), 2);

    let ai_event = events
        .iter()
        .find(|e| e.metadata.event_name == "$ai_generation")
        .expect("$ai_generation must reach the sink");
    assert_eq!(ai_event.metadata.data_type, expected_ai_data_type);
    assert_eq!(
        ai_event.metadata.overflow_reason, None,
        "no limiter is configured, so nothing may stamp overflow"
    );

    let pageview = events
        .iter()
        .find(|e| e.metadata.event_name == "$pageview")
        .expect("$pageview must reach the sink");
    assert_eq!(pageview.metadata.data_type, DataType::AnalyticsMain);
}

fn force_keyed_limiter() -> Arc<OverflowLimiter> {
    let hot_key = format!("{TOKEN}:{DISTINCT_ID}");
    Arc::new(OverflowLimiter::new(
        NonZeroU32::new(1_000).unwrap(),
        NonZeroU32::new(1_000).unwrap(),
        Some(hot_key),
        false, // preserve_locality
    ))
}

/// With `secondary` routing, a force-limited key on the AI limiter
/// overflow-stamps the diverted `$ai_*` event only when the AI overflow
/// valve is armed (setup wires the AI limiter exactly then, so the test
/// mirrors that coupling), while the `$pageview` on the same hot key
/// (force-limited on the analytics limiter) stamps in both cases (the
/// analytics lane is valve-independent). Catches the router failing to
/// thread the AI limiter into the pipeline, which the process-level tests
/// cannot see.
#[rstest]
#[case::valve_armed(true, Some(OverflowReason::ForceLimited))]
#[case::valve_unarmed(false, None)]
#[tokio::test]
async fn ai_lane_overflow_stamping_gated_on_valve(
    #[case] ai_events_overflow_enabled: bool,
    #[case] expected_ai_reason: Option<OverflowReason>,
) {
    let (router, sink) = setup_analytics_router(
        AiRouting::Secondary,
        ai_events_overflow_enabled,
        Some(force_keyed_limiter()),
        ai_events_overflow_enabled.then(force_keyed_limiter),
    );
    let client = TestClient::new(router);

    post_batch(&client, mixed_batch_payload()).await;

    let events = sink.get_events().await;
    assert_eq!(events.len(), 2);

    let ai_event = events
        .iter()
        .find(|e| e.metadata.event_name == "$ai_generation")
        .expect("$ai_generation must reach the sink");
    assert_eq!(ai_event.metadata.data_type, DataType::AiEvents);
    assert_eq!(ai_event.metadata.overflow_reason, expected_ai_reason);

    let pageview = events
        .iter()
        .find(|e| e.metadata.event_name == "$pageview")
        .expect("$pageview must reach the sink");
    assert_eq!(pageview.metadata.data_type, DataType::AnalyticsMain);
    assert_eq!(
        pageview.metadata.overflow_reason,
        Some(OverflowReason::ForceLimited),
        "the analytics lane must keep overflowing regardless of the AI valve"
    );
}

/// The two lanes consult separate limiter instances end-to-end: a key that
/// the analytics limiter force-routes must not drag the same key's diverted
/// `$ai_*` event into AI overflow (and the pageview must still stamp).
/// Catches the router wiring one limiter instance into both slots.
#[tokio::test]
async fn ai_lane_overflow_isolated_from_analytics_limiter() {
    let clean_ai_limiter = Arc::new(OverflowLimiter::new(
        NonZeroU32::new(1_000).unwrap(),
        NonZeroU32::new(1_000).unwrap(),
        None,
        false, // preserve_locality
    ));

    let (router, sink) = setup_analytics_router(
        AiRouting::Secondary,
        true, // valve armed
        Some(force_keyed_limiter()),
        Some(clean_ai_limiter),
    );
    let client = TestClient::new(router);

    post_batch(&client, mixed_batch_payload()).await;

    let events = sink.get_events().await;
    assert_eq!(events.len(), 2);

    let ai_event = events
        .iter()
        .find(|e| e.metadata.event_name == "$ai_generation")
        .expect("$ai_generation must reach the sink");
    assert_eq!(ai_event.metadata.data_type, DataType::AiEvents);
    assert_eq!(
        ai_event.metadata.overflow_reason, None,
        "the analytics limiter's force-routed key must not stamp the AI lane"
    );

    let pageview = events
        .iter()
        .find(|e| e.metadata.event_name == "$pageview")
        .expect("$pageview must reach the sink");
    assert_eq!(
        pageview.metadata.overflow_reason,
        Some(OverflowReason::ForceLimited)
    );
}
