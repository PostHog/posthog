//! Which paths each capture mode registers.
//!
//! Each deployment registers its own ingress and nothing else: the AI paths
//! belong to capture-ai, the analytics paths to capture-analytics and
//! capture-import. The ingress has always routed them that way, so the other
//! set was surface no traffic reached.
//!
//! It also has to stay in step with `Pipeline::for_capture_mode`, which loads
//! exactly the restriction slices each path set can produce to. A route on the
//! wrong deployment accepts traffic no restriction there governs, which is
//! silent rather than loud, so the split is asserted directly here.
//!
//! The pipeline-level gates cover the other half — an event name off the AI
//! allowlist arriving on a path that IS registered: `events::analytics` for the
//! v0 paths, `v1::analytics::process` for `/i/v1/ai/events`.

#[path = "common/integration_utils.rs"]
mod integration_utils;

use axum::http::StatusCode;
use axum_test_helper::TestClient;
use capture::config::CaptureMode;
use integration_utils::{build_router_for_mode, build_router_for_mode_with_v1_sink};
use rstest::rstest;
use serde_json::json;

/// A single `$ai_generation`, valid on any path that accepts a batch.
fn ai_batch_payload() -> String {
    json!({
        "api_key": "phc_route_surface_token",
        "batch": [{
            "event": "$ai_generation",
            "distinct_id": "test_user",
            "properties": {},
        }],
    })
    .to_string()
}

/// What a deployment must answer this file's payload on a given path.
///
/// [`Answer::Served`] names the real status rather than "anything but a 404",
/// so a positive case proves the intended handler ran: a 405 (the router
/// matched the path but not the method), a 5xx (no handler completed), and a
/// status from some other handler all fail it. [`Answer::Absent`] is the 404 a
/// router returns for a path it never registered.
#[derive(Debug, Clone, Copy)]
enum Answer {
    Served(StatusCode),
    Absent,
}

impl Answer {
    fn status(self) -> StatusCode {
        match self {
            Answer::Served(status) => status,
            Answer::Absent => StatusCode::NOT_FOUND,
        }
    }
}

/// Post the batch payload to `path` on a router built for `mode`, and pin what
/// comes back.
async fn assert_answer(mode: CaptureMode, path: &str, expected: Answer) {
    let status = TestClient::new(build_router_for_mode(mode))
        .post(path)
        .body(ai_batch_payload())
        .header("Content-Type", "application/json")
        // `InsecureClientIp` is a hard extractor on the analytics handlers, and
        // the test client provides no `ConnectInfo`, so without a forwarded
        // header every registered path answers 500 before its handler runs.
        .header("X-Forwarded-For", "127.0.0.1")
        .send()
        .await
        .status();

    assert_eq!(
        status,
        expected.status(),
        "{mode:?} answered {path} with {status}, expected {expected:?}"
    );
}

/// capture-ai must serve the AI batch path and nothing analytics-shaped.
///
/// The multipart and OTEL handlers answer 401 rather than 200: both read the
/// project token from an `Authorization: Bearer` header, and this file's payload
/// carries it in the body as `api_key`, the way the batch endpoints take it.
/// That is still a status only those handlers produce — reaching their auth step
/// means the router dispatched there — and pinning it is what makes these rows
/// assert something. Feeding each path a body it fully accepts would prove more,
/// but the payload shapes (multipart, protobuf) are what the endpoint suites
/// already cover; this file is about which paths exist.
#[rstest]
#[case::ai_batch("/i/v0/ai/batch", Answer::Served(StatusCode::OK))]
#[case::ai_batch_trailing_slash("/i/v0/ai/batch/", Answer::Served(StatusCode::OK))]
#[case::ai_multipart("/i/v0/ai", Answer::Served(StatusCode::UNAUTHORIZED))]
#[case::ai_otel("/i/v0/ai/otel", Answer::Served(StatusCode::UNAUTHORIZED))]
#[case::analytics_batch("/batch", Answer::Absent)]
#[case::analytics_event("/e", Answer::Absent)]
#[case::analytics_capture("/capture", Answer::Absent)]
#[case::analytics_track("/track", Answer::Absent)]
#[case::analytics_engage("/engage", Answer::Absent)]
#[tokio::test]
async fn ai_mode_registers_only_the_ai_paths(#[case] path: &str, #[case] expected: Answer) {
    assert_answer(CaptureMode::Ai, path, expected).await;
}

/// capture-analytics serves the analytics paths and none of the AI ones. It
/// still ingests AI events — they arrive on `/batch` from SDKs that send
/// everything to one endpoint and divert by event name — so a passing
/// `/batch` case here is what keeps that route alive.
#[rstest]
#[case::analytics_batch("/batch", Answer::Served(StatusCode::OK))]
#[case::analytics_batch_trailing_slash("/batch/", Answer::Served(StatusCode::OK))]
#[case::analytics_event("/e", Answer::Served(StatusCode::OK))]
#[case::analytics_capture("/capture", Answer::Served(StatusCode::OK))]
#[case::analytics_track("/track", Answer::Served(StatusCode::OK))]
#[case::ai_batch("/i/v0/ai/batch", Answer::Absent)]
#[case::ai_multipart("/i/v0/ai", Answer::Absent)]
#[case::ai_otel("/i/v0/ai/otel", Answer::Absent)]
#[tokio::test]
async fn events_mode_registers_only_the_analytics_paths(
    #[case] path: &str,
    #[case] expected: Answer,
) {
    assert_answer(CaptureMode::Events, path, expected).await;
}

