use std::sync::{atomic::Ordering, Arc};

use axum::{body::Body, http::Request};
use common_redis::MockRedisClient;
use cymbal::{app_context::AppContext, config::Config, router::get_router};
use reqwest::StatusCode;
use sqlx::PgPool;
use tower::ServiceExt;

use crate::utils::MockS3Client;

mod utils;

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn readiness_returns_503_before_warming_and_200_after(db: PgPool) {
    let mut config = Config::init_with_defaults().unwrap();
    config.cache_warming_enabled = true;
    config.object_storage_bucket = "test-bucket".to_string();

    let mut s3_client = MockS3Client::default();
    s3_client.expect_ping_bucket().returning(|_| Ok(()));

    let issue_buckets_redis_client = Arc::new(MockRedisClient::new());

    let ctx = Arc::new(
        AppContext::new(
            &config,
            Arc::new(s3_client),
            db.clone(),
            issue_buckets_redis_client,
        )
        .await
        .unwrap(),
    );

    let router = get_router(ctx.clone());

    let response = router
        .clone()
        .oneshot(
            Request::builder()
                .uri("/_readiness")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);

    ctx.cache_warmed.store(true, Ordering::Relaxed);

    let response = router
        .oneshot(
            Request::builder()
                .uri("/_readiness")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn readiness_returns_200_immediately_when_warming_disabled(db: PgPool) {
    let mut config = Config::init_with_defaults().unwrap();
    config.cache_warming_enabled = false;
    config.object_storage_bucket = "test-bucket".to_string();

    let mut s3_client = MockS3Client::default();
    s3_client.expect_ping_bucket().returning(|_| Ok(()));

    let issue_buckets_redis_client = Arc::new(MockRedisClient::new());

    let ctx = Arc::new(
        AppContext::new(
            &config,
            Arc::new(s3_client),
            db.clone(),
            issue_buckets_redis_client,
        )
        .await
        .unwrap(),
    );

    let router = get_router(ctx);

    let response = router
        .oneshot(
            Request::builder()
                .uri("/_readiness")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
}
