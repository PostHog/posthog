#[path = "common/integration_utils.rs"]
mod integration_utils;

use async_trait::async_trait;
use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;
use capture::api::CaptureError;
use capture::config::CaptureMode;
use capture::event_restrictions::{
    EventRestrictionService, IngestionPipeline, Restriction, RestrictionManager, RestrictionScope,
    RestrictionType,
};
use capture::limiters::CaptureQuotaLimiter;
use capture::router::router;
use capture::sinks::Event;
use capture::time::TimeSource;
use capture::v0_request::ProcessedEvent;
use chrono::{DateTime, Utc};
use common_redis::MockRedisClient;
use health::HealthRegistry;
use integration_utils::{DEFAULT_CONFIG, DEFAULT_TEST_TIME};
use limiters::token_dropper::TokenDropper;
use serde_json::json;
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

async fn setup_analytics_router_with_restriction(
    restriction_type: RestrictionType,
    token: &str,
) -> (Router, CapturingSink) {
    let liveness = HealthRegistry::new("analytics_restriction_tests");
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

    let service =
        EventRestrictionService::new(IngestionPipeline::Analytics, Duration::from_secs(300));

    let mut manager = RestrictionManager::new();
    manager.restrictions.insert(
        token.to_string(),
        vec![Restriction {
            restriction_type,
            scope: RestrictionScope::AllEvents,
        }],
    );
    service.update(manager).await;

    let router = router(
        timesource,
        liveness,
        sink,
        redis,
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
        Some(10),
        None,
    );

    (router, sink_clone)
}

use capture::v0_request::DataType;
use serde_json::Value;

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
    // Properties to verify in the event data
    expected_properties: Option<Value>,
}

fn assert_event(event: &ProcessedEvent, expected: &ExpectedEvent) {
    // Assert CapturedEvent fields
    assert_eq!(event.event.token, expected.token, "token mismatch");
    assert_eq!(
        event.event.distinct_id, expected.distinct_id,
        "distinct_id mismatch"
    );
    assert_eq!(
        event.event.event, expected.event_name,
        "event name mismatch"
    );
    assert!(!event.event.ip.is_empty(), "ip should not be empty");
    assert!(!event.event.now.is_empty(), "now should not be empty");
    assert!(!event.event.data.is_empty(), "data should not be empty");

    // Assert ProcessedEventMetadata fields
    assert_eq!(
        event.metadata.data_type, expected.data_type,
        "data_type mismatch"
    );
    assert_eq!(
        event.metadata.event_name, expected.event_name,
        "metadata.event_name mismatch"
    );
    assert_eq!(
        event.metadata.force_overflow, expected.force_overflow,
        "force_overflow mismatch"
    );
    assert_eq!(
        event.metadata.skip_person_processing, expected.skip_person_processing,
        "skip_person_processing mismatch"
    );
    assert_eq!(
        event.metadata.redirect_to_dlq, expected.redirect_to_dlq,
        "redirect_to_dlq mismatch"
    );

    // Assert properties in event data
    if let Some(expected_props) = &expected.expected_properties {
        let data: Value =
            serde_json::from_str(&event.event.data).expect("event.data should be valid JSON");
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
            expected_properties: None,
        },
    );
}
