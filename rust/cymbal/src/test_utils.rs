//! Test utilities for creating mock AppContext and related helpers.
//! This module is only available when the `test-utils` feature is enabled or during tests.

use std::sync::Arc;

use async_trait::async_trait;
use bytes::Bytes;
use common_redis::MockRedisClient;
use mockall::mock;
use sqlx::PgPool;

use crate::{
    app_context::AppContext, error::UnhandledError, modes::processing::config::ProcessingConfig,
    symbolication::symbol_store::BlobClient,
};

mock! {
    pub S3Client {}

    #[async_trait]
    impl BlobClient for S3Client {
        async fn get(&self, bucket: &str, key: &str) -> Result<Option<Bytes>, UnhandledError>;
        async fn put(&self, bucket: &str, key: &str, data: Bytes) -> Result<(), UnhandledError>;
        async fn delete(&self, bucket: &str, key: &str) -> Result<(), UnhandledError>;
        async fn ping_bucket(&self, bucket: &str) -> Result<(), UnhandledError>;
    }
}

pub async fn create_test_context(db: PgPool) -> Arc<AppContext> {
    create_test_context_with_config(db, ProcessingConfig::init_with_defaults().unwrap()).await
}

pub async fn create_test_context_with_config(
    db: PgPool,
    config: ProcessingConfig,
) -> Arc<AppContext> {
    let mut mock_s3 = MockS3Client::new();
    mock_s3.expect_ping_bucket().returning(|_| Ok(()));
    let s3_client = Arc::new(mock_s3);

    let issue_buckets_redis_client = Arc::new(MockRedisClient::new());

    let app_ctx = AppContext::new(&config, s3_client, db.clone(), issue_buckets_redis_client)
        .await
        .unwrap();

    Arc::new(app_ctx)
}

pub async fn create_test_context_with_s3(
    db: PgPool,
    s3_client: Arc<MockS3Client>,
) -> Arc<AppContext> {
    create_test_context_with_s3_and_config(
        db,
        s3_client,
        ProcessingConfig::init_with_defaults().unwrap(),
    )
    .await
}

pub async fn create_test_context_with_s3_and_config(
    db: PgPool,
    s3_client: Arc<MockS3Client>,
    config: ProcessingConfig,
) -> Arc<AppContext> {
    let issue_buckets_redis_client = Arc::new(MockRedisClient::new());

    let app_ctx = AppContext::new(&config, s3_client, db.clone(), issue_buckets_redis_client)
        .await
        .unwrap();

    Arc::new(app_ctx)
}
