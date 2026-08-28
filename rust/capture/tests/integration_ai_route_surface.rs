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
//! The pipeline-level gate in `events::analytics` covers the other half: an
//! event name off the AI allowlist arriving on a path that IS registered.

#[path = "common/integration_utils.rs"]
mod integration_utils;

use axum::http::StatusCode;
use axum_test_helper::TestClient;
use capture::config::CaptureMode;
use integration_utils::build_router_for_mode;
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
#[case::analytics_v1("/i/v1/analytics/events", Answer::Absent)]
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
