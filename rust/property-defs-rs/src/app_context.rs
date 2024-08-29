use health::{HealthHandle, HealthRegistry};
use time::Duration;

use crate::{
    config::Config,
    metrics_consts::{CACHE_WARMING_STATE, UPDATES_ISSUED},
    types::Update,
};

pub struct AppContext {
    //pub pool: PgPool,
    pub liveness: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub cache_warming_delay: Duration,
    pub cache_warming_cutoff: f64,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, sqlx::Error> {
        //let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        //let pool = options.connect(&config.database_url).await?;

        let liveness: HealthRegistry = HealthRegistry::new("liveness");
        let worker_liveness = liveness
            .register("worker".to_string(), Duration::seconds(60))
            .await;

        Ok(Self {
            //pool,
            liveness,
            worker_liveness,
            cache_warming_delay: Duration::milliseconds(config.cache_warming_delay_ms as i64),
            cache_warming_cutoff: 0.9,
        })
    }

    pub async fn issue(
        &self,
        updates: Vec<Update>,
        cache_consumed: f64,
    ) -> Result<(), sqlx::Error> {
        if cache_consumed < self.cache_warming_cutoff {
            metrics::gauge!(CACHE_WARMING_STATE, &[("state", "warming")]).set(cache_consumed);
            let to_sleep = self.cache_warming_delay * (1.0 - cache_consumed);
            tokio::time::sleep(to_sleep.try_into().unwrap()).await;
        } else {
            metrics::gauge!(CACHE_WARMING_STATE, &[("state", "hot")]).set(1.0);
        }

        metrics::counter!(UPDATES_ISSUED).increment(updates.len() as u64);
        Ok(())
    }
}
