#[path = "common/integration_utils.rs"]
mod integration_utils;

use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;
use common_redis::MockRedisClient;
use health::HealthRegistry;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY};
use limiters::token_dropper::TokenDropper;
use serde_json::Value;

use capture::api::CaptureError;
use capture::config::CaptureMode;
use capture::router::router;
use capture::sinks::Event;
use capture::time::TimeSource;
use capture::v0_request::ProcessedEvent;

#[derive(Default, Clone)]
struct MemorySink {
    events: Arc<Mutex<Vec<ProcessedEvent>>>,
}

#[async_trait]
impl Event for MemorySink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.events.lock().unwrap().push(event);
        Ok(())
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.events.lock().unwrap().extend(events);
        Ok(())
    }
}

impl MemorySink {
    fn events(&self) -> Vec<ProcessedEvent> {
        self.events.lock().unwrap().clone()
    }
}

struct FixedTimeSource {
    time: String,
}

impl TimeSource for FixedTimeSource {
    fn current_time(&self) -> String {
        self.time.clone()
    }
}

async fn setup_billing_limited_router(token: &str, is_limited: bool) -> (Router, MemorySink) {
    setup_router_with_limits(token, is_limited, false, false).await
}

async fn setup_survey_limited_router(token: &str, is_survey_limited: bool) -> (Router, MemorySink) {
    setup_router_with_limits(token, false, is_survey_limited, false).await
}

async fn setup_router_with_limits(
    token: &str,
    is_billing_limited: bool,
    is_survey_limited: bool,
    is_ai_limited: bool,
) -> (Router, MemorySink) {
    let liveness = HealthRegistry::new("billing_limit_tests");
    let sink = MemorySink::default();
    let timesource = FixedTimeSource {
        time: "2025-07-31T12:00:00Z".to_string(),
    };

    // Set up billing limit for the specific token using zrangebyscore
    let billing_key = format!("{}{}", QUOTA_LIMITER_CACHE_KEY, "events");
    let redis = if is_billing_limited {
        Arc::new(MockRedisClient::new().zrangebyscore_ret(&billing_key, vec![token.to_string()]))
    } else {
        Arc::new(MockRedisClient::new())
    };

    let billing_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::Events,
        ServiceName::Capture,
    )
    .unwrap();

    // Set up survey limiter - always required now
    let survey_key = format!("{}{}", QUOTA_LIMITER_CACHE_KEY, "surveys");
    let survey_redis = Arc::new(MockRedisClient::new().zrangebyscore_ret(
        &survey_key,
        if is_survey_limited {
            vec![token.to_string()]
        } else {
            vec![]
        },
    ));

    let survey_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        survey_redis,
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::Surveys,
        ServiceName::Capture,
    )
    .unwrap();

    // Set up AI events limiter with its own Redis client
    let ai_key = format!("{}{}", QUOTA_LIMITER_CACHE_KEY, "llm_events");
    let ai_redis = Arc::new(MockRedisClient::new().zrangebyscore_ret(
        &ai_key,
        if is_ai_limited {
            vec![token.to_string()]
        } else {
            vec![]
        },
    ));

    let llm_events_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        ai_redis,
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::LLMEvents,
        ServiceName::Capture,
    )
    .unwrap();

    let app = router(
        timesource,
        liveness,
        sink.clone(),
        redis,
        billing_limiter,
        survey_limiter,
        llm_events_limiter,
        TokenDropper::default(),
        false, // metrics
        CaptureMode::Events,
        None,        // concurrency_limit
        1024 * 1024, // event_size_limit
        false,       // enable_historical_rerouting
        1,           // historical_rerouting_threshold_days
        None,        // historical_tokens_keys
        false,       // is_mirror_deploy
        0.0,         // verbose_sample_percent
    );

    (app, sink)
}

fn create_batch_payload_with_token(events: &[&str], token: &str) -> String {
    let events_json: Vec<serde_json::Value> = events
        .iter()
        .map(|event_name| {
            serde_json::json!({
                "event": event_name,
                "distinct_id": "test_user_id",
                "properties": {
                    "$lib": "web",
                    "$lib_version": "1.0.0"
                },
                "api_key": token
            })
        })
        .collect();

    if events_json.len() == 1 {
        events_json[0].to_string()
    } else {
        serde_json::json!({
            "batch": events_json,
            "api_key": token
        })
        .to_string()
    }
}

#[tokio::test]
async fn test_billing_limit_retains_exception_events() {
    let token = "test_token_exception";
    let (router, sink) = setup_billing_limited_router(token, true).await;
    let client = TestClient::new(router);

    let events = ["$exception", "pageview", "click"];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK even when billing limited (legacy behavior)
    assert_eq!(response.status(), StatusCode::OK);

    // Check that only exception events were retained
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1);

    // Parse the event data to check the event name
    let event_data: Value = serde_json::from_str(&captured_events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "$exception");
}

#[tokio::test]
async fn test_billing_limit_retains_survey_events() {
    let token = "test_token_survey";
    let (router, sink) = setup_billing_limited_router(token, true).await;
    let client = TestClient::new(router);

    let events = [
        "survey sent",
        "pageview",
        "survey shown",
        "click",
        "survey dismissed",
    ];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK even when billing limited (legacy behavior)
    assert_eq!(response.status(), StatusCode::OK);

    // Check that only survey events were retained
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 3);

    // Parse the event data to check the event names
    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    assert!(event_names.contains(&"survey sent".to_string()));
    assert!(event_names.contains(&"survey shown".to_string()));
    assert!(event_names.contains(&"survey dismissed".to_string()));
    // These should NOT be present
    assert!(!event_names.contains(&"pageview".to_string()));
    assert!(!event_names.contains(&"click".to_string()));
}

