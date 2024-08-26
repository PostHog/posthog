use std::collections::HashSet;

use health::{HealthHandle, HealthRegistry};
use sqlx::{postgres::PgPoolOptions, PgPool};

use crate::{config::Config, metrics_consts::UPDATES_ISSUED, types::Update};

pub struct AppContext {
    pub pool: PgPool,
    pub liveness: HealthRegistry,
    pub worker_liveness: HealthHandle,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, sqlx::Error> {
        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);

        let pool = options.connect(&config.database_url).await?;

        let liveness: HealthRegistry = HealthRegistry::new("liveness");
        let worker_liveness = liveness
            .register("worker".to_string(), time::Duration::seconds(60))
            .await;

        Ok(Self {
            pool,
            liveness,
            worker_liveness,
        })
    }

    pub async fn issue(&self, updates: HashSet<Update>) -> Result<(), sqlx::Error> {
        metrics::counter!(UPDATES_ISSUED).increment(updates.len() as u64);
        Ok(())
    }
}
