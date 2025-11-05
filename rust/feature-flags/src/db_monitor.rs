use crate::config::Config;
use crate::database_pools::DatabasePools;
use common_metrics::gauge;
use sqlx::PgPool;
use std::sync::Arc;
use std::time::Duration;
use tokio::time::interval;
use tracing::error;

use crate::metrics::consts::{
    DB_CONNECTION_POOL_ACTIVE_COUNTER, DB_CONNECTION_POOL_IDLE_COUNTER,
    DB_CONNECTION_POOL_MAX_COUNTER,
};

pub struct DatabasePoolMonitor {
    database_pools: Arc<DatabasePools>,
    monitoring_interval: Duration,
    warn_utilization_threshold: f64,
}

impl DatabasePoolMonitor {
    pub fn new(database_pools: Arc<DatabasePools>, config: &Config) -> Self {
        Self {
            database_pools,
            monitoring_interval: Duration::from_secs(config.db_monitor_interval_secs),
            warn_utilization_threshold: config.db_pool_warn_utilization,
        }
    }

    pub async fn start_monitoring(&self) {
        let mut ticker = interval(self.monitoring_interval);

        // Check if persons DB routing is enabled by comparing pool pointers
        let persons_routing_enabled = !Arc::ptr_eq(
            &self.database_pools.persons_reader,
            &self.database_pools.non_persons_reader,
        );

        if persons_routing_enabled {
            tracing::info!(
                "Starting database connection pool monitoring with persons DB routing enabled"
            );
        } else {
            tracing::info!(
                "Starting database connection pool monitoring (persons DB routing disabled)"
            );
        }

        loop {
            ticker.tick().await;

            if let Err(e) = self.collect_pool_metrics().await {
                error!("Failed to collect database pool metrics: {}", e);
            }
        }
    }

    async fn collect_pool_metrics(&self) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        // Always monitor non-persons pools
        self.collect_single_pool_metrics(
            &self.database_pools.non_persons_reader,
            "non_persons_reader",
        )
        .await?;

        self.collect_single_pool_metrics(
            &self.database_pools.non_persons_writer,
            "non_persons_writer",
        )
        .await?;

        // Only monitor persons pools if they're different from non-persons pools
        // (i.e., when persons DB routing is enabled)
        if !Arc::ptr_eq(
            &self.database_pools.persons_reader,
            &self.database_pools.non_persons_reader,
        ) {
            self.collect_single_pool_metrics(&self.database_pools.persons_reader, "persons_reader")
                .await?;
        }

        if !Arc::ptr_eq(
            &self.database_pools.persons_writer,
            &self.database_pools.non_persons_writer,
        ) {
            self.collect_single_pool_metrics(&self.database_pools.persons_writer, "persons_writer")
                .await?;
        }

        Ok(())
    }

    async fn collect_single_pool_metrics(
        &self,
        pool: &Arc<PgPool>,
        pool_name: &str,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        let pool_size = pool.size();
        let pool_idle = pool.num_idle();
        let pool_max = pool.options().get_max_connections();

        gauge(
            DB_CONNECTION_POOL_ACTIVE_COUNTER,
            &[("pool".to_string(), pool_name.to_string())],
            (pool_size as i32 - pool_idle as i32) as f64,
        );
        gauge(
            DB_CONNECTION_POOL_IDLE_COUNTER,
            &[("pool".to_string(), pool_name.to_string())],
            pool_idle as f64,
        );
        gauge(
            DB_CONNECTION_POOL_MAX_COUNTER,
            &[("pool".to_string(), pool_name.to_string())],
            pool_max as f64,
        );

        tracing::debug!(
            "{} pool metrics - active: {}, idle: {}, max: {}",
            pool_name,
            pool_size as i32 - pool_idle as i32,
            pool_idle,
            pool_max
        );

        // Warn if pool utilization is high
        let pool_utilization = (pool_size as i32 - pool_idle as i32) as f64 / pool_max as f64;
        if pool_utilization > self.warn_utilization_threshold {
            tracing::warn!(
                "High {} pool utilization: {:.1}% ({}/{})",
                pool_name,
                pool_utilization * 100.0,
                pool_size as i32 - pool_idle as i32,
                pool_max
            );
        }

        Ok(())
    }
}
