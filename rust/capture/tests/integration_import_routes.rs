#[path = "common/integration_utils.rs"]
mod integration_utils;
use integration_utils::build_router_for_mode;

use axum::http::StatusCode;
use axum_test_helper::TestClient;
use capture::config::CaptureMode;

// Import mode must not register the AI or OTEL handlers: they build their own
// ProcessingContext with historical_migration: false, so they would bypass both
// Import gates (historical-only drop and GRL) and return a false 200 for traffic
// this deployment silently discards. Events mode keeps them.
#[tokio::test]
async fn test_import_mode_does_not_register_ai_or_otel_routes() {
    let client = TestClient::new(build_router_for_mode(CaptureMode::Import));

    for path in ["/i/v0/ai", "/i/v0/ai/", "/i/v0/ai/otel", "/i/v0/ai/otel/"] {
        let resp = client.post(path).body(vec![]).send().await;
        assert_eq!(
            StatusCode::NOT_FOUND,
            resp.status(),
            "Import mode must not register {path}, expected 404",
        );
    }
}

// The gated batch/event paths stay reachable in Import mode. /i/v0/ai/batch lives
// on batch_router (not ai_router) and dispatches to the gated v0_endpoint::event,
// so it survives the split. "Not 404" is the assertion: an empty body yields a 4xx
// from the handler, which still proves the route is registered.
#[tokio::test]
async fn test_import_mode_serves_gated_event_routes() {
    let client = TestClient::new(build_router_for_mode(CaptureMode::Import));

    for path in ["/i/v0/e", "/batch", "/i/v0/ai/batch"] {
        let resp = client.post(path).body(vec![]).send().await;
        assert_ne!(
            StatusCode::NOT_FOUND,
            resp.status(),
            "Import mode must serve {path}, got 404",
        );
    }
}

// Guard the contrast: Events mode does register the AI/OTEL routes, so the split
// above is the only thing withholding them from Import.
#[tokio::test]
async fn test_events_mode_registers_ai_and_otel_routes() {
    let client = TestClient::new(build_router_for_mode(CaptureMode::Events));

    for path in ["/i/v0/ai", "/i/v0/ai/otel"] {
        let resp = client.post(path).body(vec![]).send().await;
        assert_ne!(
            StatusCode::NOT_FOUND,
            resp.status(),
            "Events mode must register {path}, got 404",
        );
    }
}
