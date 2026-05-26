//! Runtime wiring for Cymbal.
//!
//! This crate owns process-level setup and construction of infrastructure-backed
//! stage dependencies. Domain, symbolication, and stage crates stay free of
//! application startup logic and global configuration parsing.

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use aws_config::{BehaviorVersion, Region};
use common_continuous_profiling::{ContinuousProfilingConfig, RunningAgent};
use common_redis::Client as RedisClientTrait;
use common_types::error_tracking::FrameId;
use cymbal_alerting::{AlertingDeps, AlertingStage};
use cymbal_domain::{FrameRecord, ReleaseRecord};
use cymbal_grouping::{GroupingDeps, GroupingError, GroupingRuleRepository, GroupingStage};
use cymbal_linking::{
    IssueRepository, LinkingDeps, LinkingError, LinkingRuleRepository, LinkingSideEffects,
    LinkingStage,
};
use cymbal_rate_limiting::{RateLimitingConfig, RateLimitingError, RateLimitingStage};
use cymbal_repositories::{
    new_issue_buckets_redis_client, Issue, IssueFingerprintOverride, IssueWithFirstSeen,
    RedisBackedStateConfig,
};
use cymbal_resolution::{FrameRepository, ResolutionDeps, ResolutionStage, SymbolResolver};
use cymbal_rules::{Assignment, AssignmentRule, GroupingRule, NewAssignment, SuppressionRule};
use cymbal_symbol_store::{
    apple::AppleProvider,
    caching::{Caching, SymbolSetCache},
    chunk_id::{ChunkIdFetcher, OrChunkId},
    concurrency,
    hermesmap::HermesMapProvider,
    proguard::{FetchedMapping, ProguardProvider, ProguardRef},
    saving::{set_symbol_set_reporter, Saving, SymbolSetRecord},
    sourcemap::SourcemapProvider,
    BlobClient, Catalog, ResolveError, S3Impl, SymbolStoreConfig, UnhandledError,
};
use cymbal_symbolication::{apple::AppleDebugImage, Frame, RawFrame, Symbolicator};
use envconfig::Envconfig;
use moka::future::{Cache, CacheBuilder};
use sqlx::{postgres::PgPoolOptions, PgPool};
use tokio::sync::{Mutex, Semaphore};
use tracing::{error, info, warn};
use uuid::Uuid;

const FRAME_CACHE_HITS: &str = "cymbal_frame_cache_hits";
const FRAME_CACHE_MISSES: &str = "cymbal_frame_cache_misses";
const FRAME_DB_HITS: &str = "cymbal_frame_db_hits";
const FRAME_DB_MISSES: &str = "cymbal_frame_db_misses";
const SUSPICIOUS_FRAMES_DETECTED: &str = "cymbal_suspicious_frames_detected";

#[derive(Envconfig, Clone, Debug)]
pub struct RuntimeConfig {
    #[envconfig(nested = true)]
    pub process: ProcessConfig,
    #[envconfig(nested = true)]
    pub postgres: PostgresConfig,
    #[envconfig(nested = true)]
    pub object_storage: ObjectStorageConfig,
    #[envconfig(nested = true)]
    pub symbol_store: RuntimeSymbolStoreConfig,
    #[envconfig(nested = true)]
    pub redis: RuntimeRedisConfig,
    #[envconfig(nested = true)]
    pub rate_limiting: RateLimitingConfig,
    #[envconfig(nested = true)]
    pub linking: LinkingRuntimeConfig,
    #[envconfig(nested = true)]
    pub alerting: AlertingRuntimeConfig,
    #[envconfig(nested = true)]
    pub stage_concurrency: StageConcurrencyConfig,
}

/// Per-stage caps on the number of in-flight items (or, for batch-fold
/// stages like alerting, in-flight `process()` calls) handled by each stage
/// on a single pod. The cap is enforced across every batch flowing through
/// the stage — concurrent batches share the same permit pool, so the
/// configured value is the actual ceiling on parallel work regardless of how
/// many batches the orchestrator hands the stage.
#[derive(Envconfig, Clone, Debug)]
pub struct StageConcurrencyConfig {
    #[envconfig(from = "RESOLUTION_STAGE_CONCURRENCY", default = "64")]
    pub resolution: usize,
    #[envconfig(from = "GROUPING_STAGE_CONCURRENCY", default = "16")]
    pub grouping: usize,
    #[envconfig(from = "LINKING_STAGE_CONCURRENCY", default = "8")]
    pub linking: usize,
    #[envconfig(from = "RATE_LIMITING_STAGE_CONCURRENCY", default = "32")]
    pub rate_limiting: usize,
    #[envconfig(from = "ALERTING_STAGE_CONCURRENCY", default = "4")]
    pub alerting: usize,
}

#[derive(Envconfig, Clone, Debug)]
pub struct ProcessConfig {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,
    pub posthog_api_key: Option<String>,
    #[envconfig(default = "https://us.i.posthog.com/capture")]
    pub posthog_endpoint: String,
    #[envconfig(default = "15")]
    pub context_line_count: usize,
}

#[derive(Envconfig, Clone, Debug)]
pub struct PostgresConfig {
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,
    #[envconfig(default = "16")]
    pub max_pg_connections: u32,
}

#[derive(Envconfig, Clone, Debug)]
pub struct ObjectStorageConfig {
    #[envconfig(default = "http://127.0.0.1:19000")]
    pub object_storage_endpoint: String,
    #[envconfig(default = "symbol_sets")]
    pub object_storage_bucket: String,
    #[envconfig(default = "us-east-1")]
    pub object_storage_region: String,
    #[envconfig(default = "object_storage_root_user")]
    pub object_storage_access_key_id: String,
    #[envconfig(default = "object_storage_root_password")]
    pub object_storage_secret_access_key: String,
    #[envconfig(default = "false")]
    pub object_storage_force_path_style: bool,
    #[envconfig(default = "symbolsets")]
    pub object_storage_prefix: String,
}

