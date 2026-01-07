use std::future::Future;
use std::{sync::Arc, time::Duration};

use axum::async_trait;
use axum::{body::Body, http::Request};
use common_geoip::GeoIpClient;
use common_kafka::{
    kafka_consumer::SingleTopicConsumer,
    kafka_producer::{create_kafka_producer, KafkaContext},
    transaction::TransactionalProducer,
};
use common_redis::RedisClient;
use cymbal::{
    app_context::{AppContext, FilterMode},
    config::{init_global_state, Config},
    error::UnhandledError,
    frames::resolver::Resolver,
    router::processing_router,
    symbol_store::{
        caching::{Caching, SymbolSetCache},
        chunk_id::ChunkIdFetcher,
        concurrency,
        hermesmap::HermesMapProvider,
        proguard::ProguardProvider,
        saving::Saving,
        sourcemap::SourcemapProvider,
        BlobClient, Catalog,
    },
    teams::TeamManager,
};
use health::HealthRegistry;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY};
use mockall::{mock, predicate};
use reqwest::StatusCode;
use serde::Deserialize;
use sqlx::{postgres::PgPoolOptions, PgPool};
use tokio::sync::Mutex;
use tower::ServiceExt;
use tracing::info;
use uuid::Uuid;

mock! {
    pub(crate) S3Client {}

    #[async_trait]
    impl BlobClient for S3Client {
        async fn get(&self, bucket: &str, key: &str) -> Result<Option<Vec<u8>>, UnhandledError>;
        async fn put(&self, bucket: &str, key: &str, data: Vec<u8>) -> Result<(), UnhandledError>;
        async fn ping_bucket(&self, bucket: &str) -> Result<(), UnhandledError>;
    }
}

