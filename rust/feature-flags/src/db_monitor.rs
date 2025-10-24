use crate::config::Config;
use crate::database_pools::DatabasePools;
use anyhow::Result;
use common_metrics::gauge;
use sqlx::PgPool;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::time::interval;
use tracing::error;

use crate::metrics::consts::{
    DB_CONNECTION_POOL_ACTIVE_COUNTER, DB_CONNECTION_POOL_IDLE_COUNTER,
    DB_CONNECTION_POOL_MAX_COUNTER, DB_TCP_CONNECTION_LATENCY_MS,
};

pub struct DatabasePoolMonitor {
    database_pools: Arc<DatabasePools>,
    monitoring_interval: Duration,
    warn_utilization_threshold: f64,
    pool_endpoints: HashMap<String, (String, u16)>,
}

impl DatabasePoolMonitor {
    pub fn new(database_pools: Arc<DatabasePools>, config: &Config) -> Self {
        let mut pool_endpoints = HashMap::new();

        for (pool, name) in [
            (&database_pools.non_persons_reader, "non_persons_reader"),
            (&database_pools.non_persons_writer, "non_persons_writer"),
            (&database_pools.persons_reader, "persons_reader"),
            (&database_pools.persons_writer, "persons_writer"),
        ] {
            Self::try_parse_endpoint(pool, name, &mut pool_endpoints);
        }

        Self {
            database_pools,
            monitoring_interval: Duration::from_secs(config.db_monitor_interval_secs),
            warn_utilization_threshold: config.db_pool_warn_utilization,
            pool_endpoints,
        }
    }

    fn try_parse_endpoint(
        pool: &Arc<PgPool>,
        pool_name: &str,
        endpoints: &mut HashMap<String, (String, u16)>,
    ) {
        let connect_options = pool.connect_options();
        let host = connect_options.get_host();
        let port = connect_options.get_port();

        if !host.is_empty() && port > 0 {
            endpoints.insert(pool_name.to_string(), (host.to_string(), port));
            tracing::debug!(
                "Parsed connection endpoint for {}: {}:{}",
                pool_name,
                host,
                port
            );
        } else {
            tracing::warn!("Failed to parse connection endpoint for {}, network latency monitoring will be disabled", pool_name);
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

        self.measure_all_network_latencies().await;

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

    /// Measures network latency for all configured pools in parallel.
    async fn measure_all_network_latencies(&self) {
        let futures: Vec<_> = self
            .pool_endpoints
            .keys()
            .map(|pool_name| async move {
                if let Err(e) = self.measure_network_latency(pool_name).await {
                    tracing::debug!("Failed to measure network latency for {}: {}", pool_name, e);
                }
            })
            .collect();

        futures::future::join_all(futures).await;
    }

    /// Measures network latency to a single endpoint via TCP handshake.
    /// Note: This measures pure network RTT, not database query performance.
    /// The connection is established and immediately dropped without authentication.
    async fn measure_network_latency(&self, pool_name: &str) -> Result<()> {
        let (host, port) = self
            .pool_endpoints
            .get(pool_name)
            .ok_or_else(|| anyhow::anyhow!("Endpoint not configured for this pool"))?;

        let latency_ms = Self::measure_tcp_latency(host, *port).await?;

        gauge(
            DB_TCP_CONNECTION_LATENCY_MS,
            &[("pool".to_string(), pool_name.to_string())],
            latency_ms,
        );

        Ok(())
    }

    /// Measures TCP connection latency to a specific host and port.
    /// Returns latency in milliseconds.
    pub(crate) async fn measure_tcp_latency(host: &str, port: u16) -> Result<f64> {
        let start = std::time::Instant::now();

        // Establish a raw TCP connection to measure network latency
        // Use a 5 second timeout to avoid hanging the monitoring loop
        let stream = tokio::time::timeout(
            Duration::from_secs(5),
            tokio::net::TcpStream::connect((host, port)),
        )
        .await
        .map_err(|_| anyhow::anyhow!("Connection timeout"))?
        .map_err(|e| anyhow::anyhow!("Connection failed: {}", e))?;

        drop(stream);

        let latency_ms = start.elapsed().as_millis() as f64;
        Ok(latency_ms)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::TcpListener;

    #[tokio::test]
    async fn test_tcp_latency_measurement_with_mock_server() {
        // Start a mock TCP server on a random available port
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("Failed to bind mock server");
        let addr = listener.local_addr().expect("Failed to get local address");

        // Spawn a task to accept connections
        tokio::spawn(async move {
            while let Ok((stream, _)) = listener.accept().await {
                // Immediately drop the connection to simulate minimal server response
                drop(stream);
            }
        });

        // Measure latency to the mock server
        let result = DatabasePoolMonitor::measure_tcp_latency("127.0.0.1", addr.port()).await;

        // Verify the measurement succeeded and returned a reasonable latency
        assert!(result.is_ok(), "TCP latency measurement should succeed");
        let latency_ms = result.unwrap();
        assert!(
            (0.0..1000.0).contains(&latency_ms),
            "Latency should be between 0 and 1000ms for localhost, got: {latency_ms}ms"
        );
    }

    #[tokio::test]
    async fn test_tcp_latency_measurement_connection_refused() {
        // Try to connect to a port that's not listening
        // We use a high port number that's unlikely to be in use
        let result = DatabasePoolMonitor::measure_tcp_latency("127.0.0.1", 59999).await;

        // Verify the measurement fails gracefully
        assert!(result.is_err(), "Should fail when connection is refused");
        let error_msg = result.unwrap_err().to_string();
        assert!(
            error_msg.contains("Connection failed") || error_msg.contains("refused"),
            "Error should indicate connection failure, got: {error_msg}"
        );
    }

    #[tokio::test]
    async fn test_tcp_latency_measurement_with_timeout() {
        // Use a non-routable IP address to trigger timeout
        let result = DatabasePoolMonitor::measure_tcp_latency("192.0.2.1", 9999).await;

        // Verify the measurement times out
        assert!(result.is_err(), "Should timeout for non-routable address");
        let error_msg = result.unwrap_err().to_string();
        assert!(
            error_msg.contains("timeout") || error_msg.contains("Timeout"),
            "Error should indicate timeout, got: {error_msg}"
        );
    }

    #[tokio::test]
    async fn test_tcp_latency_measurement_repeated() {
        // Start a mock TCP server
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("Failed to bind mock server");
        let addr = listener.local_addr().expect("Failed to get local address");

        // Accept multiple connections
        tokio::spawn(async move {
            for _ in 0..5 {
                if let Ok((stream, _)) = listener.accept().await {
                    drop(stream);
                }
            }
        });

        // Measure latency multiple times to ensure consistency
        for i in 0..5 {
            let result = DatabasePoolMonitor::measure_tcp_latency("127.0.0.1", addr.port()).await;
            let measurement_num = i + 1;
            assert!(
                result.is_ok(),
                "Measurement {measurement_num} should succeed"
            );
            let latency_ms = result.unwrap();
            assert!(
                latency_ms < 1000.0,
                "Measurement {measurement_num} latency should be reasonable: {latency_ms}ms"
            );
        }
    }
}
