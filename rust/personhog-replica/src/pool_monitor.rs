use std::time::Duration;

use sqlx::postgres::PgPool;

const DB_POOL_SIZE: &str = "personhog_replica_db_pool_size";
const DB_POOL_IDLE: &str = "personhog_replica_db_pool_idle";
const DB_POOL_MAX: &str = "personhog_replica_db_pool_max";

/// Spawns a background task that periodically reports pool health gauges.
///
/// Reports per-pool:
/// - `personhog_replica_db_pool_size` — current number of connections (active + idle)
/// - `personhog_replica_db_pool_idle` — idle connections available for use
/// - `personhog_replica_db_pool_max` — configured max_connections ceiling
///
/// When `separate_pools` is false (i.e. primary and replica are the same physical pool),
/// only the "primary" label is reported to avoid double-counting.
pub fn spawn_pool_monitor(
    primary_pool: PgPool,
    replica_pool: PgPool,
    max_connections: u32,
    interval: Duration,
    separate_pools: bool,
) {
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(interval);
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tick.tick().await;
            report_pool_stats(&primary_pool, "primary", max_connections);
            if separate_pools {
                report_pool_stats(&replica_pool, "replica", max_connections);
            }
        }
    });
}

fn report_pool_stats(pool: &PgPool, pool_label: &str, max_connections: u32) {
    let labels = [("pool".to_string(), pool_label.to_string())];
    common_metrics::gauge(DB_POOL_SIZE, &labels, pool.size() as f64);
    common_metrics::gauge(DB_POOL_IDLE, &labels, pool.num_idle() as f64);
    common_metrics::gauge(DB_POOL_MAX, &labels, max_connections as f64);
}
