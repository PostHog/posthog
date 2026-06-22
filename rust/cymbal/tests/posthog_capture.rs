use std::sync::Arc;
use std::time::Duration;

use axum::{body::Body, http::Request};
use common_redis::MockRedisClient;
use cymbal::{app_context::AppContext, modes::processing::ProcessingConfig, router::get_router};
use httpmock::prelude::*;
use mockall::predicate;
use serde_json::json;
use sqlx::PgPool;
use tower::ServiceExt;
use uuid::Uuid;

mod utils;
use utils::MockS3Client;

const STORAGE_BUCKET: &str = "test-bucket";

fn process_request(body: &serde_json::Value) -> Request<Body> {
    Request::builder()
        .method("POST")
        .header("content-type", "application/json")
        .uri("/process")
        .body(Body::from(serde_json::to_vec(body).unwrap()))
        .unwrap()
}

fn exception_event() -> serde_json::Value {
    json!([{
        "uuid": Uuid::now_v7(),
        "event": "$exception",
        "team_id": 1,
        "timestamp": "2024-01-01T00:00:00Z",
        "properties": {
            "$exception_list": [{"type": "Error", "value": "boom"}],
            "$exception_handled": false,
        },
    }])
}

// One test per binary: common_posthog::init configures a process-wide global
// client, so a second init with a different mock server would be ignored. Both
// behaviours (genuine errors captured, transient drops not) are exercised here
// against the same router.
#[sqlx::test(migrations = "./tests/test_migrations")]
async fn transient_db_drops_are_not_captured_but_genuine_errors_are(db: PgPool) {
    let posthog = MockServer::start_async().await;
    let capture = posthog
        .mock_async(|when, then| {
            when.method(POST)
                .path("/i/v0/e/")
                .body_contains("\"$exception\"")
                .body_contains("UnhandledError")
                .body_contains("\"service\":\"cymbal-test\"")
                .body_contains("\"request_id\"");
            then.status(200).body("{\"status\": 1}");
        })
        .await;
    // Catch-all so an unexpected payload shape fails the specific assertion
    // below instead of surfacing as a connection-level SDK error.
    let fallback = posthog
        .mock_async(|when, then| {
            when.path_contains("/");
            then.status(200).body("{\"status\": 1}");
        })
        .await;

    common_posthog::init("cymbal-test", Some("test-api-key"), &posthog.base_url())
        .await
        .expect("posthog init");

    let mut config = ProcessingConfig::init_with_defaults().unwrap();
    config.resolver.object_storage_bucket = STORAGE_BUCKET.to_string();

    let mut s3_client = MockS3Client::new();
    s3_client
        .expect_ping_bucket()
        .with(predicate::eq(STORAGE_BUCKET.to_string()))
        .returning(|_| Ok(()));

    let app_ctx = AppContext::new(
        &config,
        Arc::new(s3_client),
        db.clone(),
        Arc::new(MockRedisClient::new()),
    )
    .await
    .unwrap();
    let router = get_router(Arc::new(app_ctx));

    // Genuine (non-transient) failure: dropping the table the grouping stage
    // reads makes the pipeline's first DB query fail with a Database error,
    // standing in for a real bug-class failure. This MUST still be captured.
    sqlx::query("DROP TABLE posthog_errortrackinggroupingrule CASCADE")
        .execute(&db)
        .await
        .expect("drop grouping rule table");

    let response = router
        .clone()
        .oneshot(process_request(&exception_event()))
        .await
        .unwrap();
    assert_eq!(
        response.status(),
        reqwest::StatusCode::INTERNAL_SERVER_ERROR
    );

    // The capture is fire-and-forget; wait for it to reach the mock server.
    for _ in 0..100 {
        if capture.hits_async().await > 0 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    assert_eq!(
        capture.hits_async().await,
        1,
        "genuine errors should be captured; total capture requests seen: {}",
        fallback.hits_async().await
    );

    // Transient failure: with the pool closed, the pipeline's first DB access
    // fails with PoolClosed, which we now downgrade to a metric rather than
    // capturing as an exception. The request still returns 5xx.
    db.close().await;

    let response = router
        .oneshot(process_request(&exception_event()))
        .await
        .unwrap();
    assert_eq!(
        response.status(),
        reqwest::StatusCode::INTERNAL_SERVER_ERROR
    );

    // Give any (erroneous) capture time to land, then assert none was added.
    tokio::time::sleep(Duration::from_millis(500)).await;
    assert_eq!(
        capture.hits_async().await,
        1,
        "transient DB drops must not be captured as exceptions; total capture requests seen: {}",
        fallback.hits_async().await
    );
}
