#[path = "common/integration_utils.rs"]
mod integration_utils;

use async_trait::async_trait;
use axum::http::StatusCode;
use axum_test_helper::TestClient;
use capture::api::CaptureError;
use capture::config::CaptureMode;
use capture::quota_limiters::CaptureQuotaLimiter;
use capture::router::{router, BATCH_BODY_SIZE};
use capture::sinks::Event;
use capture::time::TimeSource;
use capture::v0_request::ProcessedEvent;
use chrono::{DateTime, Utc};
use common_redis::MockRedisClient;
use integration_utils::{test_lifecycle_handlers, DEFAULT_TEST_TIME};
use limiters::token_dropper::TokenDropper;
use std::sync::Arc;
use std::time::Duration;

use integration_utils::DEFAULT_CONFIG;

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

    async fn count(&self) -> usize {
        self.events.lock().await.len()
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

/// A client whose decompressed budget is far above the wire cap, so only the
/// wire cap can produce a 413. This mirrors production, where the decompressed
/// budget is five times the wire cap.
fn make_test_client(mode: CaptureMode) -> (TestClient, CapturingSink) {
    let (readiness, liveness, _monitor) = test_lifecycle_handlers();
    let timesource = FixedTime {
        time: DateTime::parse_from_rfc3339(DEFAULT_TEST_TIME)
            .expect("Invalid fixed time format")
            .with_timezone(&Utc),
    };
    let redis = Arc::new(MockRedisClient::new());
    let sink = CapturingSink::new();
    let mut cfg = DEFAULT_CONFIG.clone();
    cfg.capture_mode = mode;

    let app = router(
        timesource,
        readiness,
        liveness,
        Arc::new(sink.clone()),
        redis.clone(),
        None,
        CaptureQuotaLimiter::new(&cfg, redis, Duration::from_secs(60)),
        TokenDropper::default(),
        None,
        None,
        mode,
        None,
        BATCH_BODY_SIZE * 5,
        false,
        1_i64,
        false,
        0.0_f32,
        26_214_400,
        // Far above any body this file sends: the AI-lane event ceiling must not
        // be what produces a 413 here, or the wire cap would go untested.
        BATCH_BODY_SIZE as u64 * 5, // ai_max_event_bytes
        None,
        256,
        10 * 1024 * 1024,
        50 * 1024 * 1024,
        None, // overflow_limiter
        None, // ai_events_overflow_limiter
        None, // ai_byte_rate_limiter
        None, // replay_overflow_limiter
        None, // v1_sink_router
        8,
        None,
        false,
        None,
    );

    (TestClient::new(app), sink)
}

/// A body of `len` bytes that is valid JSON, so nothing before the size check
/// can reject it for a different reason.
fn body_of_len(len: usize) -> String {
    named_body_of_len(len, "e")
}

/// The same, with the event name chosen. Capture-ai rejects any event outside the
/// `AI_EVENT_NAMES` allowlist with a 400 before the size check is reached, so an
/// AI-lane body has to carry a listed name to exercise the cap at all.
fn named_body_of_len(len: usize, event: &str) -> String {
    let envelope = format!(
        r#"{{"token":"phc_test","event":"{event}","distinct_id":"d","properties":{{"big":""}}}}"#
    );
    let padding = len.saturating_sub(envelope.len());
    format!(
        r#"{{"token":"phc_test","event":"{}","distinct_id":"d","properties":{{"big":"{}"}}}}"#,
        event,
        "a".repeat(padding)
    )
}

/// The analytics paths an Events-mode deployment registers. `/i/v0/ai/batch`
/// runs the same handler under the same cap, but only capture-ai serves it, so
/// it is swept separately below rather than from this list.
const ANALYTICS_ROUTES: [&str; 6] = ["/e", "/i/v0/e", "/batch", "/capture", "/track", "/engage"];

/// Every v0 analytics route shares one handler, so every one of them must share
/// one wire cap. Before this was wired through, `DefaultBodyLimit` was the only
/// thing carrying these numbers, and it does not apply to a `Body` extractor —
/// so each of these paths silently accepted the much larger decompressed budget.
#[tokio::test]
async fn every_v0_analytics_route_rejects_a_body_over_the_wire_cap() {
    let (client, _sink) = make_test_client(CaptureMode::Events);
    let over = body_of_len(BATCH_BODY_SIZE + 1024);

    for path in ANALYTICS_ROUTES {
        let res = client
            .post(path)
            .header("Content-Type", "application/json")
            .header("X-Forwarded-For", "127.0.0.1")
            .body(over.clone())
            .send()
            .await;
        assert_eq!(
            StatusCode::PAYLOAD_TOO_LARGE,
            res.status(),
            "{path} accepted a body over the wire cap"
        );
    }
}

/// The cap must not be so tight that it rejects a legal body. This is the half
/// the pre-existing boundary tests stopped asserting, which is why a widened cap
/// went unnoticed.
#[tokio::test]
async fn every_v0_analytics_route_accepts_a_body_under_the_wire_cap() {
    let (client, sink) = make_test_client(CaptureMode::Events);
    // Comfortably over the 2MB cap the event routes used to carry, and well
    // under the shared 20MB one.
    let under = body_of_len(4 * 1024 * 1024);
    let mut ingested = 0usize;

    for path in ANALYTICS_ROUTES {
        let res = client
            .post(path)
            .header("Content-Type", "application/json")
            .header("X-Forwarded-For", "127.0.0.1")
            .body(under.clone())
            .send()
            .await;
        assert_eq!(
            StatusCode::OK,
            res.status(),
            "{path} rejected a body inside the wire cap"
        );
        ingested += 1;
        assert_eq!(
            ingested,
            sink.count().await,
            "{path} returned 200 without producing the event"
        );
    }
}

/// `/i/v0/ai/batch` carries the same handler and the same cap, but it lives in
/// its own router group that only capture-ai registers. That split is what makes
/// this worth pinning apart: a group added without the `WireBodyLimit` extension
/// falls back to the decompressed budget and reverts the fix on this one route,
/// and no Events-mode sweep would notice.
#[tokio::test]
async fn the_ai_batch_route_carries_the_same_wire_cap() {
    let (client, sink) = make_test_client(CaptureMode::Ai);

    let res = client
        .post("/i/v0/ai/batch")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(named_body_of_len(BATCH_BODY_SIZE + 1024, "$ai_span"))
        .send()
        .await;
    assert_eq!(
        StatusCode::PAYLOAD_TOO_LARGE,
        res.status(),
        "/i/v0/ai/batch accepted a body over the wire cap"
    );

    let res = client
        .post("/i/v0/ai/batch")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(named_body_of_len(4 * 1024 * 1024, "$ai_span"))
        .send()
        .await;
    assert_eq!(
        StatusCode::OK,
        res.status(),
        "/i/v0/ai/batch rejected a body inside the wire cap"
    );
    assert_eq!(
        1,
        sink.count().await,
        "/i/v0/ai/batch returned 200 without producing the event"
    );
}

/// The drain exists so a rejection can be written on a connection the client
/// keeps using. A small overshoot proves little, because hyper's own one-shot
/// drain absorbs a few leftover bytes by itself. This overshoots by half the cap,
/// which is far more than hyper will absorb, and asserts the status still lands
/// on a connection the next request can reuse.
///
/// The drain budget is one times the cap, so it covers bodies up to twice the
/// cap. Past that it gives up and the client sees a reset instead. Nothing in
/// production comes close: the largest bodies observed are well under the cap.
#[tokio::test]
async fn a_large_overshoot_still_delivers_the_status_instead_of_a_reset() {
    let (client, sink) = make_test_client(CaptureMode::Events);
    let res = client
        .post("/batch")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(body_of_len(BATCH_BODY_SIZE + BATCH_BODY_SIZE / 2))
        .send()
        .await;

    assert_eq!(StatusCode::PAYLOAD_TOO_LARGE, res.status());

    // The connection survived the rejection, so the next request works.
    let res = client
        .post("/batch")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(body_of_len(1024))
        .send()
        .await;
    assert_eq!(StatusCode::OK, res.status());
    assert_eq!(
        1,
        sink.count().await,
        "the retry after a rejection was lost"
    );
}

/// Replay keeps its own, larger cap. It runs a different handler, so the wiring
/// is separate and worth pinning apart from the analytics routes.
#[tokio::test]
async fn the_replay_route_rejects_a_body_over_its_own_wire_cap() {
    let (client, _sink) = make_test_client(CaptureMode::Recordings);
    let res = client
        .post("/s")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .body(body_of_len(26 * 1024 * 1024))
        .send()
        .await;

    assert_eq!(StatusCode::PAYLOAD_TOO_LARGE, res.status());
}
