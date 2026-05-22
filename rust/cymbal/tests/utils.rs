use std::sync::Arc;

use axum::{body::Body, http::Request};

use bytes::Bytes;
use common_redis::MockRedisClient;
use cymbal::{
    app_context::AppContext, config::Config, error::UnhandledError, router::get_router,
    symbol_store::BlobClient,
};

use async_trait::async_trait;
use mockall::mock;
use rdkafka::message::ToBytes;
use reqwest::StatusCode;
use serde::Deserialize;
use sqlx::PgPool;
use tower::ServiceExt;

mock! {
    pub(crate) S3Client {}

    #[async_trait]
    impl BlobClient for S3Client {
        async fn get(&self, bucket: &str, key: &str) -> Result<Option<Bytes>, UnhandledError>;
        async fn put(&self, bucket: &str, key: &str, data: Bytes) -> Result<(), UnhandledError>;
        async fn delete(&self, bucket: &str, key: &str) -> Result<(), UnhandledError>;
        async fn ping_bucket(&self, bucket: &str) -> Result<(), UnhandledError>;
    }
}

#[allow(dead_code)]
pub(crate) async fn get_response<T: for<'de> Deserialize<'de>>(
    db: PgPool,
    storage_bucket: String,
    request_factory: impl Fn() -> Request<Body>,
    s3_client: Arc<MockS3Client>,
) -> (StatusCode, T) {
    let mut config = Config::init_with_defaults().unwrap();
    config.object_storage_bucket = storage_bucket.clone();

    let issue_buckets_redis_client = Arc::new(MockRedisClient::new());

    let app_ctx = AppContext::new(&config, s3_client, db.clone(), issue_buckets_redis_client)
        .await
        .unwrap();

    let ctx = Arc::new(app_ctx);

    let res = get_router(ctx).oneshot(request_factory()).await.unwrap();

    let status = res.status();

    let body_bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
        .await
        .unwrap();

    let body_string = String::from_utf8(body_bytes.to_vec()).unwrap();

    // Deserialize the JSON into your struct
    let body: T = serde_json::from_slice(body_bytes.to_bytes())
        .unwrap_or_else(|e| panic!("Failed to deserialize response: {e} {body_string}"));
    (status, body)
}

#[allow(dead_code)]
pub(crate) async fn get_raw_response(
    db: PgPool,
    storage_bucket: String,
    request_factory: impl Fn() -> Request<Body>,
    s3_client: Arc<MockS3Client>,
) -> (StatusCode, String) {
    let mut config = Config::init_with_defaults().unwrap();
    config.object_storage_bucket = storage_bucket.clone();

    let issue_buckets_redis_client = Arc::new(MockRedisClient::new());

    let app_ctx = AppContext::new(&config, s3_client, db.clone(), issue_buckets_redis_client)
        .await
        .unwrap();

    let ctx = Arc::new(app_ctx);

    let res = get_router(ctx).oneshot(request_factory()).await.unwrap();

    let status = res.status();

    let body_bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
        .await
        .unwrap();

    let body_string = String::from_utf8(body_bytes.to_vec()).unwrap();
    (status, body_string)
}

/// Variant of `get_response` that lets the caller supply a pre-configured
/// `MockRedisClient` and apply config tweaks before constructing `AppContext`.
/// Used by `/v2/resolve` tests that need to assert on Redis call counts
/// (spike-detection batching) or force errors (spike-detection failure path).
#[allow(dead_code)]
pub(crate) async fn get_response_with_overrides<T: for<'de> Deserialize<'de>>(
    db: PgPool,
    storage_bucket: String,
    request_factory: impl Fn() -> Request<Body>,
    s3_client: Arc<MockS3Client>,
    redis_client: Arc<MockRedisClient>,
    configure: impl FnOnce(&mut Config),
) -> (StatusCode, T) {
    let mut config = Config::init_with_defaults().unwrap();
    config.object_storage_bucket = storage_bucket.clone();
    configure(&mut config);

    let app_ctx = AppContext::new(&config, s3_client, db.clone(), redis_client)
        .await
        .unwrap();

    let ctx = Arc::new(app_ctx);

    let res = get_router(ctx).oneshot(request_factory()).await.unwrap();

    let status = res.status();

    let body_bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
        .await
        .unwrap();

    let body_string = String::from_utf8(body_bytes.to_vec()).unwrap();

    let body: T = serde_json::from_slice(body_bytes.to_bytes())
        .unwrap_or_else(|e| panic!("Failed to deserialize response: {e} {body_string}"));
    (status, body)
}
