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
    reader: Arc<PgPool>,
    writer: Arc<PgPool>,
}

impl DatabasePoolMonitor {
    pub fn new(reader: Arc<PgPool>, writer: Arc<PgPool>) -> Self {
        Self { reader, writer }
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
        // Monitor reader pool
        let reader_size = self.reader.size();
        let reader_idle = self.reader.num_idle();
        let reader_max = self.reader.options().get_max_connections();

        gauge(
            DB_CONNECTION_POOL_ACTIVE_COUNTER,
            &[("pool".to_string(), "reader".to_string())],
            (reader_size as i32 - reader_idle as i32) as f64,
        );
        gauge(
            DB_CONNECTION_POOL_IDLE_COUNTER,
            &[("pool".to_string(), "reader".to_string())],
            reader_idle as f64,
        );
        gauge(
            DB_CONNECTION_POOL_MAX_COUNTER,
            &[("pool".to_string(), "reader".to_string())],
            reader_max as f64,
        );

        tracing::debug!(
            "Reader pool metrics - active: {}, idle: {}, max: {}",
            reader_size as i32 - reader_idle as i32,
            reader_idle,
            reader_max
        );

        // Warn if pool utilization is high
        let reader_utilization =
            (reader_size as i32 - reader_idle as i32) as f64 / reader_max as f64;
        if reader_utilization > 0.8 {
            tracing::warn!(
                "High reader pool utilization: {:.1}% ({}/{})",
                reader_utilization * 100.0,
                reader_size as i32 - reader_idle as i32,
                reader_max
            );
        }

        // Monitor writer pool
        let writer_size = self.writer.size();
        let writer_idle = self.writer.num_idle();
        let writer_max = self.writer.options().get_max_connections();

        gauge(
            DB_CONNECTION_POOL_ACTIVE_COUNTER,
            &[("pool".to_string(), "writer".to_string())],
            (writer_size as i32 - writer_idle as i32) as f64,
        );
        gauge(
            DB_CONNECTION_POOL_IDLE_COUNTER,
            &[("pool".to_string(), "writer".to_string())],
            writer_idle as f64,
        );
        gauge(
            DB_CONNECTION_POOL_MAX_COUNTER,
            &[("pool".to_string(), "writer".to_string())],
            writer_max as f64,
        );

        tracing::debug!(
            "Writer pool metrics - active: {}, idle: {}, max: {}",
            writer_size as i32 - writer_idle as i32,
            writer_idle,
            writer_max
        );

        // Warn if pool utilization is high
        let writer_utilization =
            (writer_size as i32 - writer_idle as i32) as f64 / writer_max as f64;
        if writer_utilization > 0.8 {
            tracing::warn!(
                "High writer pool utilization: {:.1}% ({}/{})",
                writer_utilization * 100.0,
                writer_size as i32 - writer_idle as i32,
                writer_max
            );
        }

        Ok(())
    }
}
