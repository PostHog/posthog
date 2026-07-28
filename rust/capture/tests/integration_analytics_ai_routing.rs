//! Endpoint-level coverage for `$ai_*` routing on analytics deployments:
//! HTTP request -> router state -> `process_events` -> outputs. The pipeline
//! tests in `events::analytics` exercise `process_events` directly, so they
//! cannot catch a regression in the router wiring (`ai_routing` /
//! `ai_events_overflow_enabled` not reaching the pipeline) or in the
//! endpoint-level batch handling of mixed `$ai_*` / non-AI payloads.

#[path = "common/integration_utils.rs"]
mod integration_utils;

use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;
use capture::config::{AiRouting, CaptureMode, EnvelopeCompression};
use capture::outputs::testing::MockOutputs;
use capture::outputs::{AddressedPayload, AnalyticsFamilyOutputs, PrepSpec};
use capture::pipeline::{Address, AiLane, AnalyticsLane};
use capture::quota_limiters::CaptureQuotaLimiter;
use capture::router::router;
use capture::time::TimeSource;
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

fn setup_analytics_router(
    ai_routing: AiRouting,
    ai_events_overflow_enabled: bool,
    overflow_limiter: Option<Arc<OverflowLimiter>>,
    ai_events_overflow_limiter: Option<Arc<OverflowLimiter>>,
) -> (Router, MockOutputs) {
    setup_router_for_mode(
        CaptureMode::Events,
        ai_routing,
        ai_events_overflow_enabled,
        overflow_limiter,
        ai_events_overflow_limiter,
    )
}

fn setup_router_for_mode(
    capture_mode: CaptureMode,
    ai_routing: AiRouting,
    ai_events_overflow_enabled: bool,
    overflow_limiter: Option<Arc<OverflowLimiter>>,
    ai_events_overflow_limiter: Option<Arc<OverflowLimiter>>,
) -> (Router, MockOutputs) {
    let (readiness, liveness, _monitor) = test_lifecycle_handlers();

    // The capturing surface preps with the deployment's valve state, exactly
    // as a real Kafka surface would.
    let mock = MockOutputs::with_prep(PrepSpec::new(
        EnvelopeCompression::None,
        ai_events_overflow_enabled,
    ));
    let row = || -> Arc<MockOutputs> { Arc::new(mock.clone()) };
    let outputs = Arc::new(AnalyticsFamilyOutputs {
        analytics: row(),
        ai: row(),
        heatmaps: row(),
        warnings: row(),
        error_tracking: row(),
    });

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
        outputs,
        redis,
        None, // global_rate_limiter_token_distinctid
        quota_limiter,
        TokenDropper::default(),
        None, // event_restriction_service
        false,
        capture_mode,
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
        None, // ingestion_warning_emitter
    );

    (router, mock)
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