#[derive(Envconfig, Clone, Debug)]
pub struct RuntimeSymbolStoreConfig {
    #[envconfig(default = "false")]
    pub allow_internal_ips: bool,
    #[envconfig(default = "30")]
    pub sourcemap_timeout_seconds: u64,
    #[envconfig(default = "5")]
    pub sourcemap_connect_timeout_seconds: u64,
    #[envconfig(default = "100000000")]
    pub symbol_store_cache_max_bytes: usize,
    #[envconfig(default = "64")]
    pub symbol_resolution_concurrency: usize,
    #[envconfig(default = "100000")]
    pub frame_cache_size: u64,
    #[envconfig(default = "600")]
    pub frame_cache_ttl_seconds: u64,
    #[envconfig(default = "10")]
    pub frame_result_ttl_minutes: u32,
}

#[derive(Envconfig, Clone, Debug)]
pub struct RuntimeRedisConfig {
    #[envconfig(from = "ISSUE_BUCKETS_REDIS_URL", default = "redis://localhost:6379/")]
    pub issue_buckets_redis_url: String,
    #[envconfig(default = "100")]
    pub redis_response_timeout_ms: u64,
    #[envconfig(default = "5000")]
    pub redis_connection_timeout_ms: u64,
}

#[derive(Envconfig, Clone, Debug)]
pub struct LinkingRuntimeConfig {
    #[envconfig(default = "600")]
    pub issue_cache_ttl_seconds: u64,
}

#[derive(Envconfig, Clone, Debug)]
pub struct AlertingRuntimeConfig {
    #[envconfig(default = "")]
    pub spike_alert_enabled_team_ids: String,
    #[envconfig(from = "ALERTING_STAGE_BATCH_SIZE", default = "500")]
    pub stage_batch_size: usize,
}

impl RuntimeConfig {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Self::init_from_env()
    }
}

impl From<&RuntimeConfig> for SymbolStoreConfig {
    fn from(config: &RuntimeConfig) -> Self {
        Self {
            allow_internal_ips: config.symbol_store.allow_internal_ips,
            sourcemap_timeout_seconds: config.symbol_store.sourcemap_timeout_seconds,
            sourcemap_connect_timeout_seconds: config
                .symbol_store
                .sourcemap_connect_timeout_seconds,
            cache_max_bytes: config.symbol_store.symbol_store_cache_max_bytes,
            object_storage_bucket: config.object_storage.object_storage_bucket.clone(),
            object_storage_prefix: config.object_storage.object_storage_prefix.clone(),
        }
    }
}

impl From<&RuntimeRedisConfig> for RedisBackedStateConfig {
    fn from(config: &RuntimeRedisConfig) -> Self {
        Self {
            issue_buckets_redis_url: config.issue_buckets_redis_url.clone(),
            redis_response_timeout_ms: config.redis_response_timeout_ms,
            redis_connection_timeout_ms: config.redis_connection_timeout_ms,
        }
    }
}

#[derive(Debug)]
pub struct RuntimeGuard {
    _profiling_agent: Option<RunningAgent>,
    posthog_capture: Option<cymbal_repositories::posthog::PostHogCaptureGuard>,
}

impl RuntimeGuard {
    pub async fn shutdown(mut self) {
        if let Some(posthog_capture) = self.posthog_capture.take() {
            posthog_capture.shutdown().await;
        }
    }
}

pub async fn init_process(config: &ProcessConfig) -> RuntimeGuard {
    if rustls::crypto::ring::default_provider()
        .install_default()
        .is_err()
    {
        tracing::debug!("rustls crypto provider was already installed");
    }
    cymbal_symbolication::FRAME_CONTEXT_LINES.store(
        config.context_line_count,
        std::sync::atomic::Ordering::Relaxed,
    );

    let profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(error) => {
            error!(%error, "failed to start continuous profiling agent");
            None
        }
    };

    match &config.posthog_api_key {
        Some(key) => {
            let ph_config = posthog_rs::ClientOptionsBuilder::default()
                .api_key(key.clone())
                .api_endpoint(config.posthog_endpoint.clone())
                .build()
                .expect("valid PostHog client options");
            if let Err(error) = posthog_rs::init_global(ph_config).await {
                error!(?error, "failed to initialize PostHog client");
            } else {
                info!("PostHog client initialized");
            }
        }
        None => {
            posthog_rs::disable_global();
            warn!("PostHog client disabled");
        }
    }

    RuntimeGuard {
        _profiling_agent: profiling_agent,
        posthog_capture: Some(cymbal_repositories::posthog::init_posthog_capture(
            config.posthog_api_key.is_some(),
        )),
    }
}

#[derive(Clone)]
pub struct CymbalRuntime {
    pub posthog_pool: PgPool,
    pub catalog: Arc<Catalog>,
    pub redis: Arc<dyn RedisClientTrait + Send + Sync>,
    pub stages: RuntimeStages,
}

impl CymbalRuntime {
    pub async fn from_config(config: &RuntimeConfig) -> Result<Self, RuntimeError> {
        let posthog_pool = PgPoolOptions::new()
            .max_connections(config.postgres.max_pg_connections)
            .connect(&config.postgres.database_url)
            .await?;

        let s3_client = Arc::new(S3Impl::new(aws_sdk_s3::Client::from_conf(
            get_aws_config(&config.object_storage).await,
        )));
        s3_client
            .ping_bucket(&config.object_storage.object_storage_bucket)
            .await?;

        let redis =
            new_issue_buckets_redis_client(&RedisBackedStateConfig::from(&config.redis)).await?;
        Self::new(config, s3_client, posthog_pool, redis).await
    }

    pub async fn new(
        config: &RuntimeConfig,
        blob_client: Arc<dyn BlobClient>,
        posthog_pool: PgPool,
        redis: Arc<dyn RedisClientTrait + Send + Sync>,
    ) -> Result<Self, RuntimeError> {
        set_symbol_set_reporter(Arc::new(
            cymbal_repositories::posthog::PostHogSymbolSetReporter,
        ));
        let catalog = Arc::new(build_symbol_catalog(
            config,
            blob_client,
            posthog_pool.clone(),
        ));
        let stages = build_stages(config, posthog_pool.clone(), redis.clone(), catalog.clone())?;
        info!("Cymbal runtime initialized");
        Ok(Self {
            posthog_pool,
            catalog,
            redis,
            stages,
        })
    }
}

