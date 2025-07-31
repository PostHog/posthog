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
    setup_router_with_limits(token, is_limited, false).await
}

async fn setup_survey_limited_router(token: &str, is_survey_limited: bool) -> (Router, MemorySink) {
    setup_router_with_limits(token, false, is_survey_limited).await
}

async fn setup_router_with_limits(token: &str, is_billing_limited: bool, is_survey_limited: bool) -> (Router, MemorySink) {
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

    // Set up survey limiter if requested
    let survey_limiter = if is_survey_limited {
        // Create a separate redis client for survey limiter
        let survey_key = format!("{}{}", QUOTA_LIMITER_CACHE_KEY, "surveys");
        let survey_redis = Arc::new(MockRedisClient::new().zrangebyscore_ret(&survey_key, vec![token.to_string()]));
        
        Some(RedisLimiter::new(
            Duration::from_secs(60),
            survey_redis,
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            None,
            QuotaResource::Surveys,
            ServiceName::Capture,
        ).unwrap())
    } else {
        None
    };

    let app = router(
        timesource,
        liveness,
        sink.clone(),
        redis,
        billing_limiter,
        survey_limiter,
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

// Test with /i/v0/e endpoint (handle_common)
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

    let events = ["survey sent", "pageview", "survey shown", "click", "$exception"];
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

    // Only non-survey events should be captured (pageview, click, $exception)
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 3);

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
    
    // Survey events should be filtered out
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

    // No events should be captured since all were survey events and got filtered
    let captured_events = sink.events();
    assert_eq!(captured_events.len(), 0);
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
    let (router, sink) = setup_router_with_limits(token, true, true).await; // Both billing and survey limited
    let client = TestClient::new(router);

    let events = ["$exception", "survey sent", "pageview", "survey shown", "click"];
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
