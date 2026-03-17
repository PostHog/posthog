use std::time::Duration;

use sqlx::postgres::PgPool;

const DB_POOL_SIZE: &str = "personhog_db_pool_size";
const DB_POOL_IDLE: &str = "personhog_db_pool_idle";
const DB_POOL_MAX: &str = "personhog_db_pool_max";

/// A database pool to be monitored, with its label and max connection ceiling.
pub struct MonitoredPool {
    pub pool: PgPool,
    /// Label for the `pool` metric dimension (e.g. "primary", "replica").
    pub label: String,
    /// Configured max_connections for this pool.
    pub max_connections: u32,
}

/// Spawns a background task that periodically reports pool health gauges.
///
/// Reports per pool:
/// - `personhog_db_pool_size{service, pool}` — current number of connections (active + idle)
/// - `personhog_db_pool_idle{service, pool}` — idle connections available for use
/// - `personhog_db_pool_max{service, pool}` — configured max_connections ceiling
pub fn spawn_pool_monitor(service: &str, pools: Vec<MonitoredPool>, interval: Duration) {
    let service = service.to_string();
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(interval);
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tick.tick().await;
            for entry in &pools {
                report_pool_stats(&service, entry);
            }
        }
    });
}

fn report_pool_stats(service: &str, entry: &MonitoredPool) {
    let labels = [
        ("service".to_string(), service.to_string()),
        ("pool".to_string(), entry.label.clone()),
    ];
    metrics::gauge!(DB_POOL_SIZE, &labels).set(entry.pool.size() as f64);
    metrics::gauge!(DB_POOL_IDLE, &labels).set(entry.pool.num_idle() as f64);
    metrics::gauge!(DB_POOL_MAX, &labels).set(entry.max_connections as f64);
}
