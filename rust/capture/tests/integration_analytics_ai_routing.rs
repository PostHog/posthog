//! Endpoint-level coverage for AI event routing on analytics deployments:
//! HTTP request -> router state -> `process_events` -> sink. The pipeline
//! tests in `events::analytics` exercise `process_events` directly, so they
//! cannot catch a regression in the router wiring (capture mode /
//! `ai_events_overflow_enabled` not reaching the pipeline) or in the
//! endpoint-level batch handling of mixed AI / non-AI payloads.

#[path = "common/integration_utils.rs"]
mod integration_utils;

use async_trait::async_trait;
use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;
use capture::api::CaptureError;
use capture::config::CaptureMode;
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
    ai_events_overflow_enabled: bool,
    overflow_limiter: Option<Arc<OverflowLimiter>>,
    ai_events_overflow_limiter: Option<Arc<OverflowLimiter>>,
) -> (Router, CapturingSink) {
    setup_router_for_mode(
        CaptureMode::Events,
        ai_events_overflow_enabled,
        overflow_limiter,
        ai_events_overflow_limiter,
    )
}

fn setup_router_for_mode(
    capture_mode: CaptureMode,
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
    cfg.capture_mode = capture_mode;

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
        None, // recorder_handle
        capture_mode,
        None,
        25 * 1024 * 1024,
        false,
        1_i64,
        false,
        0.0_f32,
        26_214_400,
        983_040, // ai_max_event_bytes (960KB, the previous hardcoded limit)
        None,
        256,              // body_read_chunk_size_kb
        10 * 1024 * 1024, // capture_v1_max_compressed_body_bytes
        50 * 1024 * 1024, // capture_v1_max_decompressed_body_bytes
        overflow_limiter,
        ai_events_overflow_limiter,
        None, // ai_byte_rate_limiter
        None, // replay_overflow_limiter
        None, // v1_sink_router
        8,    // capture_v1_scatter_gather_min_batch
        None, // ai_gateway_signing_secret
        ai_events_overflow_enabled,
        None, // ingestion_warning_emitter
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

// Two allowlisted AI event names. capture-ai rejects a batch carrying anything
// else, so its lane-assignment coverage has to use an all-AI batch.
fn ai_only_batch_payload() -> String {
    json!({
        "api_key": TOKEN,
        "batch": [
            {
                "event": "$ai_generation",
                "distinct_id": DISTINCT_ID,
                "properties": {"$ai_model": "gpt-4"}
            },
            {
                "event": "$ai_span",
                "distinct_id": DISTINCT_ID,
                "properties": {}
            }
        ]
    })
    .to_string()
}

// The same mixed batch flagged as a historical migration — the only kind of
// batch Import mode accepts.
fn historical_mixed_batch_payload() -> String {
    json!({
        "api_key": TOKEN,
        "historical_migration": true,
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

#[rstest]
#[case("/e")]
#[case("/batch")]
#[tokio::test]
async fn legacy_routes_strip_forged_gateway_properties(#[case] path: &str) {
    let (router, sink) = setup_analytics_router(false, None, None);
    let client = TestClient::new(router);
    let event = json!({
        "event": "$ai_span",
        "distinct_id": DISTINCT_ID,
        "properties": {
            "$ai_gateway_verified": true,
            "$ai_gateway_relay": true,
            "$ai_gateway_request_id": "forged",
            "$ai_trace_id": "trace-1"
        }
    });
    let payload = if path == "/batch" {
        json!({"api_key": TOKEN, "batch": [event]}).to_string()
    } else {
        json!({
            "api_key": TOKEN,
            "event": "$ai_span",
            "distinct_id": DISTINCT_ID,
            "properties": event["properties"].clone()
        })
        .to_string()
    };

    let response = client
        .post(path)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(payload)
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);
    let events = sink.get_events().await;
    let data: serde_json::Value = serde_json::from_str(&events[0].event.data).unwrap();
    assert_eq!(data["properties"]["$ai_trace_id"], "trace-1");
    assert!(data["properties"].get("$ai_gateway_verified").is_none());
    assert!(data["properties"].get("$ai_gateway_relay").is_none());
    assert!(data["properties"].get("$ai_gateway_request_id").is_none());
}

/// A mixed batch must split lanes: AI events divert to the AI lane on
/// analytics deployments, and the `$pageview` stays on the analytics lane.
/// The valve-armed case pins down that the overflow valve alone does not
/// change lane assignment.
#[rstest]
#[case::valve_unarmed(false)]
#[case::valve_armed(true)]
#[tokio::test]
async fn mixed_batch_diverts_only_ai_events(#[case] ai_events_overflow_enabled: bool) {
    let (router, sink) = setup_analytics_router(ai_events_overflow_enabled, None, None);
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
        "no limiter is configured, so nothing may stamp overflow"
    );

    let pageview = events
        .iter()
        .find(|e| e.metadata.event_name == "$pageview")
        .expect("$pageview must reach the sink");
    assert_eq!(pageview.metadata.data_type, DataType::AnalyticsMain);
}

/// Capture mode does not change lane assignment: an Ai-mode deployment stamps
/// `AiEvents` exactly like an analytics one. Pins the invariant end-to-end, so
/// a deployment can never silently rejoin AI events to the analytics lane and
/// slip past every AI-lane gate (byte limiter, ai restrictions, AI overflow).
///
/// The batch is all-AI because capture-ai refuses anything else; the mixed-batch
/// half of the old version of this test now lives below.
#[tokio::test]
async fn ai_mode_diverts_ai_events_like_every_other_mode() {
    let (router, sink) = setup_router_for_mode(CaptureMode::Ai, false, None, None);
    let client = TestClient::new(router);

    let response = client
        .post("/i/v0/ai/batch")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(ai_only_batch_payload())
        .send()
        .await;
    assert_eq!(response.status(), StatusCode::OK);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 2);
    assert!(
        events
            .iter()
            .all(|e| e.metadata.data_type == DataType::AiEvents),
        "every allowlisted AI event must land on the AI lane under Ai mode"
    );
}

/// The endpoint-level half of the AI-lane gate. The unit tests in
/// `events::analytics` call `process_events` directly, so only this proves the
/// rejection is reachable through the router and surfaces as a 400.
#[tokio::test]
async fn ai_mode_rejects_a_mixed_batch_through_the_endpoint() {
    let (router, sink) = setup_router_for_mode(CaptureMode::Ai, false, None, None);
    let client = TestClient::new(router);

    let response = client
        .post("/i/v0/ai/batch")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(mixed_batch_payload())
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    assert!(
        sink.get_events().await.is_empty(),
        "rejecting the batch must not publish the AI event ahead of the offender"
    );
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
/// overflow-stamps the diverted AI event only when the AI overflow
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
/// AI event into AI overflow (and the pageview must still stamp).
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

/// Import mode's no-overflow guarantee, end-to-end on the legacy path. Non-AI
/// events in a historical batch land on `AnalyticsHistorical`; AI events
/// divert to the AI lane (only the AI lane has AI processing, so imports must
/// divert too). With the AI overflow valve unset — the capture-import config —
/// neither lane can stamp overflow, even with the overflow limiter force-keyed
/// on the batch's `token:distinct_id`, and the GRL never runs.
#[tokio::test]
async fn import_mode_historical_batch_never_overflows() {
    let (router, sink) = setup_router_for_mode(
        CaptureMode::Import,
        false,
        Some(force_keyed_limiter()),
        None,
    );
    let client = TestClient::new(router);

    post_batch(&client, historical_mixed_batch_payload()).await;

    let events = sink.get_events().await;
    assert_eq!(
        events.len(),
        2,
        "both historical events must reach the sink"
    );

    for event in &events {
        let expected = if event.metadata.event_name == "$ai_generation" {
            DataType::AiEvents
        } else {
            DataType::AnalyticsHistorical
        };
        assert_eq!(
            event.metadata.data_type, expected,
            "unexpected lane for {}",
            event.metadata.event_name,
        );
        assert_eq!(
            event.metadata.overflow_reason, None,
            "no lane may overflow in Import mode with the AI valve unset ({})",
            event.metadata.event_name,
        );
    }
}
