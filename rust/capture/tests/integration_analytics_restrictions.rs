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
    assert!(
        events[0].metadata.redirect_to_dlq,
        "Event should have redirect_to_dlq flag set"
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
    assert!(
        events[0].metadata.force_overflow,
        "Event should have force_overflow flag set"
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
    assert!(
        events[0].metadata.skip_person_processing,
        "Event should have skip_person_processing flag set"
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
}
