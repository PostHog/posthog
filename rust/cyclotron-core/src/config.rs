use std::time::Duration;

use serde::{Deserialize, Serialize};
use sqlx::{pool::PoolOptions, PgPool};

// A pool config object, designed to be passable across API boundaries
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct PoolConfig {
    pub db_url: String,
    pub max_connections: Option<u32>,         // Default to 10
    pub min_connections: Option<u32>,         // Default to 1
    pub acquire_timeout_seconds: Option<u64>, // Default to 30
    pub max_lifetime_seconds: Option<u64>,    // Default to 300
    pub idle_timeout_seconds: Option<u64>,    // Default to 60
}

impl PoolConfig {
    pub async fn connect(&self) -> Result<PgPool, sqlx::Error> {
        let builder = PoolOptions::new()
            .max_connections(self.max_connections.unwrap_or(10))
            .min_connections(self.min_connections.unwrap_or(1))
            .max_lifetime(Duration::from_secs(
                self.max_lifetime_seconds.unwrap_or(300),
            ))
            .idle_timeout(Duration::from_secs(self.idle_timeout_seconds.unwrap_or(60)))
            .acquire_timeout(Duration::from_secs(
                self.acquire_timeout_seconds.unwrap_or(30),
            ));

        builder.connect(&self.db_url).await
    }
}

pub const DEFAULT_QUEUE_DEPTH_LIMIT: u64 = 1_000_000;
pub const DEFAULT_SHARD_HEALTH_CHECK_INTERVAL: u64 = 10;

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct ManagerConfig {
    #[serde(alias = "shards")]
    pub shards: Vec<PoolConfig>,
    #[serde(alias = "shardDepthLimit")]
    pub shard_depth_limit: Option<u64>, // Defaults to 10_000 available jobs per shard
    #[serde(alias = "shardDepthCheckIntervalSeconds")]
    pub shard_depth_check_interval_seconds: Option<u64>, // Defaults to 10 seconds - checking shard capacity
    #[serde(alias = "shouldCompressVmState")]
    pub should_compress_vm_state: Option<bool>, // Defaults to "false" for now
    #[serde(alias = "shouldUseBulkJobCopy")]
    pub should_use_bulk_job_copy: Option<bool>, // Defaults to "false" for now
}

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct WorkerConfig {
    #[serde(alias = "heartbeatWindowSeconds")]
    pub heartbeat_window_seconds: Option<u64>, // Defaults to 5
    #[serde(alias = "lingerTimeMs")]
    pub linger_time_ms: Option<u64>, // Defaults to 500
    #[serde(alias = "maxUpdatesBuffered")]
    pub max_updates_buffered: Option<usize>, // Defaults to 100
    #[serde(alias = "maxBytesBuffered")]
    pub max_bytes_buffered: Option<usize>, // Defaults to 10MB
    #[serde(alias = "flushLoopIntervalMs")]
    pub flush_loop_interval_ms: Option<u64>, // Defaults to 10
    #[serde(alias = "shouldCompressVmState")]
    pub should_compress_vm_state: Option<bool>, // Defaults to "false"
}

impl WorkerConfig {
    pub fn heartbeat_window(&self) -> chrono::Duration {
        chrono::Duration::seconds(self.heartbeat_window_seconds.unwrap_or(5) as i64)
    }

    pub fn linger_time(&self) -> chrono::Duration {
        chrono::Duration::milliseconds(self.linger_time_ms.unwrap_or(500) as i64)
    }

    pub fn flush_loop_interval(&self) -> chrono::Duration {
        chrono::Duration::milliseconds(self.flush_loop_interval_ms.unwrap_or(10) as i64)
    }

    pub fn max_updates_buffered(&self) -> usize {
        self.max_updates_buffered.unwrap_or(100)
    }

    pub fn max_bytes_buffered(&self) -> usize {
        self.max_bytes_buffered.unwrap_or(10_000_000)
    }

    pub fn should_compress_vm_state(&self) -> bool {
        self.should_compress_vm_state.unwrap_or(false)
    }
}
