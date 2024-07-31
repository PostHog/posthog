use sqlx::postgres::PgPoolOptions;

use crate::{config::Config, group_type_cache::GroupTypeCache, property_cache::PropertyCacheManager};

pub struct AppContext {
    pub property_cache: PropertyCacheManager,
    pub group_type_cache: GroupTypeCache,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, sqlx::Error> {

        let options = PgPoolOptions::new()
            .max_connections(config.max_pg_connections);

        let pool = options.connect(&config.database_url).await?;

        let property_cache = PropertyCacheManager::new(&pool);
        let group_type_cache = GroupTypeCache::new(&pool);

        Ok(Self {
            property_cache,
            group_type_cache,
        })
    }
}