use std::sync::Arc;

use axum::{body::Body, http::Request};
use common_redis::MockRedisClient;
use cymbal::{
    app_context::AppContext, error::UnhandledError, modes::processing::ProcessingConfig,
    router::get_router,
};
use serde_json::{json, Value};
use shimforge::{mock, Session};
use sqlx::PgPool;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
mod utils;

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn pipeline_failure_is_captured_as_posthog_exception(db: PgPool) {
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

    let mut session = Session::new();
    let capture = mock!(
        session,
        common_posthog::capture_exception::<UnhandledError>,
        fn(Arc<UnhandledError>, [(&'static str, Value); 3])
    );
    capture
        .expect()
        .with(|error, properties| {
            matches!(&**error, UnhandledError::SqlxError(sqlx::Error::PoolClosed))
                && properties.contains(&("request_id", json!("capture-test-request")))
                && properties.contains(&("batch_event_count", json!(1)))
                && properties.contains(&("team_count", json!(1)))
        })
        .once()
        .returns_default();
    // Enforced when `session` drops, not at call time.

    let response = router
        .oneshot(
            Request::builder()
                .method("POST")
                .header("content-type", "application/json")
                .header("x-request-id", "capture-test-request")
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
}
