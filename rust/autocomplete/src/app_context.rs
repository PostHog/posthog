use sqlx::{postgres::PgPoolOptions, PgPool};

use crate::{config::Config, group_type_cache::GroupTypeCache, property_cache::PropertyCache};

pub struct AppContext {
    pub pool: PgPool,
    pub property_cache: PropertyCache,
    pub group_type_cache: GroupTypeCache,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, sqlx::Error> {

        let options = PgPoolOptions::new()
            .max_connections(config.max_pg_connections);

        let pool = options.connect(&config.database_url).await?;

        let property_cache = PropertyCache::new();
        let group_type_cache = GroupTypeCache::new(&pool);

        Ok(Self {
            pool,
            property_cache,
            group_type_cache,
        })
    }
}