#[tokio::test]
async fn test_billing_limit_retains_both_exception_and_survey_events() {
    let token = "test_token_mixed";
    let (router, sink) = setup_billing_limited_router(token, true).await;
    let client = TestClient::new(router);

    let events = [
        "$exception",
        "pageview",
        "survey sent",
        "click",
        "survey shown",
    ];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK even when billing limited (legacy behavior)
    assert_eq!(response.status(), StatusCode::OK);

    // Check that exception and survey events were retained
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 3);

    // Parse the event data to check the event names
    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    assert!(event_names.contains(&"$exception".to_string()));
    assert!(event_names.contains(&"survey sent".to_string()));
    assert!(event_names.contains(&"survey shown".to_string()));
    // These should NOT be present
    assert!(!event_names.contains(&"pageview".to_string()));
    assert!(!event_names.contains(&"click".to_string()));
}

#[tokio::test]
async fn test_billing_limit_returns_ok_when_no_retained_events() {
    let token = "test_token_empty";
    let (router, sink) = setup_billing_limited_router(token, true).await;
    let client = TestClient::new(router);

    // Only regular events that should be filtered out
    let events = ["pageview", "click", "$pageview", "custom_event"];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK even when all events are filtered (legacy behavior)
    assert_eq!(response.status(), StatusCode::OK);

    // No events should be captured
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 0);
}

#[tokio::test]
async fn test_no_billing_limit_retains_all_events() {
    let token = "test_token_no_limit";
    let (router, sink) = setup_billing_limited_router(token, false).await; // Not limited
    let client = TestClient::new(router);

    let events = ["$exception", "pageview", "survey sent", "click"];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK when not billing limited
    assert_eq!(response.status(), StatusCode::OK);

    // All events should be retained when not billing limited
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 4);

    // Parse the event data to check all event names are present
    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    assert!(event_names.contains(&"$exception".to_string()));
    assert!(event_names.contains(&"pageview".to_string()));
    assert!(event_names.contains(&"survey sent".to_string()));
    assert!(event_names.contains(&"click".to_string()));
}

// Test with /i/v0/e endpoint
#[tokio::test]
async fn test_billing_limit_retains_survey_events_on_i_endpoint() {
    let token = "test_token_i_endpoint";
    let (router, sink) = setup_billing_limited_router(token, true).await;
    let client = TestClient::new(router);

    let events = ["survey sent", "pageview", "survey dismissed"];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/i/v0/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK even when billing limited
    assert_eq!(response.status(), StatusCode::OK);

    // Check that only survey events were retained
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 2);

    // Parse the event data to check the event names
    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    assert!(event_names.contains(&"survey sent".to_string()));
    assert!(event_names.contains(&"survey dismissed".to_string()));
    assert!(!event_names.contains(&"pageview".to_string()));
}

// Test with /i/v0/e endpoint for AI events
#[tokio::test]
async fn test_billing_limit_retains_ai_events_on_i_endpoint() {
    let token = "test_token_i_endpoint_ai";
    let (router, sink) = setup_billing_limited_router(token, true).await; // Only billing limited, not AI limited
    let client = TestClient::new(router);

    let events = [
        "$ai_generation",
        "pageview",
        "$ai_span",
        "click",
        "$ai_trace",
    ];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/i/v0/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK even when billing limited
    assert_eq!(response.status(), StatusCode::OK);

    // Check that only AI events were retained when billing limited
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 3); // Only AI events should be retained

    // Parse the event data to check the event names
    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    assert!(event_names.contains(&"$ai_generation".to_string()));
    assert!(event_names.contains(&"$ai_span".to_string()));
    assert!(event_names.contains(&"$ai_trace".to_string()));
    // Regular events should NOT be present when billing limited
    assert!(!event_names.contains(&"pageview".to_string()));
    assert!(!event_names.contains(&"click".to_string()));
}

// Tests for check_survey_quota_and_filter function
//
// These tests verify that the survey-specific quota limiting works correctly.
// Survey quota limiting is separate from billing limits:
// - Billing limits: When exceeded, only $exception and survey events are retained
// - Survey limits: When exceeded, only survey events are filtered out (other events pass through)
// Both can be applied simultaneously, with billing limits applied first, then survey limits
#[tokio::test]
async fn test_survey_quota_limit_filters_only_survey_events() {
    let token = "test_token_survey_quota";
    let (router, sink) = setup_survey_limited_router(token, true).await;
    let client = TestClient::new(router);

    let events = [
        "survey sent",
        "pageview",
        "survey shown",
        "click",
        "$exception",
    ];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK even when survey limited
    assert_eq!(response.status(), StatusCode::OK);

    // ALL survey events should be filtered out when quota exceeded, other events should be captured
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 3); // pageview, click, $exception

    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    // Non-survey events should be present
    assert!(event_names.contains(&"pageview".to_string()));
    assert!(event_names.contains(&"click".to_string()));
    assert!(event_names.contains(&"$exception".to_string()));

    // All survey events should be filtered out when quota exceeded
    assert!(!event_names.contains(&"survey sent".to_string()));
    assert!(!event_names.contains(&"survey shown".to_string()));
}

#[tokio::test]
async fn test_survey_quota_limit_returns_error_when_only_survey_events() {
    let token = "test_token_only_surveys";
    let (router, sink) = setup_survey_limited_router(token, true).await;
    let client = TestClient::new(router);

    // Only survey events in the payload
    let events = ["survey sent", "survey shown", "survey dismissed"];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK (legacy behavior - errors are converted to OK for v0 endpoints)
    assert_eq!(response.status(), StatusCode::OK);

    // When quota exceeded, ALL survey events should be filtered out
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 0);

    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    // All survey events should be filtered out when quota exceeded
    assert!(!event_names.contains(&"survey sent".to_string()));
    assert!(!event_names.contains(&"survey shown".to_string()));
    assert!(!event_names.contains(&"survey dismissed".to_string()));
}

