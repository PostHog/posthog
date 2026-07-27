#[path = "common/integration_utils.rs"]
mod integration_utils;

use async_trait::async_trait;
use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;
use capture::config::CaptureMode;
use capture::event_restrictions::{
    EventRestrictionService, Pipeline, Restriction, RestrictionManager, RestrictionScope,
    RestrictionType,
};
use capture::outputs::PrepSpec;
use capture::quota_limiters::CaptureQuotaLimiter;
use capture::router::router;
use capture::sinks::sink::{AddressedPayload, Sink, SinkResult};
use capture::time::TimeSource;
use capture::v0_request::DataType;
use chrono::{DateTime, Utc};
use common_redis::MockRedisClient;
use integration_utils::{test_lifecycle_handlers, DEFAULT_CONFIG, DEFAULT_TEST_TIME};
use limiters::token_dropper::TokenDropper;
use serde_json::{json, Value};
use std::sync::Arc;
use std::time::Duration;

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
    events: Arc<tokio::sync::Mutex<Vec<AddressedPayload>>>,
}

impl CapturingSink {
    fn new() -> Self {
        Self {
            events: Arc::new(tokio::sync::Mutex::new(Vec::new())),
        }
    }

    async fn get_events(&self) -> Vec<AddressedPayload> {
        self.events.lock().await.clone()
    }
}

#[async_trait]
impl Sink for CapturingSink {
    async fn publish(&self, prepared: Vec<AddressedPayload>) -> Vec<SinkResult> {
        let results = prepared.iter().map(|p| SinkResult::ok(p.uuid)).collect();
        self.events.lock().await.extend(prepared);
        results
    }
}

fn test_outputs(sink: &CapturingSink) -> Arc<capture::outputs::AnalyticsFamilyOutputs> {
    let row = || {
        capture::outputs::Output::single(
            Arc::new(sink.clone()),
            PrepSpec::from(&DEFAULT_CONFIG.kafka),
        )
    };
    Arc::new(capture::outputs::AnalyticsFamilyOutputs {
        analytics: row(),
        ai: row(),
        heatmaps: row(),
        warnings: row(),
        error_tracking: row(),
    })
}

async fn setup_analytics_router_with_restriction(
    restriction_type: RestrictionType,
    token: &str,
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

    let service = EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));

    let mut manager = RestrictionManager::new();
    manager.insert_restrictions(
        Pipeline::Analytics,
        token,
        vec![Restriction {
            restriction_type,
            scope: RestrictionScope::AllEvents,
            args: None,
        }],
    );
    service.update(manager).await;

    let router = router(
        timesource,
        readiness,
        liveness,
        test_outputs(&sink),
        redis,
        None, // global_rate_limiter_token_distinctid
        quota_limiter,
        TokenDropper::default(),
        Some(service),
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
        None,             // overflow_limiter
        None,             // replay_overflow_limiter
        None,             // v1_sink_router
        8,                // capture_v1_scatter_gather_min_batch
        None,             // ai_gateway_signing_secret
        None,             // ingestion_warning_emitter
    );

    (router, sink_clone)
}

struct ExpectedEvent<'a> {
    // CapturedEvent fields
    token: &'a str,
    distinct_id: &'a str,
    event_name: &'a str,
    // ProcessedEventMetadata fields
    data_type: DataType,
    force_overflow: bool,
    skip_person_processing: bool,
    redirect_to_dlq: bool,
    redirect_to_topic: Option<String>,
    // Properties to verify in the event data
    expected_properties: Option<Value>,
}

