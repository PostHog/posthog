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
use axum::Router;
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

/// A route is "registered" when the router does not 404 it. The handler may
/// still reject the payload for its own reasons, which is not what this file
/// is about, so any non-404 counts as registered.
async fn is_registered(router: Router, path: &str) -> bool {
    let res = TestClient::new(router)
        .post(path)
        .body(ai_batch_payload())
        .header("Content-Type", "application/json")
        .send()
        .await;
    res.status() != StatusCode::NOT_FOUND
}

/// capture-ai must serve the AI batch path and nothing analytics-shaped.
#[rstest]
#[case::ai_batch("/i/v0/ai/batch", true)]
#[case::ai_batch_trailing_slash("/i/v0/ai/batch/", true)]
#[case::ai_multipart("/i/v0/ai", true)]
#[case::ai_otel("/i/v0/ai/otel", true)]
#[case::analytics_batch("/batch", false)]
#[case::analytics_event("/e", false)]
#[case::analytics_capture("/capture", false)]
#[case::analytics_track("/track", false)]
#[case::analytics_engage("/engage", false)]
#[case::analytics_v1("/i/v1/analytics/events", false)]
#[tokio::test]
async fn ai_mode_registers_only_the_ai_paths(#[case] path: &str, #[case] expected: bool) {
    assert_eq!(
        is_registered(build_router_for_mode(CaptureMode::Ai), path).await,
        expected,
        "capture-ai registration for {path} should be {expected}"
    );
}

/// capture-analytics serves the analytics paths and none of the AI ones. It
/// still ingests AI events — they arrive on `/batch` from SDKs that send
/// everything to one endpoint and divert by event name — so a passing
/// `/batch` case here is what keeps that route alive.
#[rstest]
#[case::analytics_batch("/batch", true)]
#[case::analytics_batch_trailing_slash("/batch/", true)]
#[case::analytics_event("/e", true)]
#[case::analytics_capture("/capture", true)]
#[case::analytics_track("/track", true)]
#[case::ai_batch("/i/v0/ai/batch", false)]
#[case::ai_multipart("/i/v0/ai", false)]
#[case::ai_otel("/i/v0/ai/otel", false)]
#[tokio::test]
async fn events_mode_registers_only_the_analytics_paths(
    #[case] path: &str,
    #[case] expected: bool,
) {
    assert_eq!(
        is_registered(build_router_for_mode(CaptureMode::Events), path).await,
        expected,
        "capture-analytics registration for {path} should be {expected}"
    );
}

/// Import is an analytics deployment restricted to backfills, so it serves the
/// same paths as capture-analytics. The AI handlers are doubly excluded: they
/// belong to capture-ai, and they build their own context with
/// `historical_migration: false`, which would sidestep the import gates.
#[rstest]
#[case::analytics_batch("/batch", true)]
#[case::analytics_event("/e", true)]
#[case::analytics_v0_event("/i/v0/e", true)]
#[case::ai_batch("/i/v0/ai/batch", false)]
#[case::ai_multipart("/i/v0/ai", false)]
#[case::ai_multipart_trailing_slash("/i/v0/ai/", false)]
#[case::ai_otel("/i/v0/ai/otel", false)]
#[case::ai_otel_trailing_slash("/i/v0/ai/otel/", false)]
#[tokio::test]
async fn import_mode_registers_only_the_analytics_paths(
    #[case] path: &str,
    #[case] expected: bool,
) {
    assert_eq!(
        is_registered(build_router_for_mode(CaptureMode::Import), path).await,
        expected,
        "capture-import registration for {path} should be {expected}"
    );
}