#[tokio::test]
async fn test_survey_quota_limit_allows_survey_events_when_not_limited() {
    let token = "test_token_survey_not_limited";
    let (router, sink) = setup_survey_limited_router(token, false).await; // Not survey limited
    let client = TestClient::new(router);

    let events = ["survey sent", "pageview", "survey shown"];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK
    assert_eq!(response.status(), StatusCode::OK);

    // All events should be captured when not survey limited
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 3);

    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    assert!(event_names.contains(&"survey sent".to_string()));
    assert!(event_names.contains(&"pageview".to_string()));
    assert!(event_names.contains(&"survey shown".to_string()));
}

#[tokio::test]
async fn test_survey_quota_limit_ignores_non_survey_events() {
    let token = "test_token_survey_ignore_non_survey";
    let (router, sink) = setup_survey_limited_router(token, true).await;
    let client = TestClient::new(router);

    // No survey events in the payload
    let events = ["pageview", "click", "$exception", "custom_event"];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK
    assert_eq!(response.status(), StatusCode::OK);

    // All events should be captured since survey quota doesn't affect non-survey events
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 4);

    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    assert!(event_names.contains(&"pageview".to_string()));
    assert!(event_names.contains(&"click".to_string()));
    assert!(event_names.contains(&"$exception".to_string()));
    assert!(event_names.contains(&"custom_event".to_string()));
}

#[tokio::test]
async fn test_both_billing_and_survey_limits_applied() {
    let token = "test_token_both_limits";
    let (router, sink) = setup_router_with_limits(token, true, true, false).await; // Both billing and survey limited
    let client = TestClient::new(router);

    let events = [
        "$exception",
        "survey sent",
        "pageview",
        "survey shown",
        "click",
    ];
    let payload = create_batch_payload_with_token(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    // Should return OK
    assert_eq!(response.status(), StatusCode::OK);

    // First billing limit is applied (retains only $exception and survey events)
    // Then survey limit is applied (filters out survey events)
    // So only $exception should remain
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1);

    let event_data: Value = serde_json::from_str(&captured_events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "$exception");
}

// Helper function to create survey events with custom properties including $survey_submission_id
fn create_survey_events_with_submission_ids(
    events: &[(&str, Option<&str>)], // (event_name, submission_id)
    token: &str,
) -> String {
    let events_json: Vec<serde_json::Value> = events
        .iter()
        .map(|(event_name, submission_id)| {
            let mut properties = serde_json::json!({
                "$lib": "web",
                "$lib_version": "1.0.0"
            });

            // Add $survey_submission_id if provided
            if let Some(id) = submission_id {
                properties["$survey_submission_id"] = serde_json::Value::String(id.to_string());
            }

            serde_json::json!({
                "event": event_name,
                "distinct_id": "test_user_id",
                "properties": properties,
                "api_key": token
            })
        })
        .collect();

    if events_json.len() == 1 {
        events_json[0].to_string()
    } else {
        serde_json::json!({
            "batch": events_json,
            "api_key": token
        })
        .to_string()
    }
}

// Tests for enhanced survey quota logic with $survey_submission_id grouping
#[tokio::test]
async fn test_survey_quota_groups_events_by_submission_id() {
    let token = "test_token_submission_grouping";
    let (router, sink) = setup_survey_limited_router(token, true).await;
    let client = TestClient::new(router);

    // Create events with same submission_id - should be grouped together
    let events = [
        ("survey sent", Some("submission_123")),
        ("survey shown", Some("submission_123")),
        ("survey dismissed", Some("submission_123")),
        ("pageview", None), // Non-survey event
    ];
    let payload = create_survey_events_with_submission_ids(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // All survey events from submission_123 should be filtered out, only pageview should remain
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1);

    let event_data: Value = serde_json::from_str(&captured_events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "pageview");
}

#[tokio::test]
async fn test_survey_quota_handles_multiple_submission_groups() {
    let token = "test_token_multiple_submissions";
    let (router, sink) = setup_survey_limited_router(token, true).await;
    let client = TestClient::new(router);

    // Create events with different submission_ids - each group should be filtered separately
    let events = [
        ("survey sent", Some("submission_1")),
        ("survey shown", Some("submission_1")),
        ("survey sent", Some("submission_2")),
        ("survey dismissed", Some("submission_2")),
        ("click", None), // Non-survey event
    ];
    let payload = create_survey_events_with_submission_ids(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // All survey events should be filtered out, only the click event should remain
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1);

    let event_data: Value = serde_json::from_str(&captured_events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "click");
}

#[tokio::test]
async fn test_survey_quota_backward_compatibility_without_submission_id() {
    let token = "test_token_backward_compat";
    let (router, sink) = setup_survey_limited_router(token, true).await;
    let client = TestClient::new(router);

    // Create survey events without $survey_submission_id - should count individually
    let events = [
        ("survey sent", None),
        ("survey shown", None),
        ("pageview", None), // Non-survey event
    ];
    let payload = create_survey_events_with_submission_ids(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // When quota exceeded, ALL survey events should be filtered out, only pageview should remain
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1);

    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    // All survey events should be filtered out when quota exceeded
    assert!(!event_names.contains(&"survey sent".to_string()));
    assert!(!event_names.contains(&"survey shown".to_string()));

    // Non-survey events should be kept
    assert!(event_names.contains(&"pageview".to_string()));
}

#[tokio::test]
async fn test_survey_quota_mixed_with_and_without_submission_id() {
    let token = "test_token_mixed_submissions";
    let (router, sink) = setup_survey_limited_router(token, true).await;
    let client = TestClient::new(router);

    // Mix of events with and without submission_id
    let events = [
        ("survey sent", Some("submission_456")),
        ("survey shown", Some("submission_456")),
        ("survey dismissed", None), // No submission_id - backward compatibility
        ("survey sent", None),      // No submission_id - backward compatibility
        ("custom_event", None),     // Non-survey event
    ];
    let payload = create_survey_events_with_submission_ids(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // All survey events should be filtered out, only custom_event should remain
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1);

    let event_data: Value = serde_json::from_str(&captured_events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "custom_event");
}