fn assert_event(payload: &AddressedPayload, expected: &ExpectedEvent) {
    // Assert event content by deserializing the payload back.
    let event: Value =
        serde_json::from_slice(&payload.payload).expect("payload should be valid JSON");
    assert_eq!(event["token"], expected.token, "token mismatch");
    assert_eq!(
        event["distinct_id"], expected.distinct_id,
        "distinct_id mismatch"
    );
    assert_eq!(event["event"], expected.event_name, "event name mismatch");
    assert!(
        !event["ip"].as_str().unwrap_or_default().is_empty(),
        "ip should not be empty"
    );
    assert!(
        !event["now"].as_str().unwrap_or_default().is_empty(),
        "now should not be empty"
    );
    let data_str = event["data"].as_str().expect("data should be a string");
    assert!(!data_str.is_empty(), "data should not be empty");

    // Assert the routing outcome the declarative expectations imply: the
    // record's topic and person-processing header carry what used to be
    // metadata stamps.
    use capture::pipeline::{Address, AiLane, AnalyticsLane, BasicLane, Pipeline as CapPipeline};
    let ai = expected.event_name.starts_with("$ai_");
    let expected_address = if expected.redirect_to_dlq {
        if ai {
            Address::Ai(AiLane::Dlq)
        } else {
            Address::Analytics(AnalyticsLane::Dlq)
        }
    } else if let Some(topic) = &expected.redirect_to_topic {
        Address::Custom {
            pipeline: if ai {
                CapPipeline::Ai
            } else {
                CapPipeline::Analytics
            },
            topic: topic.clone(),
        }
    } else if expected.force_overflow {
        if ai {
            Address::Ai(AiLane::Overflow)
        } else {
            Address::Analytics(AnalyticsLane::Overflow)
        }
    } else {
        match expected.data_type {
            DataType::AnalyticsMain | DataType::SnapshotMain => {
                if ai {
                    Address::Ai(AiLane::Main)
                } else {
                    Address::Analytics(AnalyticsLane::Main)
                }
            }
            DataType::AnalyticsHistorical => Address::Analytics(AnalyticsLane::Historical),
            DataType::HeatmapMain => Address::Heatmaps(BasicLane::Main),
            DataType::ClientIngestionWarning => Address::Warnings(BasicLane::Main),
            DataType::ExceptionErrorTracking => Address::ErrorTracking(BasicLane::Main),
        }
    };
    assert_eq!(payload.address, expected_address, "address mismatch");
    assert_eq!(
        payload.headers.force_disable_person_processing,
        if expected.skip_person_processing {
            Some(true)
        } else {
            None
        },
        "person-processing header mismatch"
    );

    // Assert properties in event data
    if let Some(expected_props) = &expected.expected_properties {
        let data: Value = serde_json::from_str(data_str).expect("event.data should be valid JSON");
        let actual_props = data
            .get("properties")
            .expect("event data should have properties");
        for (key, expected_value) in expected_props.as_object().unwrap() {
            let actual_value = actual_props.get(key).unwrap_or(&Value::Null);
            assert_eq!(actual_value, expected_value, "property '{key}' mismatch");
        }
    }
}

#[tokio::test]
async fn test_analytics_drop_event_restriction() {
    let restricted_token = "phc_restricted_drop_token";
    let (router, sink) =
        setup_analytics_router_with_restriction(RestrictionType::DropEvent, restricted_token).await;
    let test_client = TestClient::new(router);

    let payload = json!({
        "token": restricted_token,
        "event": "$pageview",
        "distinct_id": "test_user"
    });

    let response = test_client
        .post("/capture")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(payload.to_string())
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let events = sink.get_events().await;
    assert!(
        events.is_empty(),
        "Event should be dropped by restriction, but {} events were published",
        events.len()
    );
}

#[tokio::test]
async fn test_analytics_redirect_to_dlq_restriction() {
    let restricted_token = "phc_restricted_dlq_token";
    let (router, sink) =
        setup_analytics_router_with_restriction(RestrictionType::RedirectToDlq, restricted_token)
            .await;
    let test_client = TestClient::new(router);

    let payload = json!({
        "token": restricted_token,
        "event": "$pageview",
        "distinct_id": "test_user"
    });

    let response = test_client
        .post("/capture")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(payload.to_string())
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);
    assert_event(
        &events[0],
        &ExpectedEvent {
            token: restricted_token,
            distinct_id: "test_user",
            event_name: "$pageview",
            data_type: DataType::AnalyticsMain,
            force_overflow: false,
            skip_person_processing: false,
            redirect_to_dlq: true,
            redirect_to_topic: None,
            expected_properties: None,
        },
    );
}

#[tokio::test]
async fn test_analytics_force_overflow_restriction() {
    let restricted_token = "phc_restricted_overflow_token";
    let (router, sink) =
        setup_analytics_router_with_restriction(RestrictionType::ForceOverflow, restricted_token)
            .await;
    let test_client = TestClient::new(router);

    let payload = json!({
        "token": restricted_token,
        "event": "$pageview",
        "distinct_id": "test_user"
    });

    let response = test_client
        .post("/capture")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(payload.to_string())
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);
    assert_event(
        &events[0],
        &ExpectedEvent {
            token: restricted_token,
            distinct_id: "test_user",
            event_name: "$pageview",
            data_type: DataType::AnalyticsMain,
            force_overflow: true,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: None,
            expected_properties: None,
        },
    );
}