/// Import is an analytics deployment restricted to backfills, so it serves the
/// same paths as capture-analytics. The AI handlers are doubly excluded: they
/// belong to capture-ai, and they build their own context with
/// `historical_migration: false`, which would sidestep the import gates.
#[rstest]
#[case::analytics_batch("/batch", Answer::Served(StatusCode::OK))]
#[case::analytics_event("/e", Answer::Served(StatusCode::OK))]
#[case::analytics_v0_event("/i/v0/e", Answer::Served(StatusCode::OK))]
#[case::ai_batch("/i/v0/ai/batch", Answer::Absent)]
#[case::ai_multipart("/i/v0/ai", Answer::Absent)]
#[case::ai_multipart_trailing_slash("/i/v0/ai/", Answer::Absent)]
#[case::ai_otel("/i/v0/ai/otel", Answer::Absent)]
#[case::ai_otel_trailing_slash("/i/v0/ai/otel/", Answer::Absent)]
#[tokio::test]
async fn import_mode_registers_only_the_analytics_paths(
    #[case] path: &str,
    #[case] expected: Answer,
) {
    assert_answer(CaptureMode::Import, path, expected).await;
}

// ---------------------------------------------------------------------------
// v1 endpoints
// ---------------------------------------------------------------------------

/// Post a real v1 batch to `path` on a router built for `mode` with a v1 sink
/// wired, and pin what comes back.
///
/// Unlike the v0 cases above, the payload is one the endpoint fully accepts, so
/// [`Answer::Served`] is the 200 a completed publish returns rather than a status
/// from some earlier validation step. The event is an `$ai_generation`, which
/// both endpoints accept: the analytics endpoint diverts it to the AI lane by
/// name, and the AI endpoint's non-AI gate lets it through.
async fn assert_v1_answer(mode: CaptureMode, path: &str, expected: Answer) {
    let mut event = capture::v1::test_utils::valid_event();
    event.event = "$ai_generation".to_string();
    let payload = capture::v1::test_utils::batch_payload(&[event]);

    let status = TestClient::new(build_router_for_mode_with_v1_sink(mode))
        .post(path)
        .body(payload)
        .header("Authorization", "Bearer phc_route_surface_token")
        .header("Content-Type", "application/json")
        .header("X-Forwarded-For", "127.0.0.1")
        .header("PostHog-Sdk-Info", "posthog-rs/1.0.0")
        .header("PostHog-Attempt", "1")
        .header("PostHog-Request-Id", uuid::Uuid::new_v4().to_string())
        .header("PostHog-Request-Timestamp", "2026-03-19T14:30:00Z")
        .header("User-Agent", "test-agent/1.0")
        .send()
        .await
        .status();

    assert_eq!(
        status,
        expected.status(),
        "{mode:?} answered {path} with {status}, expected {expected:?}"
    );
}

/// capture-ai serves the v1 contract on its own path only. It must not also
/// serve `/i/v1/analytics/events`: that endpoint accepts any event name and its
/// traffic is governed by analytics restrictions, which capture-ai does not load.
#[rstest]
#[case::ai_events("/i/v1/ai/events", Answer::Served(StatusCode::OK))]
#[case::ai_events_trailing_slash("/i/v1/ai/events/", Answer::Served(StatusCode::OK))]
#[case::analytics_events("/i/v1/analytics/events", Answer::Absent)]
#[case::analytics_events_trailing_slash("/i/v1/analytics/events/", Answer::Absent)]
#[tokio::test]
async fn ai_mode_serves_only_the_v1_ai_endpoint(#[case] path: &str, #[case] expected: Answer) {
    assert_v1_answer(CaptureMode::Ai, path, expected).await;
}

/// The mirror image: the analytics deployments keep the analytics endpoint and
/// never register the AI one. They still ingest `$ai_*` events, which divert to
/// the AI lane by event name on the analytics path.
#[rstest]
#[case::events_analytics(
    CaptureMode::Events,
    "/i/v1/analytics/events",
    Answer::Served(StatusCode::OK)
)]
#[case::events_ai(CaptureMode::Events, "/i/v1/ai/events", Answer::Absent)]
#[case::events_ai_trailing_slash(CaptureMode::Events, "/i/v1/ai/events/", Answer::Absent)]
#[case::import_analytics(
    CaptureMode::Import,
    "/i/v1/analytics/events",
    Answer::Served(StatusCode::OK)
)]
#[case::import_ai(CaptureMode::Import, "/i/v1/ai/events", Answer::Absent)]
#[case::recordings_analytics(CaptureMode::Recordings, "/i/v1/analytics/events", Answer::Absent)]
#[case::recordings_ai(CaptureMode::Recordings, "/i/v1/ai/events", Answer::Absent)]
#[tokio::test]
async fn non_ai_modes_never_serve_the_v1_ai_endpoint(
    #[case] mode: CaptureMode,
    #[case] path: &str,
    #[case] expected: Answer,
) {
    assert_v1_answer(mode, path, expected).await;
}

/// Without a v1 sink the paths stay unregistered on every mode, which is what
/// makes the sink-wired assertions above say something about the mode gating
/// rather than about sink presence.
#[rstest]
#[case::ai(CaptureMode::Ai, "/i/v1/ai/events")]
#[case::events(CaptureMode::Events, "/i/v1/analytics/events")]
#[tokio::test]
async fn v1_paths_stay_unregistered_without_a_v1_sink(
    #[case] mode: CaptureMode,
    #[case] path: &str,
) {
    assert_answer(mode, path, Answer::Absent).await;
}