#[tokio::test]
async fn test_survey_quota_empty_submission_id_treated_as_none() {
    let token = "test_token_empty_submission";
    let (router, sink) = setup_survey_limited_router(token, true).await;
    let client = TestClient::new(router);

    // Create events with empty string submission_id - should be treated as None
    let events_json: Vec<serde_json::Value> = vec![
        serde_json::json!({
            "event": "survey sent",
            "distinct_id": "test_user_id",
            "properties": {
                "$lib": "web",
                "$lib_version": "1.0.0",
                "$survey_submission_id": "" // Empty string should be treated as None
            },
            "api_key": token
        }),
        serde_json::json!({
            "event": "pageview",
            "distinct_id": "test_user_id",
            "properties": {
                "$lib": "web",
                "$lib_version": "1.0.0"
            },
            "api_key": token
        }),
    ];

    let payload = serde_json::json!({
        "batch": events_json,
        "api_key": token
    })
    .to_string();

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // Survey event with empty submission_id should be filtered out, only pageview should remain
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1);

    let event_data: Value = serde_json::from_str(&captured_events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "pageview");
}

#[tokio::test]
async fn test_survey_quota_allows_events_when_not_limited() {
    let token = "test_token_not_survey_limited";
    let (router, sink) = setup_survey_limited_router(token, false).await; // Not survey limited
    let client = TestClient::new(router);

    // Create events with submission_ids - should all pass through when not limited
    let events = [
        ("survey sent", Some("submission_789")),
        ("survey shown", Some("submission_789")),
        ("survey dismissed", None),
        ("pageview", None),
    ];
    let payload = create_survey_events_with_submission_ids(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // All events should be captured when not survey limited
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 4);

    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    assert!(event_names.contains(&"survey sent".to_string()));
    assert!(event_names.contains(&"survey shown".to_string()));
    assert!(event_names.contains(&"survey dismissed".to_string()));
    assert!(event_names.contains(&"pageview".to_string()));
}

// Tests for cross-batch survey submission tracking
#[tokio::test]
async fn test_survey_quota_cross_batch_first_submission_allowed() {
    let token = "test_token_cross_batch_first";
    let liveness = HealthRegistry::new("billing_limit_tests");
    let sink = MemorySink::default();
    let timesource = FixedTimeSource {
        time: "2025-07-31T12:00:00Z".to_string(),
    };

    // Configure MockRedisClient for survey quota limited scenario
    let survey_key = format!("{}{}", QUOTA_LIMITER_CACHE_KEY, "surveys");
    let mut redis_client =
        MockRedisClient::new().zrangebyscore_ret(&survey_key, vec![token.to_string()]);

    // Configure set_nx_ex to return true (key was set successfully, first time seeing this submission)
    let submission_key = format!("survey-submission:{token}:submission_first");
    redis_client = redis_client.set_nx_ex_ret(&submission_key, Ok(true));

    let redis = Arc::new(redis_client);

    let billing_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::Events,
        ServiceName::Capture,
    )
    .unwrap();

    let survey_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::Surveys,
        ServiceName::Capture,
    )
    .unwrap();

    let llm_events_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::LLMEvents,
        ServiceName::Capture,
    )
    .unwrap();
    let app = router(
        timesource,
        liveness,
        sink.clone(),
        redis,
        billing_limiter,
        survey_limiter,
        llm_events_limiter,
        TokenDropper::default(),
        false,
        CaptureMode::Events,
        None,
        1024 * 1024,
        false,
        1,
        None,
        false,
        0.0,
    );

    let client = TestClient::new(app);

    // First batch with survey events from submission_first
    let events = [
        ("survey sent", Some("submission_first")),
        ("survey shown", Some("submission_first")),
        ("pageview", None),
    ];
    let payload = create_survey_events_with_submission_ids(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // Since this is the first time seeing submission_first, survey events should be allowed through
    // but then dropped by the main quota system since we're survey limited
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1); // Only pageview should remain

    let event_data: Value = serde_json::from_str(&captured_events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "pageview");
}

#[tokio::test]
async fn test_survey_quota_cross_batch_duplicate_submission_dropped() {
    let token = "test_token_cross_batch_dup";
    let liveness = HealthRegistry::new("billing_limit_tests");
    let sink = MemorySink::default();
    let timesource = FixedTimeSource {
        time: "2025-07-31T12:00:00Z".to_string(),
    };

    // Configure MockRedisClient for survey quota limited scenario
    let survey_key = format!("{}{}", QUOTA_LIMITER_CACHE_KEY, "surveys");
    let mut redis_client =
        MockRedisClient::new().zrangebyscore_ret(&survey_key, vec![token.to_string()]);

    // Configure set_nx_ex to return false (key already exists, submission already processed)
    let submission_key = format!("survey-submission:{token}:submission_duplicate");
    redis_client = redis_client.set_nx_ex_ret(&submission_key, Ok(false));

    let redis = Arc::new(redis_client);

    let billing_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::Events,
        ServiceName::Capture,
    )
    .unwrap();

    let survey_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::Surveys,
        ServiceName::Capture,
    )
    .unwrap();

    let llm_events_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::LLMEvents,
        ServiceName::Capture,
    )
    .unwrap();
    let app = router(
        timesource,
        liveness,
        sink.clone(),
        redis,
        billing_limiter,
        survey_limiter,
        llm_events_limiter,
        TokenDropper::default(),
        false,
        CaptureMode::Events,
        None,
        1024 * 1024,
        false,
        1,
        None,
        false,
        0.0,
    );

    let client = TestClient::new(app);

    // Second batch with same submission_duplicate - should be dropped completely
    let events = [
        ("survey sent", Some("submission_duplicate")),
        ("survey dismissed", Some("submission_duplicate")),
        ("click", None),
    ];
    let payload = create_survey_events_with_submission_ids(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // Survey events from duplicate submission should be dropped, only click should remain
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1);

    let event_data: Value = serde_json::from_str(&captured_events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "click");
}