#[tokio::test]
async fn test_analytics_skip_person_processing_restriction() {
    let restricted_token = "phc_restricted_skip_person_token";
    let (router, sink) = setup_analytics_router_with_restriction(
        RestrictionType::SkipPersonProcessing,
        restricted_token,
    )
    .await;
    let test_client = TestClient::new(router);

    let payload = json!({
        "token": restricted_token,
        "event": "$pageview",
        "distinct_id": "test_user"
    });

    let response = test_client
        .post("/capture")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(payload.to_string())
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);
    assert_event(
        &events[0],
        &ExpectedEvent {
            token: restricted_token,
            distinct_id: "test_user",
            event_name: "$pageview",
            data_type: DataType::AnalyticsMain,
            force_overflow: false,
            skip_person_processing: true,
            redirect_to_dlq: false,
            redirect_to_topic: None,
            expected_properties: None,
        },
    );
}

#[tokio::test]
async fn test_analytics_restriction_does_not_apply_to_other_tokens() {
    let restricted_token = "phc_restricted_token";
    let (router, sink) =
        setup_analytics_router_with_restriction(RestrictionType::DropEvent, restricted_token).await;
    let test_client = TestClient::new(router);

    let payload = json!({
        "token": "phc_not_restricted_token",
        "event": "$pageview",
        "distinct_id": "test_user"
    });

    let response = test_client
        .post("/capture")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(payload.to_string())
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let events = sink.get_events().await;
    assert_eq!(
        events.len(),
        1,
        "Event should be published for non-restricted token"
    );
    assert_event(
        &events[0],
        &ExpectedEvent {
            token: "phc_not_restricted_token",
            distinct_id: "test_user",
            event_name: "$pageview",
            data_type: DataType::AnalyticsMain,
            force_overflow: false,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: None,
            expected_properties: None,
        },
    );
}

async fn setup_analytics_router_with_redirect_to_topic(
    token: &str,
    topic: &str,
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

    let service = EventRestrictionService::new(vec![Pipeline::Analytics], Duration::from_secs(300));

    let mut manager = RestrictionManager::new();
    manager.insert_restrictions(
        Pipeline::Analytics,
        token,
        vec![Restriction {
            restriction_type: RestrictionType::RedirectToTopic,
            scope: RestrictionScope::AllEvents,
            args: Some(json!({"topic": topic})),
        }],
    );
    service.update(manager).await;

    let router = router(
        timesource,
        readiness,
        liveness,
        test_outputs(&sink),
        redis,
        None, // global_rate_limiter_token_distinctid
        quota_limiter,
        TokenDropper::default(),
        Some(service),
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
        None,
        None,
        256,              // body_read_chunk_size_kb
        10 * 1024 * 1024, // capture_v1_max_compressed_body_bytes
        50 * 1024 * 1024, // capture_v1_max_decompressed_body_bytes
        None,             // overflow_limiter
        None,             // replay_overflow_limiter
        None,             // v1_sink_router
        8,                // capture_v1_scatter_gather_min_batch
        None,             // ai_gateway_signing_secret
        None,             // ingestion_warning_emitter
    );

    (router, sink_clone)
}

#[tokio::test]
async fn test_analytics_redirect_to_topic_restriction() {
    let restricted_token = "phc_restricted_redirect_topic_token";
    let target_topic = "custom_events_topic";
    let (router, sink) =
        setup_analytics_router_with_redirect_to_topic(restricted_token, target_topic).await;
    let test_client = TestClient::new(router);

    let payload = json!({
        "token": restricted_token,
        "event": "$pageview",
        "distinct_id": "test_user"
    });

    let response = test_client
        .post("/capture")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(payload.to_string())
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);
    assert_event(
        &events[0],
        &ExpectedEvent {
            token: restricted_token,
            distinct_id: "test_user",
            event_name: "$pageview",
            data_type: DataType::AnalyticsMain,
            force_overflow: false,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: Some(target_topic.to_string()),
            expected_properties: None,
        },
    );
}
