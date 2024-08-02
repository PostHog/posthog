use health::{HealthHandle, HealthRegistry};
use sqlx::{postgres::PgPoolOptions, PgPool};

use crate::{config::Config, group_type_cache::GroupTypeCache, property_cache::PropertyCache};

pub struct AppContext {
    pub pool: PgPool,
    pub property_cache: PropertyCache,
    pub group_type_cache: GroupTypeCache,
    pub liveness: HealthRegistry,
    pub worker_liveness: HealthHandle,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, sqlx::Error> {

        let options = PgPoolOptions::new()
            .max_connections(config.max_pg_connections);

        let pool = options.connect(&config.database_url).await?;

        let liveness: HealthRegistry = HealthRegistry::new("liveness");
        let worker_liveness = liveness.register("worker".to_string(), time::Duration::seconds(60)).await;

        let property_cache = PropertyCache::new();
        let group_type_cache = GroupTypeCache::new(&pool);

        Ok(Self {
            pool,
            property_cache,
            group_type_cache,
            liveness,
            worker_liveness
        })
    }
}