#[tokio::test]
async fn test_survey_quota_cross_batch_redis_error_fail_open() {
    let token = "test_token_redis_error";
    let liveness = HealthRegistry::new("billing_limit_tests");
    let sink = MemorySink::default();
    let timesource = FixedTimeSource {
        time: "2025-07-31T12:00:00Z".to_string(),
    };

    // Configure MockRedisClient for survey quota limited scenario
    let survey_key = format!("{}{}", QUOTA_LIMITER_CACHE_KEY, "surveys");
    let mut redis_client =
        MockRedisClient::new().zrangebyscore_ret(&survey_key, vec![token.to_string()]);

    // Configure set_nx_ex to return an error (Redis failure)
    let submission_key = format!("survey-submission:{token}:submission_error");
    redis_client = redis_client.set_nx_ex_ret(
        &submission_key,
        Err(common_redis::CustomRedisError::Timeout),
    );

    let redis = Arc::new(redis_client);

    let billing_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::Events,
        ServiceName::Capture,
    )
    .unwrap();

    let survey_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::Surveys,
        ServiceName::Capture,
    )
    .unwrap();

    let llm_events_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::LLMEvents,
        ServiceName::Capture,
    )
    .unwrap();
    let app = router(
        timesource,
        liveness,
        sink.clone(),
        redis,
        billing_limiter,
        survey_limiter,
        llm_events_limiter,
        TokenDropper::default(),
        false,
        CaptureMode::Events,
        None,
        1024 * 1024,
        false,
        1,
        None,
        false,
        0.0,
    );

    let client = TestClient::new(app);

    // Events with submission that causes Redis error - should fail open (allow events through)
    let events = [
        ("survey sent", Some("submission_error")),
        ("pageview", None),
    ];
    let payload = create_survey_events_with_submission_ids(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // Redis error should fail open - survey events should be allowed through
    // but then dropped by main quota system, only pageview remains
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1);

    let event_data: Value = serde_json::from_str(&captured_events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "pageview");
}

#[tokio::test]
async fn test_survey_quota_only_limits_survey_sent_events() {
    let token = "test_token_only_survey_sent";
    let (router, sink) = setup_survey_limited_router(token, true).await;
    let client = TestClient::new(router);

    // Mix of all survey event types - when quota exceeded, ALL survey events should be dropped
    let events = [
        ("survey sent", Some("submission_123")), // This should be dropped due to quota
        ("survey shown", Some("submission_123")), // This should also be dropped when quota exceeded
        ("survey dismissed", Some("submission_123")), // This should also be dropped when quota exceeded
        ("pageview", None),                           // Non-survey event
    ];
    let payload = create_survey_events_with_submission_ids(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // When survey quota is exceeded, ALL survey events should be dropped
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1); // only pageview

    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    // All survey events should be dropped when quota exceeded
    assert!(!event_names.contains(&"survey sent".to_string()));
    assert!(!event_names.contains(&"survey shown".to_string()));
    assert!(!event_names.contains(&"survey dismissed".to_string()));

    // Non-survey events should be kept
    assert!(event_names.contains(&"pageview".to_string()));
}

#[tokio::test]
async fn test_survey_quota_backward_compatibility_survey_sent_only() {
    let token = "test_token_survey_sent_backward_compat";
    let (router, sink) = setup_survey_limited_router(token, true).await;
    let client = TestClient::new(router);

    // Survey events without submission_id - when quota exceeded, ALL survey events should be dropped
    let events = [
        ("survey sent", None),      // Should be dropped due to quota (no submission_id)
        ("survey shown", None),     // Should also be dropped when quota exceeded
        ("survey dismissed", None), // Should also be dropped when quota exceeded
        ("pageview", None),         // Non-survey event
    ];
    let payload = create_survey_events_with_submission_ids(&events, token);

    let response = client
        .post("/e")
        .body(payload)
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;

    assert_eq!(response.status(), StatusCode::OK);

    // When quota exceeded, ALL survey events should be dropped
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 1);

    let event_names: Vec<String> = captured_events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();

    // All survey events should be dropped when quota exceeded
    assert!(!event_names.contains(&"survey sent".to_string()));
    assert!(!event_names.contains(&"survey shown".to_string()));
    assert!(!event_names.contains(&"survey dismissed".to_string()));

    // Non-survey events should be kept
    assert!(event_names.contains(&"pageview".to_string()));
}

