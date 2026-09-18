use std::sync::Arc;
use std::time::Duration;

use axum::{body::Body, http::Request};
use common_redis::MockRedisClient;
use cymbal::{app_context::AppContext, modes::processing::ProcessingConfig, router::get_router};
use httpmock::prelude::*;
use serde_json::json;
use sqlx::PgPool;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
mod utils;

// One test per binary: common_posthog::init configures a process-wide global
// client, so a second init with a different mock server would be ignored.
#[sqlx::test(migrations = "./tests/test_migrations")]
async fn pipeline_failure_is_captured_as_posthog_exception(db: PgPool) {
    let posthog = MockServer::start_async().await;
    let capture = posthog
        .mock_async(|when, then| {
            when.method(POST)
                .path("/i/v1/analytics/events")
                .body_contains("\"$exception\"")
                .body_contains("UnhandledError")
                .body_contains("\"service\":\"cymbal-test\"")
                .body_contains("\"request_id\"");
            then.status(200).body("{\"results\":{}}");
        })
        .await;
    // Catch-all so an unexpected payload shape fails the specific assertion
    // below instead of surfacing as a connection-level SDK error.
    let fallback = posthog
        .mock_async(|when, then| {
            when.path_contains("/");
            then.status(200).body("{\"results\":{}}");
        })
        .await;

    common_posthog::init("cymbal-test", Some("test-api-key"), &posthog.base_url())
        .await
        .expect("posthog init");

    let (addr, _) = common::spawn_stub_server(common::ServerBehavior::Happy).await;
    let mut config = ProcessingConfig::init_with_defaults().unwrap();
    config.remote_resolution_host = "127.0.0.1".to_string();
    config.remote_resolution_port = addr.port();
    config.resolver.internal_api_secret = "test-secret".to_string();
    config.remote_resolution_subscribe_tick_hint_ms = 25;
    let app_ctx = AppContext::new(&config, db.clone(), Arc::new(MockRedisClient::new()))
        .await
        .unwrap();
    let router = get_router(Arc::new(app_ctx));

    // With the pool closed, the pipeline's first database access fails with
    // an UnhandledError — the capture funnel under test.
    db.close().await;

    let event = json!([{
        "uuid": Uuid::now_v7(),
        "event": "$exception",
        "team_id": 1,
        "timestamp": "2024-01-01T00:00:00Z",
        "properties": {
            "$exception_list": [{"type": "Error", "value": "boom"}],
            "$exception_handled": false,
        },
    }]);

    let response = router
        .oneshot(
            Request::builder()
                .method("POST")
                .header("content-type", "application/json")
                .uri("/process")
                .body(Body::from(serde_json::to_vec(&event).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(
        response.status(),
        reqwest::StatusCode::INTERNAL_SERVER_ERROR
    );

    // The capture is fire-and-forget, and the SDK only buffers it: one event
    // never reaches `flush_at`, so delivery would otherwise wait on the 5s
    // `flush_interval_ms`. Flush every turn so this waits on the spawned send
    // rather than racing that interval.
    for _ in 0..100 {
        posthog_rs::flush().await;
        if capture.hits_async().await > 0 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    assert_eq!(
        capture.hits_async().await,
        1,
        "expected a matching $exception capture; total capture requests seen: {}",
        fallback.hits_async().await
    );
}