#[derive(Clone, Debug)]
pub struct RuntimeStages {
    pub rate_limiting: RateLimitingStage,
    pub resolution: ResolutionStage,
    pub grouping: GroupingStage,
    pub linking: LinkingStage,
    pub alerting: AlertingStage,
}

fn build_stages(
    config: &RuntimeConfig,
    pool: PgPool,
    redis: Arc<dyn RedisClientTrait + Send + Sync>,
    catalog: Arc<Catalog>,
) -> Result<RuntimeStages, RuntimeError> {
    let rate_limiting = RateLimitingStage::from_redis(config.rate_limiting.clone(), redis.clone())?
        .with_stage_concurrency(config.stage_concurrency.rate_limiting);
    let frame_repository = Arc::new(PostgresFrameRepository::new(pool.clone()));
    let symbol_resolver = Arc::new(RuntimeSymbolResolver::new(
        catalog,
        frame_repository,
        &config.symbol_store,
    ));
    let symbol_resolution_limiter = Arc::new(Semaphore::new(
        config.symbol_store.symbol_resolution_concurrency.max(1),
    ));
    let resolution = ResolutionStage::with_deps(
        ResolutionDeps::new(symbol_resolver, symbol_resolution_limiter)
            .with_stage_concurrency(config.stage_concurrency.resolution),
    );
    let rule_repository = Arc::new(PostgresRuleRepository::new(pool.clone()));
    let grouping = GroupingStage::with_deps(
        GroupingDeps::new(rule_repository.clone())
            .with_stage_concurrency(config.stage_concurrency.grouping),
    );

    let issue_repository = Arc::new(PostgresIssueRepository::new(pool.clone()));
    let issue_cache = CacheBuilder::new(1_000)
        .time_to_live(Duration::from_secs(config.linking.issue_cache_ttl_seconds))
        .build();
    let linking = LinkingStage::with_deps(
        LinkingDeps::new(issue_repository)
            .with_rule_repository(rule_repository)
            .with_side_effects(Arc::new(PostHogLinkingSideEffects))
            .with_issue_cache(issue_cache),
    )
    .with_stage_concurrency(config.stage_concurrency.linking);

    let alerting = AlertingStage::with_deps(AlertingDeps::new(redis).with_enabled_team_ids(
        parse_enabled_team_ids(&config.alerting.spike_alert_enabled_team_ids),
    ))
    .with_stage_concurrency(config.stage_concurrency.alerting)
    .with_stage_batch_size(config.alerting.stage_batch_size);

    Ok(RuntimeStages {
        rate_limiting,
        resolution,
        grouping,
        linking,
        alerting,
    })
}

fn build_symbol_catalog(
    config: &RuntimeConfig,
    blob_client: Arc<dyn BlobClient>,
    pool: PgPool,
) -> Catalog {
    let symbol_store_config = SymbolStoreConfig::from(config);
    let ss_cache = Arc::new(Mutex::new(SymbolSetCache::new(
        symbol_store_config.cache_max_bytes,
    )));
    let bucket = config.object_storage.object_storage_bucket.clone();
    let prefix = config.object_storage.object_storage_prefix.clone();

    let sourcemap_provider = SourcemapProvider::new(symbol_store_config.clone())
        .with_chunk_id_rescue(pool.clone(), blob_client.clone(), bucket.clone());
    let sourcemap_chunk = ChunkIdFetcher::new(
        sourcemap_provider,
        blob_client.clone(),
        pool.clone(),
        bucket.clone(),
    );
    let sourcemap_saving = Saving::new(
        sourcemap_chunk,
        pool.clone(),
        blob_client.clone(),
        bucket.clone(),
        prefix,
    );
    let sourcemap_caching = Caching::new(sourcemap_saving, ss_cache.clone());
    let sourcemap_at_most_once = concurrency::AtMostOne::new(sourcemap_caching);

    let hermes_chunk = ChunkIdFetcher::new(
        HermesMapProvider {},
        blob_client.clone(),
        pool.clone(),
        bucket.clone(),
    );
    let hermes_caching = Caching::new(hermes_chunk, ss_cache.clone());
    let hermes_at_most_once = concurrency::AtMostOne::new(hermes_caching);

    let proguard_chunk = ChunkIdFetcher::new(
        ProguardProvider {},
        blob_client.clone(),
        pool.clone(),
        bucket.clone(),
    );
    let proguard_caching = Caching::new(proguard_chunk, ss_cache.clone());
    let proguard_at_most_once = concurrency::AtMostOne::new(proguard_caching);

    let apple_chunk = ChunkIdFetcher::new(AppleProvider {}, blob_client, pool, bucket);
    let apple_caching = Caching::new(apple_chunk, ss_cache);
    let apple_at_most_once = concurrency::AtMostOne::new(apple_caching);

    Catalog::new(
        sourcemap_at_most_once,
        hermes_at_most_once,
        proguard_at_most_once,
        apple_at_most_once,
    )
}

async fn get_aws_config(config: &ObjectStorageConfig) -> aws_sdk_s3::Config {
    if std::env::var("AWS_ROLE_ARN").is_ok() && std::env::var("AWS_WEB_IDENTITY_TOKEN_FILE").is_ok()
    {
        info!("AWS role and token file detected, config loaded from environment variables");
        aws_sdk_s3::config::Builder::from(&aws_config::load_from_env().await)
            .force_path_style(config.object_storage_force_path_style)
            .build()
    } else {
        warn!("Falling back to building config from explicit environment variables");
        let env_credentials = aws_sdk_s3::config::Credentials::new(
            &config.object_storage_access_key_id,
            &config.object_storage_secret_access_key,
            None,
            None,
            "environment",
        );
        aws_sdk_s3::config::Builder::new()
            .region(Region::new(config.object_storage_region.clone()))
            .endpoint_url(&config.object_storage_endpoint)
            .credentials_provider(env_credentials)
            .behavior_version(BehaviorVersion::latest())
            .force_path_style(config.object_storage_force_path_style)
            .build()
    }
}

