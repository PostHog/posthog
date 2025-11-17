use common_geoip::GeoIpClient;
use common_kafka::{
    kafka_consumer::SingleTopicConsumer,
    kafka_producer::{create_kafka_producer, KafkaContext},
    transaction::TransactionalProducer,
};
use common_redis::RedisClient;
use health::{HealthHandle, HealthRegistry};
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY};
use rdkafka::producer::FutureProducer;
use sqlx::{postgres::PgPoolOptions, PgPool};
use std::{sync::Arc, time::Duration};
use tokio::sync::Mutex;
use tracing::info;
use uuid::Uuid;

use crate::{
    config::{get_aws_config, init_global_state, Config},
    error::UnhandledError,
    frames::resolver::Resolver,
    symbol_store::{
        caching::{Caching, SymbolSetCache},
        chunk_id::ChunkIdFetcher,
        concurrency,
        hermesmap::HermesMapProvider,
        proguard::ProguardProvider,
        saving::Saving,
        sourcemap::SourcemapProvider,
        Catalog, S3Client,
    },
    teams::TeamManager,
};

pub enum FilterMode {
    In,
    Out,
}

pub struct AppContext {
    pub health_registry: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub kafka_consumer: SingleTopicConsumer,
    pub transactional_producer: Mutex<TransactionalProducer<KafkaContext>>,
    pub immediate_producer: FutureProducer<KafkaContext>,
    pub posthog_pool: PgPool,
    pub persons_pool: PgPool,
    pub catalog: Catalog,
    pub resolver: Resolver,
    pub config: Config,
    pub geoip_client: GeoIpClient,

    pub team_manager: TeamManager,
    pub billing_limiter: RedisLimiter,

    pub filtered_teams: Vec<i32>,
    pub filter_mode: FilterMode,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, UnhandledError> {
        init_global_state(config);
        let health_registry = HealthRegistry::new("liveness");
        let worker_liveness = health_registry
            .register("worker".to_string(), Duration::from_secs(60))
            .await;

        let kafka_consumer =
            SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;

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
        let immediate_producer =
            create_kafka_producer(&config.kafka, kafka_immediate_liveness).await?;

        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let persons_options = options.clone();
        let posthog_pool = options.connect(&config.database_url).await?;
        let persons_pool = persons_options.connect(&config.persons_url).await?;

        let s3_client = aws_sdk_s3::Client::from_conf(get_aws_config(config).await);
        let s3_client = S3Client::new(s3_client);
        let s3_client = Arc::new(s3_client);

        s3_client.ping_bucket(&config.object_storage_bucket).await?;

        let ss_cache = Arc::new(Mutex::new(SymbolSetCache::new(
            config.symbol_store_cache_max_bytes,
        )));

        let smp = SourcemapProvider::new(config);
        let smp_chunk = ChunkIdFetcher::new(
            smp,
            s3_client.clone(),
            posthog_pool.clone(),
            config.object_storage_bucket.clone(),
        );
        let smp_saving = Saving::new(
            smp_chunk,
            posthog_pool.clone(),
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
            posthog_pool.clone(),
            config.object_storage_bucket.clone(),
        );
        let hmp_caching = Caching::new(hmp_chunk, ss_cache.clone());
        // We skip the saving layer for HermesMapProvider, since it'll never fetch something from the outside world.

        let pgp_chunk = ChunkIdFetcher::new(
            ProguardProvider {},
            s3_client.clone(),
            posthog_pool.clone(),
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

        let redis_client = RedisClient::new(config.redis_url.clone()).await?;
        let redis_client = Arc::new(redis_client);

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

        Ok(Self {
            health_registry,
            worker_liveness,
            kafka_consumer,
            transactional_producer: Mutex::new(transactional_producer),
            immediate_producer,
            posthog_pool,
            persons_pool,
            catalog,
            resolver,
            config: config.clone(),
            team_manager,
            geoip_client,
            billing_limiter,
            filtered_teams,
            filter_mode,
        })
    }
}
