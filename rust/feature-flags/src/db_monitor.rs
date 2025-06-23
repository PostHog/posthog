use common_metrics::gauge;
use sqlx::PgPool;
use std::sync::Arc;
use std::time::Duration;
use tokio::time::interval;
use tracing::error;

use crate::database_pools::DatabasePools;
use crate::metrics::consts::{
    DB_CONNECTION_POOL_ACTIVE_COUNTER, DB_CONNECTION_POOL_IDLE_COUNTER,
    DB_CONNECTION_POOL_MAX_COUNTER,
};

pub struct DatabasePoolMonitor {
    database_pools: Option<Arc<DatabasePools>>,
    // Legacy support for existing constructor
    reader: Option<Arc<PgPool>>,
    writer: Option<Arc<PgPool>>,
}

impl DatabasePoolMonitor {
    // Legacy constructor for backward compatibility
    pub fn new(reader: Arc<PgPool>, writer: Arc<PgPool>) -> Self {
        Self {
            database_pools: None,
            reader: Some(reader),
            writer: Some(writer),
        }
    }

    // New constructor that uses database pools
    pub fn new_with_pools(database_pools: Arc<DatabasePools>) -> Self {
        Self {
            database_pools: Some(database_pools),
            reader: None,
            writer: None,
        }
    }

    pub async fn start_monitoring(&self) {
        let mut ticker = interval(Duration::from_secs(30));
        tracing::debug!("Starting database connection pool monitoring");

        loop {
            ticker.tick().await;

            if let Err(e) = self.collect_pool_metrics().await {
                error!("Failed to collect database pool metrics: {}", e);
            }
        }
    }

    async fn collect_pool_metrics(&self) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        if let Some(pools) = &self.database_pools {
            // Monitor all database pools directly
            self.monitor_pool_direct("non_persons_reader", &pools.non_persons_reader)
                .await?;
            self.monitor_pool_direct("persons_reader", &pools.persons_reader)
                .await?;
            self.monitor_pool_direct("persons_writer", &pools.persons_writer)
                .await?;
        } else if let (Some(reader), Some(writer)) = (&self.reader, &self.writer) {
            // Legacy monitoring for backward compatibility
            self.monitor_pool_direct("reader", reader).await?;
            self.monitor_pool_direct("writer", writer).await?;
        }

        Ok(())
    }

    async fn monitor_pool_direct(
        &self,
        pool_name: &str,
        pool: &PgPool,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        let size = pool.size();
        let idle = pool.num_idle();
        let max_connections = pool.options().get_max_connections();

        gauge(
            DB_CONNECTION_POOL_ACTIVE_COUNTER,
            &[("pool".to_string(), pool_name.to_string())],
            (size as i32 - idle as i32) as f64,
        );
        gauge(
            DB_CONNECTION_POOL_IDLE_COUNTER,
            &[("pool".to_string(), pool_name.to_string())],
            idle as f64,
        );
        gauge(
            DB_CONNECTION_POOL_MAX_COUNTER,
            &[("pool".to_string(), pool_name.to_string())],
            max_connections as f64,
        );

        tracing::debug!(
            "{} pool metrics - active: {}, idle: {}, max: {}",
            pool_name,
            size as i32 - idle as i32,
            idle,
            max_connections
        );

        // Warn if pool utilization is high
        let utilization = (size as i32 - idle as i32) as f64 / max_connections as f64;
        if utilization > 0.8 {
            tracing::warn!(
                "High {} pool utilization: {:.1}% ({}/{})",
                pool_name,
                utilization * 100.0,
                size as i32 - idle as i32,
                max_connections
            );
        }

        Ok(())
    }
}
