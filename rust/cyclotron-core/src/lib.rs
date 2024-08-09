use std::time::Duration;

use serde::{Deserialize, Serialize};
use sqlx::{pool::PoolOptions, PgPool};

pub mod base_ops;
pub mod error;
pub mod janitor_ops;
pub mod manager;
pub mod worker;

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
