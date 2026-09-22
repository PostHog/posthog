#[path = "common/integration_utils.rs"]
mod integration_utils;

use async_trait::async_trait;
use axum::http::StatusCode;
use axum_test_helper::TestClient;
use capture::api::CaptureError;
use capture::config::CaptureMode;
use capture::known_tokens::{KnownTokenChecker, TokenValidationMode};
use capture::outputs::{OutputRegistry, PublishEvents};
use capture::quota_limiters::CaptureQuotaLimiter;
use capture::router::{router, BATCH_BODY_SIZE};
use capture::time::TimeSource;
use capture::v0_request::ProcessedEvent;
use chrono::{DateTime, Utc};
use common_redis::MockRedisClient;
use integration_utils::{test_lifecycle_handlers, DEFAULT_CONFIG, DEFAULT_TEST_TIME};
use limiters::token_dropper::TokenDropper;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const KNOWN_TOKEN: &str = "phc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const UNKNOWN_TOKEN: &str = "phc_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

struct FixedTime {
    time: DateTime<Utc>,
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

#[async_trait]
impl PublishEvents for CapturingSink {
    async fn publish_events(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.events.lock().await.extend(events);
        Ok(())
    }
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
}

/// Builds a client whose projection holds exactly one token, with the sweep
/// marker at `marker_age`.
async fn make_test_client(
    mode: TokenValidationMode,
    marker_age: Duration,
) -> (TestClient, CapturingSink) {
    let (readiness, liveness, _monitor) = test_lifecycle_handlers();
    let timesource = FixedTime {
        time: DateTime::parse_from_rfc3339(DEFAULT_TEST_TIME)
            .expect("invalid fixed time")
            .with_timezone(&Utc),
    };

    let mut projection = MockRedisClient::new();
    projection.get_ret(
        "capture_known_tokens_swept_at",
        Ok((now_secs() - marker_age.as_secs()).to_string()),
    );
    projection.get_ret(
        &format!("capture_known_token:{KNOWN_TOKEN}"),
        Ok("1".to_string()),
    );

    let checker = Arc::new(KnownTokenChecker::new(
        Arc::new(projection),
        None,
        Duration::from_millis(100),
        Duration::from_secs(600),
        Duration::from_secs(60),
        1000,
    ));
    checker.refresh_marker(Duration::from_secs(3600)).await;

    let redis = Arc::new(MockRedisClient::new());
    let sink = CapturingSink {
        events: Arc::new(tokio::sync::Mutex::new(Vec::new())),
    };
    let cfg = DEFAULT_CONFIG.clone();

    let app = router(
        timesource,
        readiness,
        liveness,
        Arc::new(OutputRegistry::single(sink.clone())),
        redis.clone(),
        None,
        CaptureQuotaLimiter::new(&cfg, redis, Duration::from_secs(60)),
        TokenDropper::default(),
        None,
        None,
        CaptureMode::Events,
        None,
        BATCH_BODY_SIZE,
        false,
        1_i64,
        false,
        0.0_f32,
        26_214_400,
        0,
        None,
        256,
        10 * 1024 * 1024,
        50 * 1024 * 1024,
        None,
        None,
        None,
        None,
        None,
        8,
        None,
        false,
        None,
        Some(checker),
        mode,
    );

    (TestClient::new(app), sink)
}

async fn post_event(client: &TestClient, token: &str) -> axum_test_helper::TestResponse {
    client
        .post("/capture")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(format!(
            r#"{{"token":"{token}","event":"$pageview","distinct_id":"someone"}}"#
        ))
        .send()
        .await
}

#[tokio::test]
async fn enforce_refuses_a_token_that_belongs_to_no_project() {
    let (client, sink) = make_test_client(TokenValidationMode::Enforce, Duration::ZERO).await;

    let res = post_event(&client, UNKNOWN_TOKEN).await;

    assert_eq!(res.status(), StatusCode::UNAUTHORIZED);
    assert!(res.text().await.contains("project API key"));
    assert_eq!(sink.events.lock().await.len(), 0);
}

#[tokio::test]
async fn enforce_still_accepts_a_token_the_projection_holds() {
    let (client, sink) = make_test_client(TokenValidationMode::Enforce, Duration::ZERO).await;

    let res = post_event(&client, KNOWN_TOKEN).await;

    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(sink.events.lock().await.len(), 1);
}

#[tokio::test]
async fn dry_run_accepts_an_unknown_token() {
    let (client, sink) = make_test_client(TokenValidationMode::DryRun, Duration::ZERO).await;

    let res = post_event(&client, UNKNOWN_TOKEN).await;

    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(sink.events.lock().await.len(), 1);
}

#[tokio::test]
async fn enforce_accepts_an_unknown_token_when_the_sweep_marker_is_stale() {
    // A sweep that stopped running must not turn into refused traffic.
    let (client, sink) =
        make_test_client(TokenValidationMode::Enforce, Duration::from_secs(7200)).await;

    let res = post_event(&client, UNKNOWN_TOKEN).await;

    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(sink.events.lock().await.len(), 1);
}