async fn build_app_context(
    config: &Config,
    pool: PgPool,
    s3_client: Arc<MockS3Client>,
) -> Result<AppContext, UnhandledError> {
    init_global_state(config);
    let health_registry = HealthRegistry::new("liveness");
    let worker_liveness = health_registry
        .register("worker".to_string(), Duration::from_secs(60))
        .await;

    let kafka_consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;

    let kafka_transactional_liveness = health_registry
        .register("transactional_kafka".to_string(), Duration::from_secs(30))
        .await;
    let transactional_producer = TransactionalProducer::with_context(
        &config.kafka,
        &Uuid::now_v7().to_string(),
        Duration::from_secs(10),
        KafkaContext::from(kafka_transactional_liveness),
    )?;

    let kafka_immediate_liveness = health_registry
        .register("immediate_kafka".to_string(), Duration::from_secs(30))
        .await;
    let immediate_producer = create_kafka_producer(&config.kafka, kafka_immediate_liveness).await?;

    let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
    let persons_options = options.clone();
    // let posthog_pool = options.connect(&config.database_url).await?;
    // let persons_pool = persons_options.connect(&config.persons_url).await?;

    let ss_cache = Arc::new(Mutex::new(SymbolSetCache::new(
        config.symbol_store_cache_max_bytes,
    )));

    let smp = SourcemapProvider::new(config);
    let smp_chunk = ChunkIdFetcher::new(
        smp,
        s3_client.clone(),
        pool.clone(),
        config.object_storage_bucket.clone(),
    );
    let smp_saving = Saving::new(
        smp_chunk,
        pool.clone(),
        s3_client.clone(),
        config.object_storage_bucket.clone(),
        config.ss_prefix.clone(),
    );
    let smp_caching = Caching::new(smp_saving, ss_cache.clone());
    // We want to fetch each sourcemap from the outside world
    // exactly once, and if it isn't in the cache, load/parse
    // it from s3 exactly once too. Limiting the per symbol set
    // reference concurrency to 1 ensures this.
    let smp_atmostonce = concurrency::AtMostOne::new(smp_caching);

    let hmp_chunk = ChunkIdFetcher::new(
        HermesMapProvider {},
        s3_client.clone(),
        pool.clone(),
        config.object_storage_bucket.clone(),
    );
    let hmp_caching = Caching::new(hmp_chunk, ss_cache.clone());
    // We skip the saving layer for HermesMapProvider, since it'll never fetch something from the outside world.

    let pgp_chunk = ChunkIdFetcher::new(
        ProguardProvider {},
        s3_client.clone(),
        pool.clone(),
        config.object_storage_bucket.clone(),
    );
    let pgp_caching = Caching::new(pgp_chunk, ss_cache.clone());

    info!(
        "AppContext initialized, subscribed to topic {}",
        config.consumer.kafka_consumer_topic
    );

    let catalog = Catalog::new(smp_atmostonce, hmp_caching, pgp_caching);
    let resolver = Resolver::new(config);

    let team_manager = TeamManager::new(config);

    let geoip_client = GeoIpClient::new(config.maxmind_db_path.clone())?;

    let redis_client = RedisClient::with_config(
        config.redis_url.clone(),
        common_redis::CompressionConfig::disabled(),
        common_redis::RedisValueFormat::default(),
        if config.redis_response_timeout_ms == 0 {
            None
        } else {
            Some(Duration::from_millis(config.redis_response_timeout_ms))
        },
        if config.redis_connection_timeout_ms == 0 {
            None
        } else {
            Some(Duration::from_millis(config.redis_connection_timeout_ms))
        },
    )
    .await?;
    let redis_client = Arc::new(redis_client);

    let issue_buckets_redis_client = RedisClient::with_config(
        config.issue_buckets_redis_url.clone(),
        common_redis::CompressionConfig::disabled(),
        common_redis::RedisValueFormat::default(),
        if config.redis_response_timeout_ms == 0 {
            None
        } else {
            Some(Duration::from_millis(config.redis_response_timeout_ms))
        },
        if config.redis_connection_timeout_ms == 0 {
            None
        } else {
            Some(Duration::from_millis(config.redis_connection_timeout_ms))
        },
    )
    .await?;
    let issue_buckets_redis_client = Arc::new(issue_buckets_redis_client);

    // TODO - we expect here rather returning an UnhandledError because the limiter returns an Anyhow::Result,
    // which we don't want to put into the UnhandledError enum since it basically means "any error"
    let billing_limiter = RedisLimiter::new(
        Duration::from_secs(30),
        redis_client.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None, // The QUOTA_LIMITER_CACHE_KEY already has the full prefix
        QuotaResource::Exceptions,
        ServiceName::Cymbal,
    )
    .expect("Redis billing limiter construction succeeds");

    let filtered_teams = config
        .filtered_teams
        .split(",")
        .filter(|s| !s.is_empty())
        .map(|tid| tid.parse().expect("Filtered team id's must be i32s"))
        .collect();
    let filter_mode = match config.filter_mode.to_lowercase().as_str() {
        "in" => FilterMode::In,
        "out" => FilterMode::Out,
        _ => panic!("Invalid filter mode"),
    };

    Ok(AppContext {
        health_registry,
        worker_liveness,
        kafka_consumer,
        transactional_producer: Mutex::new(transactional_producer),
        immediate_producer,
        posthog_pool: pool.clone(),
        persons_pool: pool.clone(),
        catalog,
        resolver,
        config: config.clone(),
        team_manager,
        geoip_client,
        billing_limiter,
        issue_buckets_redis_client,
        filtered_teams,
        filter_mode,
    })
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

    let app_ctx = build_app_context(&config, db, s3_client).await.unwrap();
    let ctx = Arc::new(app_ctx);

    let res = processing_router()
        .with_state(ctx)
        .oneshot(request_factory())
        .await
        .unwrap();

    let status = res.status();
    let body_bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
        .await
        .unwrap();
    let body_string = String::from_utf8(body_bytes.to_vec()).unwrap();

    // Deserialize the JSON into your struct
    let body: T = serde_json::from_str(body_string.as_str()).unwrap();
    (status, body)
}
