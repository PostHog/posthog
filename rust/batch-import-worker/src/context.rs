use std::sync::Arc;
use std::time::Duration;

use anyhow::Error;
use sqlx::postgres::PgPoolOptions;
use tracing::info;

use crate::cache::{GroupCache, IdentifyCache, MemoryGroupCache, MemoryIdentifyCache};
use crate::config::Config;
use crate::person_processing_filter::PersonProcessingFilter;

pub struct AppContext {
    pub config: Config,
    pub db: sqlx::PgPool,
    pub encryption_keys: Vec<String>, // fernet, base64-urlsafe encoded 32-byte long key
    pub identify_cache: Arc<dyn IdentifyCache>,
    pub group_cache: Arc<dyn GroupCache>,
    pub person_processing_filter: PersonProcessingFilter,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, Error> {
        let options = PgPoolOptions::new()
            .max_connections(config.max_pg_connections)
            .acquire_timeout(Duration::from_secs(30))
            .idle_timeout(Duration::from_secs(600));
        let db = options.connect(&config.database_url).await?;

        info!(
            "Using in-memory cache for identify events (capacity: {}, TTL: {}s)",
            config.identify_memory_cache_capacity, config.identify_memory_cache_ttl_seconds
        );
        let identify_cache: Arc<dyn IdentifyCache> = Arc::new(MemoryIdentifyCache::new(
            config.identify_memory_cache_capacity,
            Duration::from_secs(config.identify_memory_cache_ttl_seconds),
        ));

        info!(
            "Using in-memory cache for group events (capacity: {}, TTL: {}s)",
            config.group_memory_cache_capacity, config.group_memory_cache_ttl_seconds
        );
        let group_cache: Arc<dyn GroupCache> = Arc::new(MemoryGroupCache::new(
            config.group_memory_cache_capacity,
            Duration::from_secs(config.group_memory_cache_ttl_seconds),
        ));

        let person_processing_filter =
            PersonProcessingFilter::new(&config.force_disable_person_processing);

        let ctx = Self {
            config: config.clone(),
            db,
            encryption_keys: config
                .encryption_keys
                .split(",")
                .map(|s| s.to_string())
                .collect(),
            identify_cache,
            group_cache,
            person_processing_filter,
        };

        Ok(ctx)
    }

    pub async fn get_token_for_team_id(&self, team_id: i32) -> Result<String, Error> {
        Ok(
            sqlx::query_scalar!("SELECT api_token FROM posthog_team WHERE id = $1", team_id)
                .fetch_one(&self.db)
                .await?,
        )
    }
}
