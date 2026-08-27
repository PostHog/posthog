use std::{
    sync::{atomic::AtomicBool, Arc},
    time::Duration,
};

use axum::{body::Body, http::Request};

use bytes::Bytes;
use common_redis::MockRedisClient;
use cymbal::{
    app_context::AppContext,
    core::resolver::build_catalog,
    error::UnhandledError,
    modes::{
        processing::ProcessingConfig,
        resolution::{
            load_monitor::LoadMonitor,
            service::{CymbalResolutionService, ServiceConfig},
        },
    },
    router::get_router,
    symbolication::{symbol::local::LocalSymbolResolver, symbol_store::BlobClient},
};
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolutionServer;

use async_trait::async_trait;
use mockall::mock;
use rdkafka::message::ToBytes;
use reqwest::StatusCode;
use serde::Deserialize;
use sqlx::PgPool;
use tokio::sync::Semaphore;
use tonic::transport::Server;
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
    get_response_with_config(db, storage_bucket, request_factory, s3_client, |_| {}).await
}

#[allow(dead_code)]
pub(crate) async fn get_response_with_config<T: for<'de> Deserialize<'de>>(
    db: PgPool,
    storage_bucket: String,
    request_factory: impl Fn() -> Request<Body>,
    s3_client: Arc<MockS3Client>,
    configure: impl FnOnce(&mut ProcessingConfig),
) -> (StatusCode, T) {
    let mut config = ProcessingConfig::init_with_defaults().unwrap();
    config.resolver.object_storage_bucket = storage_bucket.clone();
    configure(&mut config);

    ensure_remote_resolution(&mut config, s3_client, db.clone()).await;

    let issue_buckets_redis_client = Arc::new(MockRedisClient::new());

    let app_ctx = AppContext::new(&config, db.clone(), issue_buckets_redis_client)
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

async fn ensure_remote_resolution(
    config: &mut ProcessingConfig,
    s3_client: Arc<MockS3Client>,
    db: PgPool,
) {
    if config.remote_resolution_host.is_empty() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind test resolution server");
        let addr = listener.local_addr().expect("test resolution server addr");
        let incoming = futures::stream::unfold(listener, |listener| async {
            Some((listener.accept().await.map(|(stream, _)| stream), listener))
        });
        s3_client
            .ping_bucket(&config.resolver.object_storage_bucket)
            .await
            .expect("test symbol store is available");
        let catalog = build_catalog(&config.resolver, s3_client, db.clone());
        let resolver = Arc::new(LocalSymbolResolver::new(
            &config.resolver,
            catalog,
            db.clone(),
        ));
        let service = CymbalResolutionService::new(
            resolver,
            Arc::new(Semaphore::new(4)),
            LoadMonitor::new(64),
            "test-instance",
            ServiceConfig {
                default_tick_interval: Duration::from_millis(25),
                min_tick_interval: Duration::from_millis(10),
                max_tick_interval: Duration::from_millis(100),
            },
            Arc::new(AtomicBool::new(false)),
        );
        tokio::spawn(async move {
            Server::builder()
                .add_service(CymbalResolutionServer::new(service))
                .serve_with_incoming(incoming)
                .await
                .expect("test resolution server exits cleanly");
        });
        config.remote_resolution_host = "127.0.0.1".to_string();
        config.remote_resolution_port = addr.port();
        config.resolver.internal_api_secret = "test-secret".to_string();
        config.remote_resolution_subscribe_tick_hint_ms = 25;
    }
}

#[allow(dead_code)]
pub(crate) async fn get_raw_response(
    db: PgPool,
    storage_bucket: String,
    request_factory: impl Fn() -> Request<Body>,
    s3_client: Arc<MockS3Client>,
) -> (StatusCode, String) {
    let mut config = ProcessingConfig::init_with_defaults().unwrap();
    config.resolver.object_storage_bucket = storage_bucket.clone();

    ensure_remote_resolution(&mut config, s3_client, db.clone()).await;

    let issue_buckets_redis_client = Arc::new(MockRedisClient::new());

    let app_ctx = AppContext::new(&config, db.clone(), issue_buckets_redis_client)
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
