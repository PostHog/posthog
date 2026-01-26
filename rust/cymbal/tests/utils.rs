use std::sync::Arc;

use axum::async_trait;
use axum::{body::Body, http::Request};

use common_redis::MockRedisClient;
use cymbal::{app_context::AppContext, config::Config, error::UnhandledError, router::get_router};

use cymbal::symbol_store::BlobClient;
use mockall::mock;
use reqwest::StatusCode;
use serde::Deserialize;
use sqlx::PgPool;
use tower::ServiceExt;

mock! {
    pub(crate) S3Client {}

    #[async_trait]
    impl BlobClient for S3Client {
        async fn get(&self, bucket: &str, key: &str) -> Result<Option<Vec<u8>>, UnhandledError>;
        async fn put(&self, bucket: &str, key: &str, data: Vec<u8>) -> Result<(), UnhandledError>;
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

    let redis_client = Arc::new(MockRedisClient::new());
    let issue_buckets_redis_client = Arc::new(MockRedisClient::new());

    let app_ctx = AppContext::new(
        &config,
        s3_client,
        db.clone(),
        db.clone(),
        redis_client,
        issue_buckets_redis_client,
    )
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
    let body: T = serde_json::from_str(body_string.as_str())
        .expect("Failed to deserialize data: {body_string}");
    (status, body)
}
