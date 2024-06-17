use std::time::Duration;

use anyhow::Result;
use async_trait::async_trait;
use redis::{AsyncCommands, RedisError};
use sqlx::{pool::PoolConnection, postgres::{PgPoolOptions, PgRow}, Postgres};
use thiserror::Error;
use tokio::time::timeout;

const DATABASE_TIMEOUT_MILLISECS: u64 = 1000;

#[derive(Error, Debug)]
pub enum CustomDatabaseError {
    #[error("Not found in database")]
    NotFound,

    #[error("Pg error: {0}")]
    Other(#[from] sqlx::Error),

    #[error("Timeout error")]
    Timeout(#[from] tokio::time::error::Elapsed),
}

/// A simple db wrapper
/// Supports running any arbitrary query with a timeout.
/// TODO: Make sqlx prepared statements work with pgbouncer, potentially by setting pooling mode to session.
#[async_trait]
pub trait Client {
    async fn get_connection(&self) -> Result<PoolConnection<Postgres>, CustomDatabaseError>;
    async fn run_query(&self, query: String, parameters: Vec<String>, timeout_ms: Option<u64>) -> Result<Vec<PgRow>, CustomDatabaseError>;
}

pub struct PgClient {
    pool: sqlx::PgPool,
}

impl PgClient {
    pub async fn new(addr: String) -> Result<PgClient, CustomDatabaseError> {
        let pool = PgPoolOptions::new()
        .max_connections(5)
        .connect(&addr).await?;

        Ok(PgClient { pool })
    }
}

#[async_trait]
impl Client for PgClient {
    async fn run_query(&self, query: String, parameters: Vec<String>, timeout_ms: Option<u64>) -> Result<Vec<PgRow>, CustomDatabaseError> {
        let query_results = sqlx::query(&query).fetch_all(&self.pool);

        let timeout_ms = match timeout_ms {
            Some(ms) => ms,
            None => DATABASE_TIMEOUT_MILLISECS,
        };

        let fut =
            timeout(Duration::from_secs(timeout_ms), query_results).await?;

        Ok(fut?)
    }

    async fn get_connection(&self) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
        Ok(self.pool.acquire().await?)
    }
}