#[tokio::test]
async fn test_ai_events_quota_limit_filters_only_ai_events() {
    let token = "test_token";
    let (app, sink) = setup_ai_limited_router(token, true).await;
    let client = TestClient::new(app);

    let ai_event = serde_json::json!({
        "api_key": token,
        "batch": [
            {
                "event": "$ai_generation",
                "properties": {
                    "distinct_id": "ai_user",
                    "$ai_model": "gpt-4",
                    "$ai_provider": "openai"
                }
            },
            {"event": "$ai_span", "properties": {"distinct_id": "ai_user"}},
            {"event": "$ai_trace", "properties": {"distinct_id": "ai_user"}},
            {"event": "pageview", "properties": {"distinct_id": "regular_user"}},
            {"event": "custom_event", "properties": {"distinct_id": "regular_user"}}
        ]
    });

    let res = client
        .post("/e")
        .body(ai_event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    let events = sink.events();
    assert_eq!(events.len(), 2); // Only non-AI events should be kept

    // Verify only non-AI events were kept
    let event_names: Vec<String> = events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();
    assert!(event_names.contains(&"pageview".to_string()));
    assert!(event_names.contains(&"custom_event".to_string()));
    assert!(!event_names.contains(&"$ai_generation".to_string()));
    assert!(!event_names.contains(&"$ai_span".to_string()));
    assert!(!event_names.contains(&"$ai_trace".to_string()));
}

#[tokio::test]
async fn test_ai_events_quota_limit_returns_error_when_only_ai_events() {
    let token = "test_token";
    let (app, _) = setup_ai_limited_router(token, true).await;
    let client = TestClient::new(app);

    let ai_only_event = serde_json::json!({
        "api_key": token,
        "batch": [
            {"event": "$ai_generation", "properties": {"distinct_id": "ai_user"}},
            {"event": "$ai_completion", "properties": {"distinct_id": "ai_user"}},
            {"event": "$ai_custom_metric", "properties": {"distinct_id": "ai_user"}}
        ]
    });

    let res = client
        .post("/e")
        .body(ai_only_event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);
}

#[tokio::test]
async fn test_ai_events_quota_allows_ai_events_when_not_limited() {
    let token = "test_token";
    let (app, sink) = setup_ai_limited_router(token, false).await;
    let client = TestClient::new(app);

    let ai_event = serde_json::json!({
        "api_key": token,
        "batch": [
            {"event": "$ai_generation", "properties": {"distinct_id": "ai_user"}},
            {"event": "$ai_span", "properties": {"distinct_id": "ai_user"}},
            {"event": "pageview", "properties": {"distinct_id": "regular_user"}}
        ]
    });

    let res = client
        .post("/e")
        .body(ai_event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    let events = sink.events();
    assert_eq!(events.len(), 3); // All events should be kept when not limited

    let event_names: Vec<String> = events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();
    assert!(event_names.contains(&"$ai_generation".to_string()));
    assert!(event_names.contains(&"$ai_span".to_string()));
    assert!(event_names.contains(&"pageview".to_string()));
}

#[tokio::test]
async fn test_ai_events_quota_ignores_non_ai_events() {
    let token = "test_token";
    let (app, sink) = setup_ai_limited_router(token, true).await;
    let client = TestClient::new(app);

    // Send only non-AI events when AI quota is exceeded
    let non_ai_event = serde_json::json!({
        "api_key": token,
        "batch": [
            {"event": "pageview", "properties": {"distinct_id": "user1"}},
            {"event": "$autocapture", "properties": {"distinct_id": "user2"}},
            {"event": "custom_event", "properties": {"distinct_id": "user3"}}
        ]
    });

    let res = client
        .post("/e")
        .body(non_ai_event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    let events = sink.events();
    assert_eq!(events.len(), 3); // All non-AI events should pass through
}

// Helper function to set up router with AI limiting
async fn setup_ai_limited_router(token: &str, is_ai_limited: bool) -> (Router, MemorySink) {
    setup_router_with_limits(token, false, false, is_ai_limited).await
}

#[tokio::test]
async fn test_both_billing_and_ai_limits_applied() {
    let token = "test_token";
    let (app, sink) = setup_router_with_limits(token, true, false, true).await;
    let client = TestClient::new(app);

    let mixed_event = serde_json::json!({
        "api_key": token,
        "batch": [
            {"event": "$ai_generation", "properties": {"distinct_id": "ai_user"}},
            {"event": "$exception", "properties": {"distinct_id": "error_user"}},
            {"event": "pageview", "properties": {"distinct_id": "regular_user"}}
        ]
    });

    let res = client
        .post("/e")
        .body(mixed_event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    let events = sink.events();
    assert_eq!(events.len(), 1); // Only exception should remain

    let event_names: Vec<String> = events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();
    assert!(event_names.contains(&"$exception".to_string()));
    assert!(!event_names.contains(&"$ai_generation".to_string()));
    assert!(!event_names.contains(&"pageview".to_string()));
}

#[tokio::test]
async fn test_ai_and_survey_limits_interaction() {
    let token = "test_token";
    let (app, sink) = setup_router_with_limits(token, false, true, true).await;
    let client = TestClient::new(app);

    let mixed_event = serde_json::json!({
        "api_key": token,
        "batch": [
            {"event": "$ai_generation", "properties": {"distinct_id": "ai_user"}},
            {"event": "survey sent", "properties": {"distinct_id": "survey_user", "$survey_id": "123"}},
            {"event": "pageview", "properties": {"distinct_id": "regular_user"}},
            {"event": "custom_event", "properties": {"distinct_id": "regular_user"}}
        ]
    });

    let res = client
        .post("/e")
        .body(mixed_event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    let status = res.status();

    assert_eq!(status, StatusCode::OK);

    let events = sink.events();
    assert_eq!(events.len(), 2); // Only regular events should remain

    let event_names: Vec<String> = events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();
    assert!(event_names.contains(&"pageview".to_string()));
    assert!(event_names.contains(&"custom_event".to_string()));
    assert!(!event_names.contains(&"$ai_generation".to_string()));
    assert!(!event_names.contains(&"survey sent".to_string()));
}

#[tokio::test]
async fn test_all_three_limits_applied() {
    let token = "test_token";
    let (app, sink) = setup_router_with_limits(token, true, true, true).await;
    let client = TestClient::new(app);

    let mixed_event = serde_json::json!({
        "api_key": token,
        "batch": [
            {"event": "$ai_generation", "properties": {"distinct_id": "ai_user"}},
            {"event": "survey sent", "properties": {"distinct_id": "survey_user"}},
            {"event": "$exception", "properties": {"distinct_id": "error_user"}},
            {"event": "pageview", "properties": {"distinct_id": "regular_user"}}
        ]
    });

    let res = client
        .post("/e")
        .body(mixed_event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    let events = sink.events();
    assert_eq!(events.len(), 1); // Only exception should remain

    let event_names: Vec<String> = events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();
    assert!(event_names.contains(&"$exception".to_string()));
    assert!(!event_names.contains(&"$ai_generation".to_string()));
    assert!(!event_names.contains(&"survey sent".to_string()));
    assert!(!event_names.contains(&"pageview".to_string()));
}

#[tokio::test]
async fn test_ai_event_name_detection() {
    // Test various event names to ensure is_ai_event() works correctly
    let test_cases = vec![
        ("$ai_generation", true),
        ("$ai_completion", true),
        ("$ai_span", true),
        ("$ai_trace", true),
        ("$ai_custom", true),
        ("$ai_", true),           // Edge case: exactly "$ai_"
        ("$ai", false),           // No underscore
        ("$ainotthis", false),    // No underscore after ai
        ("ai_generation", false), // Missing $
        ("$pageview", false),
        ("pageview", false),
    ];

    let token = "test_token";

    for (event_name, should_be_filtered) in test_cases {
        let (app, sink) = setup_ai_limited_router(token, true).await;
        let client = TestClient::new(app);

        let event = serde_json::json!({
            "api_key": token,
            "batch": [
                {"event": event_name, "properties": {"distinct_id": "user"}},
                {"event": "pageview", "properties": {"distinct_id": "user"}}  // Control event
            ]
        });

        let res = client
            .post("/e")
            .body(event.to_string())
            .header("Content-Type", "application/json")
            .header("X-Forwarded-For", "127.0.0.1")
            .send()
            .await;
        assert_eq!(res.status(), StatusCode::OK);

        let events = sink.events();

        if should_be_filtered {
            // AI event should be filtered, only pageview remains
            assert_eq!(events.len(), 1, "Event '{event_name}' should be filtered");
            let event_data: Value = serde_json::from_str(&events[0].event.data).unwrap();
            assert_eq!(event_data["event"], "pageview");
        } else {
            // Non-AI event should pass through with pageview
            assert_eq!(
                events.len(),
                2,
                "Event '{event_name}' should not be filtered"
            );
        }
    }
}

#[tokio::test]
async fn test_ai_generation_event_limited() {
    let token = "test_token";
    let (app, sink) = setup_ai_limited_router(token, true).await;
    let client = TestClient::new(app);

    let event = serde_json::json!({
        "api_key": token,
        "batch": [
            {
                "event": "$ai_generation",
                "properties": {
                    "distinct_id": "user",
                    "$ai_model": "gpt-4",
                    "$ai_provider": "openai",
                    "$ai_input_tokens": 100,
                    "$ai_output_tokens": 200
                }
            }
        ]
    });

    let res = client
        .post("/i/v0/e")
        .body(event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK); // Returns OK even when all events are filtered (legacy behavior)

    let events = sink.events();
    assert_eq!(events.len(), 0); // AI event should be filtered
}

#[tokio::test]
async fn test_ai_span_event_limited() {
    let token = "test_token";
    let (app, sink) = setup_ai_limited_router(token, true).await;
    let client = TestClient::new(app);

    let event = serde_json::json!({
        "api_key": token,
        "batch": [
            {
                "event": "$ai_span",
                "properties": {
                    "distinct_id": "user",
                    "$ai_trace_id": "trace_123",
                    "$ai_span_id": "span_456"
                }
            },
            {"event": "custom", "properties": {"distinct_id": "user"}}
        ]
    });

    let res = client
        .post("/i/v0/e")
        .body(event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    let events = sink.events();
    assert_eq!(events.len(), 1);
    let event_data: Value = serde_json::from_str(&events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "custom");
}

#[tokio::test]
async fn test_ai_trace_event_limited() {
    let token = "test_token";
    let (app, sink) = setup_ai_limited_router(token, true).await;
    let client = TestClient::new(app);

    let event = serde_json::json!({
        "api_key": token,
        "batch": [
            {
                "event": "$ai_trace",
                "properties": {
                    "distinct_id": "user",
                    "$ai_trace_id": "trace_789"
                }
            },
            {"event": "$autocapture", "properties": {"distinct_id": "user"}}
        ]
    });

    let res = client
        .post("/i/v0/e")
        .body(event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    let events = sink.events();
    assert_eq!(events.len(), 1);
    let event_data: Value = serde_json::from_str(&events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "$autocapture");
}

#[tokio::test]
async fn test_custom_ai_prefixed_events_limited() {
    let token = "test_token";
    let (app, sink) = setup_ai_limited_router(token, true).await;
    let client = TestClient::new(app);

    // Custom AI events that follow the $ai_ pattern should also be limited
    let event = serde_json::json!({
        "api_key": token,
        "batch": [
            {"event": "$ai_custom_metric", "properties": {"distinct_id": "user"}},
            {"event": "$ai_user_feedback", "properties": {"distinct_id": "user"}},
            {"event": "$ai_model_switch", "properties": {"distinct_id": "user"}},
            {"event": "non_ai_event", "properties": {"distinct_id": "user"}}
        ]
    });

    let res = client
        .post("/i/v0/e")
        .body(event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    let events = sink.events();
    assert_eq!(events.len(), 1); // Only non-AI event should pass
    let event_data: Value = serde_json::from_str(&events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "non_ai_event");
}

#[tokio::test]
async fn test_ai_quota_with_empty_batch() {
    let token = "test_token";
    let (app, _sink) = setup_ai_limited_router(token, true).await;
    let client = TestClient::new(app);

    let empty_event = serde_json::json!({
        "api_key": token,
        "batch": []
    });

    let res = client
        .post("/e")
        .body(empty_event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::BAD_REQUEST); // Empty batch is invalid
}

#[tokio::test]
async fn test_ai_quota_cross_batch_redis_error_fail_open() {
    let token = "test_token_redis_error_ai";
    let liveness = HealthRegistry::new("ai_limit_tests");
    let sink = MemorySink::default();
    let timesource = FixedTimeSource {
        time: "2025-07-31T12:00:00Z".to_string(),
    };

    // Configure MockRedisClient for AI quota limited scenario
    let ai_key = format!("{}{}", QUOTA_LIMITER_CACHE_KEY, "llm_events");
    let mut redis_client =
        MockRedisClient::new().zrangebyscore_ret(&ai_key, vec![token.to_string()]);

    // Configure set_nx_ex to return an error (Redis failure) for cross-batch tracking
    let tracking_key = format!("ai-events:{token}:batch_1");
    redis_client =
        redis_client.set_nx_ex_ret(&tracking_key, Err(common_redis::CustomRedisError::Timeout));

    let redis = Arc::new(redis_client);

    let billing_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::Events,
        ServiceName::Capture,
    )
    .unwrap();

    let survey_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::Surveys,
        ServiceName::Capture,
    )
    .unwrap();

    let llm_events_limiter = RedisLimiter::new(
        Duration::from_secs(60),
        redis.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
        QuotaResource::LLMEvents,
        ServiceName::Capture,
    )
    .unwrap();

    let app = router(
        timesource,
        liveness,
        sink.clone(),
        redis,
        billing_limiter,
        survey_limiter,
        llm_events_limiter,
        TokenDropper::default(),
        false,
        CaptureMode::Events,
        None,
        1024 * 1024,
        false,
        1,
        None,
        false,
        0.0,
    );

    let client = TestClient::new(app);

    // Events with Redis error - should fail open (allow events through but apply quota)
    let ai_event = serde_json::json!({
        "api_key": token,
        "batch": [
            {"event": "$ai_generation", "properties": {"distinct_id": "ai_user", "batch_id": "batch_1"}},
            {"event": "pageview", "properties": {"distinct_id": "regular_user"}},
        ]
    });

    let res = client
        .post("/e")
        .body(ai_event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    // Redis error should fail open - but AI quota limit still applies
    // So AI event should be dropped, only pageview remains
    let events = sink.events();
    assert_eq!(events.len(), 1);
    let event_data: Value = serde_json::from_str(&events[0].event.data).unwrap();
    assert_eq!(event_data["event"], "pageview");
}

#[tokio::test]
async fn test_ai_quota_cross_batch_consistency() {
    let token = "test_token_cross_batch_ai";
    let (app, sink) = setup_ai_limited_router(token, true).await;
    let client = TestClient::new(app);

    // First batch - AI events should be filtered
    let first_batch = serde_json::json!({
        "api_key": token,
        "batch": [
            {"event": "$ai_generation", "properties": {"distinct_id": "ai_user_1"}},
            {"event": "pageview", "properties": {"distinct_id": "user_1"}},
        ]
    });

    let res = client
        .post("/e")
        .body(first_batch.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    // Second batch - AI events should still be filtered consistently
    let second_batch = serde_json::json!({
        "api_key": token,
        "batch": [
            {"event": "$ai_span", "properties": {"distinct_id": "ai_user_2"}},
            {"event": "click", "properties": {"distinct_id": "user_2"}},
        ]
    });

    let res = client
        .post("/e")
        .body(second_batch.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    // Both batches should have AI events filtered out consistently
    let events = sink.events();
    assert_eq!(events.len(), 2); // Only non-AI events

    let event_names: Vec<String> = events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();
    assert!(event_names.contains(&"pageview".to_string()));
    assert!(event_names.contains(&"click".to_string()));
    assert!(!event_names.contains(&"$ai_generation".to_string()));
    assert!(!event_names.contains(&"$ai_span".to_string()));
}

#[tokio::test]
async fn test_ai_quota_all_ai_event_types_count() {
    let token = "test_token_all_types";
    let (app, sink) = setup_ai_limited_router(token, true).await;
    let client = TestClient::new(app);

    // Test that ALL events starting with "$ai_" count toward quota
    let ai_event = serde_json::json!({
        "api_key": token,
        "batch": [
            {"event": "$ai_generation", "properties": {"distinct_id": "user1"}},
            {"event": "$ai_completion", "properties": {"distinct_id": "user2"}},
            {"event": "$ai_span", "properties": {"distinct_id": "user3"}},
            {"event": "$ai_trace", "properties": {"distinct_id": "user4"}},
            {"event": "$ai_custom_metric", "properties": {"distinct_id": "user5"}},
            {"event": "$ai_anything", "properties": {"distinct_id": "user6"}},
            {"event": "$ainotcounted", "properties": {"distinct_id": "user7"}},  // No underscore
            {"event": "ai_generation", "properties": {"distinct_id": "user8"}},  // No $
            {"event": "pageview", "properties": {"distinct_id": "user9"}},
        ]
    });

    let res = client
        .post("/e")
        .body(ai_event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    let events = sink.events();
    // Only non-AI events should pass: $ainotcounted, ai_generation, pageview
    assert_eq!(events.len(), 3);

    let event_names: Vec<String> = events
        .iter()
        .map(|e| {
            let event_data: Value = serde_json::from_str(&e.event.data).unwrap();
            event_data["event"].as_str().unwrap().to_string()
        })
        .collect();
    assert!(event_names.contains(&"$ainotcounted".to_string())); // No underscore after $ai
    assert!(event_names.contains(&"ai_generation".to_string())); // No $ prefix
    assert!(event_names.contains(&"pageview".to_string()));

    // All proper $ai_ events should be filtered
    assert!(!event_names.contains(&"$ai_generation".to_string()));
    assert!(!event_names.contains(&"$ai_completion".to_string()));
    assert!(!event_names.contains(&"$ai_span".to_string()));
    assert!(!event_names.contains(&"$ai_trace".to_string()));
    assert!(!event_names.contains(&"$ai_custom_metric".to_string()));
    assert!(!event_names.contains(&"$ai_anything".to_string()));
}

#[tokio::test]
async fn test_ai_quota_empty_null_field_handling() {
    let token = "test_token_empty_fields_ai";
    let (app, _sink) = setup_ai_limited_router(token, true).await;
    let client = TestClient::new(app);

    // Test various empty/null scenarios
    let ai_event = serde_json::json!({
        "api_key": token,
        "batch": [
            // AI event with empty string event name (should be handled gracefully)
            {"event": "", "properties": {"distinct_id": "user1"}},
            // AI event with whitespace event name
            {"event": "  ", "properties": {"distinct_id": "user2"}},
            // Proper AI event
            {"event": "$ai_generation", "properties": {"distinct_id": "user3"}},
            // Event with null (will be handled by JSON parsing)
            {"event": null, "properties": {"distinct_id": "user4"}},
            // Regular event
            {"event": "pageview", "properties": {"distinct_id": "user5"}},
        ]
    });

    let res = client
        .post("/e")
        .body(ai_event.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await;
    // Invalid event names (null, empty) should return BAD_REQUEST
    assert_eq!(res.status(), StatusCode::BAD_REQUEST);
}
