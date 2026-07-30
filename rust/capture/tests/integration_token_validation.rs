use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use axum::http::StatusCode;
use axum::Router;
use axum_test_helper::TestClient;
use chrono::{DateTime, Utc};
use common_redis::MockRedisClient;
use limiters::token_dropper::TokenDropper;
use serde_json::json;

use capture::api::CaptureError;
use capture::config::{AiRouting, CaptureMode};
use capture::quota_limiters::CaptureQuotaLimiter;
use capture::router::router;
use capture::sinks::Event;
use capture::time::TimeSource;
use capture::token_validation::{TeamTokenStore, TokenValidationMode, TokenValidator};
use capture::v0_request::ProcessedEvent;

#[path = "common/integration_utils.rs"]
mod integration_utils;
use integration_utils::{test_lifecycle_handlers, DEFAULT_CONFIG};

const KNOWN_TOKEN: &str = "phc_a_real_project_key";
const TYPOD_TOKEN: &str = "phc_a_reaI_prOject_key";

struct FixedTime;

impl TimeSource for FixedTime {
    fn current_time(&self) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-07-01T11:00:00Z")
            .unwrap()
            .with_timezone(&Utc)
    }
}

#[derive(Clone, Default)]
struct MemorySink {
    events: Arc<Mutex<Vec<ProcessedEvent>>>,
}

impl MemorySink {
    fn count(&self) -> usize {
        self.events.lock().unwrap().len()
    }
}

#[async_trait]
impl Event for MemorySink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.events.lock().unwrap().push(event);
        Ok(())
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.events.lock().unwrap().extend_from_slice(&events);
        Ok(())
    }
}

/// Knows about exactly one team, and counts lookups so tests can tell a cached
/// verdict from a fresh one.
struct OneTeamStore {
    answer_with_failure: bool,
    lookups: AtomicUsize,
}

#[async_trait]
impl TeamTokenStore for OneTeamStore {
    async fn team_exists(&self, token: &str) -> anyhow::Result<Option<bool>> {
        self.lookups.fetch_add(1, Ordering::SeqCst);
        if self.answer_with_failure {
            anyhow::bail!("the read replica is unreachable");
        }
        Ok(Some(token == KNOWN_TOKEN))
    }
}

fn build_router(validator: TokenValidator) -> (Router, MemorySink) {
    let (readiness, liveness, _monitor) = test_lifecycle_handlers();
    let sink = MemorySink::default();
    let redis = Arc::new(MockRedisClient::new());
    let cfg = DEFAULT_CONFIG.clone();
    let quota_limiter =
        CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60 * 60 * 24 * 7));

    (
        router(
            FixedTime,
            readiness,
            liveness,
            Arc::new(sink.clone()),
            redis,
            None, // global_rate_limiter_token_distinctid
            quota_limiter,
            TokenDropper::default(),
            Arc::new(validator),
            None, // event_restriction_service
            false,
            CaptureMode::Events,
            String::from("capture"),
            None,
            25 * 1024 * 1024,
            false,
            1_i64,
            false,
            0.0_f32,
            26_214_400,
            None,               // ai_blob_storage
            None,               // body_chunk_read_timeout_ms
            256,                // body_read_chunk_size_kb
            10 * 1024 * 1024,   // capture_v1_max_compressed_body_bytes
            50 * 1024 * 1024,   // capture_v1_max_decompressed_body_bytes
            None,               // overflow_limiter
            None,               // ai_events_overflow_limiter
            None,               // replay_overflow_limiter
            None,               // v1_sink_router
            8,                  // capture_v1_scatter_gather_min_batch
            None,               // ai_gateway_signing_secret
            AiRouting::Primary, // ai_routing
            false,              // ai_events_overflow_enabled
            None,               // ingestion_warning_emitter
        ),
        sink,
    )
}

fn validator(mode: TokenValidationMode, store: Arc<OneTeamStore>) -> TokenValidator {
    let store: Arc<dyn TeamTokenStore> = store;
    TokenValidator::new(
        mode,
        Some(store),
        100,
        Duration::from_secs(300),
        Duration::from_secs(30),
    )
}

fn working_store() -> Arc<OneTeamStore> {
    Arc::new(OneTeamStore {
        answer_with_failure: false,
        lookups: AtomicUsize::new(0),
    })
}

async fn post_event(router: &Router, token: &str) -> StatusCode {
    let payload = json!({
        "api_key": token,
        "event": "testing",
        "distinct_id": "user-1",
    });
    TestClient::new(router.clone())
        .post("/e")
        .body(payload.to_string())
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await
        .status()
}

#[tokio::test]
async fn a_mistyped_key_is_rejected_instead_of_silently_accepted() {
    let (router, sink) = build_router(validator(TokenValidationMode::Enforce, working_store()));

    assert_eq!(
        post_event(&router, TYPOD_TOKEN).await,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        sink.count(),
        0,
        "a token no team owns must not reach the pipeline"
    );

    assert_eq!(post_event(&router, KNOWN_TOKEN).await, StatusCode::OK);
    assert_eq!(sink.count(), 1);
}

#[tokio::test]
async fn dry_run_accepts_a_mistyped_key() {
    let store = working_store();
    let (router, sink) = build_router(validator(TokenValidationMode::DryRun, store.clone()));

    assert_eq!(post_event(&router, TYPOD_TOKEN).await, StatusCode::OK);
    assert_eq!(sink.count(), 1);
    assert_eq!(
        store.lookups.load(Ordering::SeqCst),
        1,
        "dry run still resolves the token, so the reject rate is observable"
    );
}

#[tokio::test]
async fn a_lookup_failure_never_rejects_valid_traffic() {
    let store = Arc::new(OneTeamStore {
        answer_with_failure: true,
        lookups: AtomicUsize::new(0),
    });
    let (router, sink) = build_router(validator(TokenValidationMode::Enforce, store));

    assert_eq!(post_event(&router, KNOWN_TOKEN).await, StatusCode::OK);
    assert_eq!(sink.count(), 1);
}

#[tokio::test]
async fn repeated_requests_reuse_the_cached_verdict() {
    let store = working_store();
    let (router, _sink) = build_router(validator(TokenValidationMode::Enforce, store.clone()));

    for _ in 0..3 {
        assert_eq!(post_event(&router, KNOWN_TOKEN).await, StatusCode::OK);
        assert_eq!(
            post_event(&router, TYPOD_TOKEN).await,
            StatusCode::UNAUTHORIZED
        );
    }

    assert_eq!(
        store.lookups.load(Ordering::SeqCst),
        2,
        "one lookup per distinct token, in both directions"
    );
}