/// The captured payload carrying `event_name` (the serialized event rides
/// inside the payload bytes).
fn find_payload(payloads: &[AddressedPayload], event_name: &str) -> AddressedPayload {
    payloads
        .iter()
        .find(|p| String::from_utf8_lossy(&p.payload).contains(event_name))
        .unwrap_or_else(|| panic!("{event_name} must reach the outputs"))
        .clone()
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
#[case::secondary(AiRouting::Secondary, false, Address::Ai(AiLane::Main))]
#[case::allowlisted_token(allowlist(&[TOKEN]), false, Address::Ai(AiLane::Main))]
#[case::unlisted_token(allowlist(&["phc_other"]), false, Address::Analytics(AnalyticsLane::Main))]
#[case::full_percentage(AiRouting::SecondaryPercentage(100), false, Address::Ai(AiLane::Main))]
#[case::zero_percentage(
    AiRouting::SecondaryPercentage(0),
    false,
    Address::Analytics(AnalyticsLane::Main)
)]
#[case::primary_with_valve_armed(AiRouting::Primary, true, Address::Analytics(AnalyticsLane::Main))]
#[tokio::test]
async fn mixed_batch_diverts_only_ai_events_per_routing_mode(
    #[case] ai_routing: AiRouting,
    #[case] ai_events_overflow_enabled: bool,
    #[case] expected_ai_address: Address,
) {
    let (router, outputs) =
        setup_analytics_router(ai_routing, ai_events_overflow_enabled, None, None);
    let client = TestClient::new(router);

    post_batch(&client, mixed_batch_payload()).await;

    let payloads = outputs.get_payloads();
    assert_eq!(payloads.len(), 2);

    let ai_event = find_payload(&payloads, "$ai_generation");
    assert_eq!(
        ai_event.address, expected_ai_address,
        "no limiter is configured, so nothing may land on an overflow lane"
    );

    let pageview = find_payload(&payloads, "$pageview");
    assert_eq!(pageview.address, Address::Analytics(AnalyticsLane::Main));
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

/// With `secondary` routing, a force-limited key on the AI limiter routes the
/// diverted `$ai_*` event to the AI overflow lane only when the AI overflow
/// valve is armed (setup wires the AI limiter exactly then, so the test
/// mirrors that coupling), while the `$pageview` on the same hot key
/// (force-limited on the analytics limiter) overflows in both cases (the
/// analytics lane is valve-independent). Catches the router failing to
/// thread the AI limiter into the pipeline, which the process-level tests
/// cannot see.
#[rstest]
#[case::valve_armed(true, Address::Ai(AiLane::Overflow), None)]
#[case::valve_unarmed(false, Address::Ai(AiLane::Main), Some(format!("{TOKEN}:{DISTINCT_ID}")))]
#[tokio::test]
async fn ai_lane_overflow_routing_gated_on_valve(
    #[case] ai_events_overflow_enabled: bool,
    #[case] expected_ai_address: Address,
    #[case] expected_ai_key: Option<String>,
) {
    let (router, outputs) = setup_analytics_router(
        AiRouting::Secondary,
        ai_events_overflow_enabled,
        Some(force_keyed_limiter()),
        ai_events_overflow_enabled.then(force_keyed_limiter),
    );
    let client = TestClient::new(router);

    post_batch(&client, mixed_batch_payload()).await;

    let payloads = outputs.get_payloads();
    assert_eq!(payloads.len(), 2);

    let ai_event = find_payload(&payloads, "$ai_generation");
    assert_eq!(ai_event.address, expected_ai_address);
    assert_eq!(
        ai_event.key, expected_ai_key,
        "force-limited AI overflow must drop the partition key; the unarmed lane keeps it"
    );

    let pageview = find_payload(&payloads, "$pageview");
    assert_eq!(
        pageview.address,
        Address::Analytics(AnalyticsLane::Overflow),
        "the analytics lane must keep overflowing regardless of the AI valve"
    );
    assert_eq!(pageview.key, None, "ForceLimited overflow nulls the key");
}

/// The two lanes consult separate limiter instances end-to-end: a key that
/// the analytics limiter force-routes must not drag the same key's diverted
/// `$ai_*` event into AI overflow (and the pageview must still overflow).
/// Catches the router wiring one limiter instance into both slots.
#[tokio::test]
async fn ai_lane_overflow_isolated_from_analytics_limiter() {
    let clean_ai_limiter = Arc::new(OverflowLimiter::new(
        NonZeroU32::new(1_000).unwrap(),
        NonZeroU32::new(1_000).unwrap(),
        None,
        false, // preserve_locality
    ));

    let (router, outputs) = setup_analytics_router(
        AiRouting::Secondary,
        true, // valve armed
        Some(force_keyed_limiter()),
        Some(clean_ai_limiter),
    );
    let client = TestClient::new(router);

    post_batch(&client, mixed_batch_payload()).await;

    let payloads = outputs.get_payloads();
    assert_eq!(payloads.len(), 2);

    let ai_event = find_payload(&payloads, "$ai_generation");
    assert_eq!(
        ai_event.address,
        Address::Ai(AiLane::Main),
        "the analytics limiter's force-routed key must not route the AI lane to overflow"
    );

    let pageview = find_payload(&payloads, "$pageview");
    assert_eq!(
        pageview.address,
        Address::Analytics(AnalyticsLane::Overflow)
    );
}

/// Import mode's no-overflow guarantee, end-to-end on the legacy path. With the
/// deployment's real config — AI routing off — every event in a historical batch
/// lands on the historical lane, even with the overflow limiter force-keyed on
/// the batch's `token:distinct_id`. Nothing reaches the main or AI lanes (the
/// only overflowing lanes), so nothing can be routed to overflow, and the GRL
/// never runs. The invariant is emergent (historical_migration forces the
/// lane, AI routing off keeps AI events out of the AI lane), so it needs pinning:
/// arming AI routing here would divert `$ai_*` and break it.
#[tokio::test]
async fn import_mode_historical_batch_never_overflows() {
    let (router, outputs) = setup_router_for_mode(
        CaptureMode::Import,
        AiRouting::Primary, // matches capture-import: AI routing off
        false,
        Some(force_keyed_limiter()),
        None,
    );
    let client = TestClient::new(router);

    post_batch(&client, historical_mixed_batch_payload()).await;

    let payloads = outputs.get_payloads();
    assert_eq!(
        payloads.len(),
        2,
        "both historical events must reach the outputs"
    );

    for payload in &payloads {
        assert_eq!(
            payload.address,
            Address::Analytics(AnalyticsLane::Historical),
            "Import mode must route every event to the historical lane",
        );
    }
}