fn parse_enabled_team_ids(raw: &str) -> Option<HashSet<i32>> {
    let ids: HashSet<i32> = raw
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .filter_map(|value| value.parse::<i32>().ok())
        .collect();
    if ids.is_empty() {
        None
    } else {
        Some(ids)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum RuntimeError {
    #[error("postgres error: {0}")]
    Postgres(#[from] sqlx::Error),
    #[error("symbol store error: {0}")]
    SymbolStore(#[from] cymbal_symbol_store::SymbolStoreError),
    #[error("redis error: {0}")]
    Redis(#[from] common_redis::CustomRedisError),
    #[error("rate limiter error: {0}")]
    RateLimiter(#[from] RateLimitingError),
}

#[derive(Clone)]
struct RuntimeSymbolResolver {
    catalog: Arc<Catalog>,
    frame_repository: Arc<PostgresFrameRepository>,
    cache: Cache<(i32, String), Vec<FrameRecord<FrameId>>>,
    result_ttl: chrono::Duration,
}

impl RuntimeSymbolResolver {
    fn new(
        catalog: Arc<Catalog>,
        frame_repository: Arc<PostgresFrameRepository>,
        config: &RuntimeSymbolStoreConfig,
    ) -> Self {
        Self {
            catalog,
            frame_repository,
            cache: CacheBuilder::new(config.frame_cache_size)
                .time_to_live(Duration::from_secs(config.frame_cache_ttl_seconds))
                .build(),
            result_ttl: chrono::Duration::minutes(config.frame_result_ttl_minutes as i64),
        }
    }

    async fn resolve(
        &self,
        team_id: i32,
        frame: &RawFrame,
        debug_images: &[AppleDebugImage],
    ) -> Result<Vec<Frame>, UnhandledError> {
        if frame.is_suspicious() {
            metrics::counter!(SUSPICIOUS_FRAMES_DETECTED, "frame_type" => "raw").increment(1);
        }

        let raw_id = frame.raw_id(team_id);
        let cache_key = (raw_id.team_id, raw_id.hash_id.clone());
        let mut cache_miss = false;
        let records = self
            .cache
            .try_get_with(cache_key, async {
                cache_miss = true;
                self.resolve_uncached(team_id, frame, debug_images).await
            })
            .await
            .map_err(|error| UnhandledError::Other(error.to_string()))?;

        if cache_miss {
            metrics::counter!(FRAME_CACHE_MISSES).increment(1);
        } else {
            metrics::counter!(FRAME_CACHE_HITS).increment(1);
        }

        Ok(records.into_iter().map(|record| record.contents).collect())
    }

    async fn resolve_uncached(
        &self,
        team_id: i32,
        frame: &RawFrame,
        debug_images: &[AppleDebugImage],
    ) -> Result<Vec<FrameRecord<FrameId>>, UnhandledError> {
        let raw_id = frame.raw_id(team_id);
        let loaded = self
            .frame_repository
            .load_all(&raw_id.hash_id, raw_id.team_id, self.result_ttl)
            .await?;
        if !loaded.is_empty() {
            metrics::counter!(FRAME_DB_HITS).increment(1);
            return Ok(loaded);
        }

        metrics::counter!(FRAME_DB_MISSES).increment(1);
        let mut resolved = self
            .catalog
            .resolve_raw_frame(team_id, frame, debug_images)
            .await?;
        if resolved.is_empty() {
            return Err(UnhandledError::Other(
                "No resolved frames produced from raw frame".to_string(),
            ));
        }

        let symbol_set_id = self
            .frame_repository
            .symbol_set_id(team_id, frame.symbol_set_ref())
            .await?;
        let release = match symbol_set_id {
            Some(symbol_set_id) => {
                self.frame_repository
                    .release_for_symbol_set_id(symbol_set_id, team_id)
                    .await?
            }
            None => None,
        };

        let mut records = Vec::with_capacity(resolved.len());
        for resolved_frame in &mut resolved {
            resolved_frame.release = release.clone();
            if resolved_frame.suspicious {
                metrics::counter!(SUSPICIOUS_FRAMES_DETECTED, "frame_type" => "resolved")
                    .increment(1);
            }

            let record = self
                .frame_repository
                .save_resolved_frame_with_symbol_set(team_id, symbol_set_id, resolved_frame)
                .await?;
            records.push(record);
        }

        Ok(records)
    }
}

#[async_trait]
impl SymbolResolver for RuntimeSymbolResolver {
    async fn resolve_raw_frame(
        &self,
        team_id: i32,
        frame: &RawFrame,
        debug_images: &[AppleDebugImage],
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve(team_id, frame, debug_images).await
    }

    async fn resolve_java_class(
        &self,
        team_id: i32,
        symbolset_ref: OrChunkId<ProguardRef>,
        class: String,
    ) -> Result<String, ResolveError> {
        let map: Arc<FetchedMapping> = self.catalog.pg.lookup(team_id, symbolset_ref).await?;
        map.remap_class(class.as_str())?
            .ok_or_else(|| cymbal_symbol_store::ProguardError::MissingClass.into())
    }

    async fn resolve_dart_minified_name(
        &self,
        team_id: i32,
        chunk_id: String,
        minified_name: &str,
    ) -> Result<String, ResolveError> {
        let sourcemap = self
            .catalog
            .smp
            .lookup(team_id, OrChunkId::ChunkId(chunk_id))
            .await?;
        let minified_names = sourcemap
            .get_dart_minified_names()
            .ok_or(ResolveError::from(
                cymbal_symbol_store::JsResolveErr::InvalidSourceAndMap,
            ))?;
        cymbal_symbol_store::dart_minified_names::lookup_minified_type(
            minified_names,
            minified_name,
        )
        .ok_or(ResolveError::from(
            cymbal_symbol_store::JsResolveErr::InvalidSourceAndMap,
        ))
    }
}

#[derive(Clone)]
struct PostgresFrameRepository {
    pool: PgPool,
}

#[derive(sqlx::FromRow)]
struct StoredFrameRow {
    raw_id: String,
    part: i32,
    team_id: i32,
    created_at: chrono::DateTime<chrono::Utc>,
    symbol_set_id: Option<Uuid>,
    contents: serde_json::Value,
    resolved: bool,
    context: Option<serde_json::Value>,
}

#[derive(sqlx::FromRow)]
struct ReleaseRecordRow {
    id: Uuid,
    team_id: i32,
    hash_id: String,
    created_at: chrono::DateTime<chrono::Utc>,
    version: String,
    project: String,
    metadata: Option<serde_json::Value>,
}

impl From<ReleaseRecordRow> for ReleaseRecord {
    fn from(row: ReleaseRecordRow) -> Self {
        Self {
            id: row.id,
            team_id: row.team_id,
            hash_id: row.hash_id,
            created_at: row.created_at,
            version: row.version,
            project: row.project,
            metadata: row.metadata,
        }
    }
}

impl PostgresFrameRepository {
    fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    async fn symbol_set_id(
        &self,
        team_id: i32,
        symbol_set_ref: Option<String>,
    ) -> Result<Option<Uuid>, UnhandledError> {
        let Some(symbol_set_ref) = symbol_set_ref else {
            return Ok(None);
        };

        let Some(mut record) = SymbolSetRecord::load(&self.pool, team_id, &symbol_set_ref).await?
        else {
            return Ok(None);
        };
        record.set_last_used(&self.pool).await?;
        Ok(Some(record.id))
    }

    async fn release_for_symbol_set_id(
        &self,
        symbol_set_id: Uuid,
        team_id: i32,
    ) -> Result<Option<ReleaseRecord>, UnhandledError> {
        sqlx::query_as::<_, ReleaseRecordRow>(
            r#"
            SELECT r.id, r.team_id, r.hash_id, r.created_at, r.version, r.project, r.metadata
            FROM posthog_errortrackingsymbolset ss
            INNER JOIN posthog_errortrackingrelease r ON ss.release_id = r.id
            WHERE ss.id = $1 AND ss.team_id = $2
            "#,
        )
        .bind(symbol_set_id)
        .bind(team_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(UnhandledError::from)
        .map(|row| row.map(Into::into))
    }

    async fn load_all(
        &self,
        raw_id: &str,
        team_id: i32,
        result_ttl: chrono::Duration,
    ) -> Result<Vec<FrameRecord<FrameId>>, UnhandledError> {
        let rows = sqlx::query_as::<_, StoredFrameRow>(
            r#"
            SELECT raw_id, part, team_id, created_at, symbol_set_id, contents, resolved, context
            FROM posthog_errortrackingstackframe
            WHERE raw_id = $1 AND team_id = $2
            ORDER BY part ASC
            "#,
        )
        .bind(raw_id)
        .bind(team_id)
        .fetch_all(&self.pool)
        .await?;

        if rows.is_empty()
            || rows
                .iter()
                .any(|frame| frame.created_at < chrono::Utc::now() - result_ttl)
        {
            return Ok(Vec::new());
        }

        let release = match rows.first().and_then(|row| row.symbol_set_id) {
            Some(symbol_set_id) => {
                self.release_for_symbol_set_id(symbol_set_id, team_id)
                    .await?
            }
            None => None,
        };

        rows.into_iter()
            .map(|row| self.stored_row_to_frame_record(row, release.clone()))
            .collect()
    }

    fn stored_row_to_frame_record(
        &self,
        row: StoredFrameRow,
        release: Option<ReleaseRecord>,
    ) -> Result<FrameRecord<FrameId>, UnhandledError> {
        let frame_id = FrameId::new(row.raw_id, row.team_id, row.part);
        let context = row.context.map(serde_json::from_value).transpose()?;
        let mut contents: Frame = serde_json::from_value(row.contents)?;
        contents.frame_id = frame_id.clone();
        contents.context = context.clone();
        contents.release = release;

        Ok(FrameRecord {
            id: frame_id,
            created_at: row.created_at,
            symbol_set_id: row.symbol_set_id.map(|id| id.to_string()),
            contents,
            resolved: row.resolved,
            context,
        })
    }

    async fn save_resolved_frame_with_symbol_set(
        &self,
        team_id: i32,
        symbol_set_id: Option<Uuid>,
        frame: &Frame,
    ) -> Result<FrameRecord<FrameId>, UnhandledError> {
        let created_at = chrono::Utc::now();
        let context = frame.context.clone();
        let context_value = context.as_ref().map(serde_json::to_value).transpose()?;
        let contents = serde_json::to_value(frame)?;

        sqlx::query(
            r#"
            INSERT INTO posthog_errortrackingstackframe (raw_id, part, team_id, created_at, symbol_set_id, contents, resolved, id, context)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (team_id, raw_id, part) DO UPDATE SET
                created_at = $4,
                symbol_set_id = $5,
                contents = $6,
                resolved = $7,
                context = $9
            "#,
        )
        .bind(&frame.frame_id.hash_id)
        .bind(frame.frame_id.part)
        .bind(team_id)
        .bind(created_at)
        .bind(symbol_set_id)
        .bind(contents)
        .bind(frame.resolved)
        .bind(Uuid::now_v7())
        .bind(context_value)
        .execute(&self.pool)
        .await?;

        Ok(FrameRecord {
            id: frame.frame_id.clone(),
            created_at,
            symbol_set_id: symbol_set_id.map(|id| id.to_string()),
            contents: frame.clone(),
            resolved: frame.resolved,
            context,
        })
    }
}

#[async_trait]
impl FrameRepository for PostgresFrameRepository {
    async fn save_resolved_frame(
        &self,
        team_id: i32,
        raw_frame: &RawFrame,
        frame: &Frame,
    ) -> Result<(), UnhandledError> {
        let symbol_set_id = self
            .symbol_set_id(team_id, raw_frame.symbol_set_ref())
            .await?;
        self.save_resolved_frame_with_symbol_set(team_id, symbol_set_id, frame)
            .await?;
        Ok(())
    }
}

#[derive(Clone)]
struct PostgresRuleRepository {
    pool: PgPool,
}

impl PostgresRuleRepository {
    fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

#[async_trait]
impl GroupingRuleRepository for PostgresRuleRepository {
    async fn grouping_rules(&self, team_id: i32) -> Result<Vec<GroupingRule>, GroupingError> {
        sqlx::query_as::<_, GroupingRuleRow>(
            r#"
            SELECT id, team_id, user_id, role_id, order_key, bytecode, created_at, updated_at
            FROM posthog_errortrackinggroupingrule
            WHERE team_id = $1 AND disabled_data IS NULL
            "#,
        )
        .bind(team_id)
        .fetch_all(&self.pool)
        .await
        .map(|rows| rows.into_iter().map(Into::into).collect())
        .map_err(|error| GroupingError::Repository(error.to_string()))
    }

    async fn disable_grouping_rule(
        &self,
        rule: &GroupingRule,
        message: String,
        props: serde_json::Value,
    ) -> Result<(), GroupingError> {
        let disabled_data = serde_json::json!({ "message": message, "props": props });
        sqlx::query(
            r#"
            UPDATE posthog_errortrackinggroupingrule
            SET disabled_data = $1, updated_at = NOW()
            WHERE id = $2
            "#,
        )
        .bind(disabled_data)
        .bind(rule.id)
        .execute(&self.pool)
        .await
        .map(|_| ())
        .map_err(|error| GroupingError::Repository(error.to_string()))
    }
}

#[async_trait]
impl LinkingRuleRepository for PostgresRuleRepository {
    async fn suppression_rules(&self, team_id: i32) -> Result<Vec<SuppressionRule>, LinkingError> {
        sqlx::query_as::<_, SuppressionRuleRow>(
            r#"
            SELECT id, team_id, order_key, bytecode, sampling_rate, created_at, updated_at
            FROM posthog_errortrackingsuppressionrule
            WHERE team_id = $1 AND disabled_data IS NULL AND bytecode IS NOT NULL
            "#,
        )
        .bind(team_id)
        .fetch_all(&self.pool)
        .await
        .map(|rows| rows.into_iter().map(Into::into).collect())
        .map_err(repository_error)
    }

    async fn disable_suppression_rule(
        &self,
        rule: &SuppressionRule,
        message: String,
        props: serde_json::Value,
    ) -> Result<(), LinkingError> {
        let disabled_data = serde_json::json!({ "message": message, "props": props });
        sqlx::query(
            r#"
            UPDATE posthog_errortrackingsuppressionrule
            SET disabled_data = $1, updated_at = NOW()
            WHERE id = $2
            "#,
        )
        .bind(disabled_data)
        .bind(rule.id)
        .execute(&self.pool)
        .await
        .map(|_| ())
        .map_err(repository_error)
    }

    async fn assignment_rules(&self, team_id: i32) -> Result<Vec<AssignmentRule>, LinkingError> {
        sqlx::query_as::<_, AssignmentRuleRow>(
            r#"
            SELECT id, team_id, user_id, role_id, order_key, bytecode, created_at, updated_at
            FROM posthog_errortrackingassignmentrule
            WHERE team_id = $1 AND disabled_data IS NULL
            "#,
        )
        .bind(team_id)
        .fetch_all(&self.pool)
        .await
        .map(|rows| rows.into_iter().map(Into::into).collect())
        .map_err(repository_error)
    }

    async fn disable_assignment_rule(
        &self,
        rule: &AssignmentRule,
        message: String,
        issue: serde_json::Value,
        props: serde_json::Value,
    ) -> Result<(), LinkingError> {
        let disabled_data =
            serde_json::json!({ "message": message, "issue": issue, "props": props });
        sqlx::query(
            r#"
            UPDATE posthog_errortrackingassignmentrule
            SET disabled_data = $1, updated_at = NOW()
            WHERE id = $2
            "#,
        )
        .bind(disabled_data)
        .bind(rule.id)
        .execute(&self.pool)
        .await
        .map(|_| ())
        .map_err(repository_error)
    }
}

#[derive(sqlx::FromRow)]
struct GroupingRuleRow {
    id: Uuid,
    team_id: i32,
    user_id: Option<i32>,
    role_id: Option<Uuid>,
    order_key: i32,
    bytecode: serde_json::Value,
    created_at: chrono::DateTime<chrono::Utc>,
    updated_at: chrono::DateTime<chrono::Utc>,
}

impl From<GroupingRuleRow> for GroupingRule {
    fn from(row: GroupingRuleRow) -> Self {
        Self {
            id: row.id,
            team_id: row.team_id,
            user_id: row.user_id,
            role_id: row.role_id,
            order_key: row.order_key,
            bytecode: row.bytecode,
            created_at: row.created_at,
            updated_at: row.updated_at,
        }
    }
}

#[derive(sqlx::FromRow)]
struct SuppressionRuleRow {
    id: Uuid,
    team_id: i32,
    order_key: i32,
    bytecode: serde_json::Value,
    sampling_rate: f64,
    created_at: chrono::DateTime<chrono::Utc>,
    updated_at: chrono::DateTime<chrono::Utc>,
}

impl From<SuppressionRuleRow> for SuppressionRule {
    fn from(row: SuppressionRuleRow) -> Self {
        Self {
            id: row.id,
            team_id: row.team_id,
            order_key: row.order_key,
            bytecode: row.bytecode,
            sampling_rate: row.sampling_rate,
            created_at: row.created_at,
            updated_at: row.updated_at,
        }
    }
}

#[derive(sqlx::FromRow)]
struct AssignmentRuleRow {
    id: Uuid,
    team_id: i32,
    user_id: Option<i32>,
    role_id: Option<Uuid>,
    order_key: i32,
    bytecode: serde_json::Value,
    created_at: chrono::DateTime<chrono::Utc>,
    updated_at: chrono::DateTime<chrono::Utc>,
}

impl From<AssignmentRuleRow> for AssignmentRule {
    fn from(row: AssignmentRuleRow) -> Self {
        Self {
            id: row.id,
            team_id: row.team_id,
            user_id: row.user_id,
            role_id: row.role_id,
            order_key: row.order_key,
            bytecode: row.bytecode,
            created_at: row.created_at,
            updated_at: row.updated_at,
        }
    }
}

#[derive(Clone)]
struct PostgresIssueRepository {
    pool: PgPool,
}

impl PostgresIssueRepository {
    fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

#[async_trait]
impl IssueRepository for PostgresIssueRepository {
    async fn load_by_fingerprint(
        &self,
        team_id: i32,
        fingerprint: &str,
    ) -> Result<Option<IssueWithFirstSeen>, LinkingError> {
        Issue::load_by_fingerprint(&self.pool, team_id, fingerprint)
            .await
            .map_err(repository_error)
    }

    async fn load(&self, team_id: i32, issue_id: Uuid) -> Result<Option<Issue>, LinkingError> {
        Issue::load(&self.pool, team_id, issue_id)
            .await
            .map_err(repository_error)
    }

    async fn insert_new(
        &self,
        team_id: i32,
        name: String,
        description: String,
    ) -> Result<Issue, LinkingError> {
        Issue::insert_new(team_id, name, description, &self.pool)
            .await
            .map_err(repository_error)
    }

    async fn maybe_reopen(&self, issue: &mut Issue) -> Result<bool, LinkingError> {
        issue
            .maybe_reopen(&self.pool)
            .await
            .map_err(repository_error)
    }

    async fn create_or_load_fingerprint(
        &self,
        team_id: i32,
        fingerprint: &str,
        issue: &Issue,
        first_seen: chrono::DateTime<chrono::Utc>,
    ) -> Result<IssueFingerprintOverride, LinkingError> {
        IssueFingerprintOverride::create_or_load(
            &self.pool,
            team_id,
            fingerprint,
            issue,
            first_seen,
        )
        .await
        .map_err(repository_error)
    }

    async fn existing_assignments(&self, issue_id: Uuid) -> Result<Vec<Assignment>, LinkingError> {
        sqlx::query_as::<_, AssignmentRow>(
            r#"
            SELECT id, issue_id, user_id, role_id, created_at
            FROM posthog_errortrackingissueassignment
            WHERE issue_id = $1
            "#,
        )
        .bind(issue_id)
        .fetch_all(&self.pool)
        .await
        .map(|rows| rows.into_iter().map(Into::into).collect())
        .map_err(repository_error)
    }

    async fn apply_assignment(
        &self,
        new_assignment: &NewAssignment,
        issue_id: Uuid,
    ) -> Result<Assignment, LinkingError> {
        sqlx::query_as::<_, AssignmentRow>(
            r#"
            INSERT INTO posthog_errortrackingissueassignment (id, issue_id, user_id, role_id, created_at)
            VALUES ($1, $2, $3, $4, NOW())
            RETURNING id, issue_id, user_id, role_id, created_at
            "#,
        )
        .bind(Uuid::new_v4())
        .bind(issue_id)
        .bind(new_assignment.user_id)
        .bind(new_assignment.role_id)
        .fetch_one(&self.pool)
        .await
        .map(Into::into)
        .map_err(repository_error)
    }
}

#[derive(sqlx::FromRow)]
struct AssignmentRow {
    id: Uuid,
    issue_id: Uuid,
    user_id: Option<i32>,
    role_id: Option<Uuid>,
    created_at: chrono::DateTime<chrono::Utc>,
}

impl From<AssignmentRow> for Assignment {
    fn from(row: AssignmentRow) -> Self {
        Self {
            id: row.id,
            issue_id: row.issue_id,
            user_id: row.user_id,
            role_id: row.role_id,
            created_at: row.created_at,
        }
    }
}

fn repository_error(error: sqlx::Error) -> LinkingError {
    LinkingError::Repository(error.to_string())
}

#[derive(Debug)]
struct PostHogLinkingSideEffects;

#[async_trait]
impl LinkingSideEffects for PostHogLinkingSideEffects {
    async fn issue_created(
        &self,
        issue: &Issue,
        _assignment: Option<&Assignment>,
        _properties: &cymbal_linking::LinkingExceptionProperties,
        _first_seen: chrono::DateTime<chrono::Utc>,
    ) -> Result<(), LinkingError> {
        cymbal_repositories::posthog::capture_issue_created(issue.team_id, issue.id, false);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    #[test]
    fn parses_empty_enabled_team_ids_as_all_teams() {
        assert_eq!(parse_enabled_team_ids(""), None);
        assert_eq!(parse_enabled_team_ids(" , "), None);
    }

    #[test]
    fn parses_enabled_team_ids() {
        assert_eq!(
            parse_enabled_team_ids("1, 2, invalid"),
            Some(HashSet::from([1, 2]))
        );
    }

    #[test]
    fn alerting_config_parses_stage_batch_size() {
        let defaults = AlertingRuntimeConfig::init_from_hashmap(&HashMap::new()).unwrap();
        assert_eq!(defaults.stage_batch_size, 500);

        let config = AlertingRuntimeConfig::init_from_hashmap(&HashMap::from([(
            "ALERTING_STAGE_BATCH_SIZE".to_string(),
            "250".to_string(),
        )]))
        .unwrap();
        assert_eq!(config.stage_batch_size, 250);
    }

    #[test]
    fn rate_limit_config_defaults_to_disabled_safe_mode() {
        let config = RateLimitingConfig::init_from_hashmap(&HashMap::new()).unwrap();

        assert!(!config.enabled);
        assert!(!config.reporting_only);
        assert_eq!(config.threshold, 1_000_000);
        assert_eq!(
            config.redis_key_prefix,
            "@ph/grl/cymbal/error_tracking/team_id"
        );
    }

    #[test]
    fn stage_concurrency_config_defaults_to_moderate_caps() {
        let config = StageConcurrencyConfig::init_from_hashmap(&HashMap::new()).unwrap();

        assert_eq!(config.resolution, 64);
        assert_eq!(config.grouping, 16);
        assert_eq!(config.linking, 8);
        assert_eq!(config.rate_limiting, 32);
        assert_eq!(config.alerting, 4);
    }

    #[test]
    fn stage_concurrency_config_parses_stage_overrides() {
        let config = StageConcurrencyConfig::init_from_hashmap(&HashMap::from([
            ("RESOLUTION_STAGE_CONCURRENCY".to_string(), "7".to_string()),
            ("GROUPING_STAGE_CONCURRENCY".to_string(), "11".to_string()),
            ("LINKING_STAGE_CONCURRENCY".to_string(), "13".to_string()),
            (
                "RATE_LIMITING_STAGE_CONCURRENCY".to_string(),
                "17".to_string(),
            ),
            ("ALERTING_STAGE_CONCURRENCY".to_string(), "19".to_string()),
        ]))
        .unwrap();

        assert_eq!(config.resolution, 7);
        assert_eq!(config.grouping, 11);
        assert_eq!(config.linking, 13);
        assert_eq!(config.rate_limiting, 17);
        assert_eq!(config.alerting, 19);
    }

    #[test]
    fn process_config_defaults_to_no_api_key() {
        let config = ProcessConfig::init_from_hashmap(&HashMap::new()).unwrap();

        assert!(
            config.posthog_api_key.is_none(),
            "API key must default to None"
        );
        assert_eq!(config.posthog_endpoint, "https://us.i.posthog.com/capture");
        assert_eq!(config.context_line_count, 15);
    }

    #[test]
    fn process_config_api_key_parsed_from_env() {
        let config = ProcessConfig::init_from_hashmap(&HashMap::from([(
            "POSTHOG_API_KEY".to_string(),
            "phc_testkey".to_string(),
        )]))
        .unwrap();

        assert_eq!(config.posthog_api_key.as_deref(), Some("phc_testkey"));
    }

    #[test]
    fn redis_runtime_config_converts_to_backed_state_config() {
        let runtime_redis = RuntimeRedisConfig {
            issue_buckets_redis_url: "redis://redis.test:6380/1".to_string(),
            redis_response_timeout_ms: 200,
            redis_connection_timeout_ms: 3000,
        };

        let backed: RedisBackedStateConfig = RedisBackedStateConfig::from(&runtime_redis);

        assert_eq!(backed.issue_buckets_redis_url, "redis://redis.test:6380/1");
        assert_eq!(backed.redis_response_timeout_ms, 200);
        assert_eq!(backed.redis_connection_timeout_ms, 3000);
    }

    #[test]
    fn runtime_redis_config_has_safe_defaults() {
        let config = RuntimeRedisConfig::init_from_hashmap(&HashMap::new()).unwrap();

        assert_eq!(config.issue_buckets_redis_url, "redis://localhost:6379/");
        assert_eq!(config.redis_response_timeout_ms, 100);
        assert_eq!(config.redis_connection_timeout_ms, 5000);
    }

    #[test]
    fn symbol_store_config_preserves_bucket_and_prefix() {
        // Build a minimal RuntimeConfig with non-default bucket/prefix values and
        // verify they are propagated into the SymbolStoreConfig conversion.
        let config = RuntimeConfig::init_from_hashmap(&HashMap::from([
            ("OBJECT_STORAGE_BUCKET".to_string(), "my-bucket".to_string()),
            ("OBJECT_STORAGE_PREFIX".to_string(), "my-prefix".to_string()),
        ]))
        .unwrap();

        let ss_config = SymbolStoreConfig::from(&config);

        assert_eq!(ss_config.object_storage_bucket, "my-bucket");
        assert_eq!(ss_config.object_storage_prefix, "my-prefix");
    }

    #[test]
    fn symbol_store_config_defaults_to_large_cache_and_no_internal_ips() {
        let config = RuntimeConfig::init_from_hashmap(&HashMap::new()).unwrap();
        let ss_config = SymbolStoreConfig::from(&config);

        assert!(!ss_config.allow_internal_ips);
        assert!(ss_config.cache_max_bytes > 0);
    }

    #[test]
    fn linking_runtime_config_defaults_to_600s_cache_ttl() {
        let config = LinkingRuntimeConfig::init_from_hashmap(&HashMap::new()).unwrap();

        assert_eq!(config.issue_cache_ttl_seconds, 600);
    }

    #[test]
    fn alerting_runtime_config_defaults_to_empty_team_ids_and_500_batch_size() {
        let config = AlertingRuntimeConfig::init_from_hashmap(&HashMap::new()).unwrap();

        assert_eq!(config.spike_alert_enabled_team_ids, "");
        assert_eq!(config.stage_batch_size, 500);
    }

    #[test]
    fn rate_limit_config_parses_reporting_and_cache_settings() {
        let config = RateLimitingConfig::init_from_hashmap(&HashMap::from([
            ("CYMBAL_RATE_LIMIT_ENABLED".to_string(), "true".to_string()),
            (
                "CYMBAL_RATE_LIMIT_REPORTING_ONLY".to_string(),
                "true".to_string(),
            ),
            ("CYMBAL_RATE_LIMIT_THRESHOLD".to_string(), "42".to_string()),
            (
                "CYMBAL_RATE_LIMIT_WINDOW_SECONDS".to_string(),
                "30".to_string(),
            ),
            (
                "CYMBAL_RATE_LIMIT_REDIS_KEY_PREFIX".to_string(),
                "@ph/test/cymbal".to_string(),
            ),
            (
                "CYMBAL_RATE_LIMIT_REDIS_KEY_TTL_SECONDS".to_string(),
                "90".to_string(),
            ),
            (
                "CYMBAL_RATE_LIMIT_SYNC_INTERVAL_SECONDS".to_string(),
                "5".to_string(),
            ),
            (
                "CYMBAL_RATE_LIMIT_TICK_INTERVAL_MS".to_string(),
                "250".to_string(),
            ),
            (
                "CYMBAL_RATE_LIMIT_LOCAL_CACHE_TTL_SECONDS".to_string(),
                "120".to_string(),
            ),
            (
                "CYMBAL_RATE_LIMIT_LOCAL_CACHE_IDLE_TIMEOUT_SECONDS".to_string(),
                "60".to_string(),
            ),
            (
                "CYMBAL_RATE_LIMIT_LOCAL_CACHE_MAX_ENTRIES".to_string(),
                "5000".to_string(),
            ),
            (
                "CYMBAL_RATE_LIMIT_CHANNEL_CAPACITY".to_string(),
                "10000".to_string(),
            ),
        ]))
        .unwrap();

        assert!(config.enabled);
        assert!(config.reporting_only);
        assert_eq!(config.threshold, 42);
        assert_eq!(config.window_interval, Duration::from_secs(30));
        assert_eq!(config.redis_key_prefix, "@ph/test/cymbal");
        assert_eq!(config.redis_key_ttl, Duration::from_secs(90));
        assert_eq!(config.sync_interval, Duration::from_secs(5));
        assert_eq!(config.tick_interval, Duration::from_millis(250));
        assert_eq!(config.local_cache_ttl, Duration::from_secs(120));
        assert_eq!(config.local_cache_idle_timeout, Duration::from_secs(60));
        assert_eq!(config.local_cache_max_entries, 5_000);
        assert_eq!(config.channel_capacity, 10_000);
    }
}
