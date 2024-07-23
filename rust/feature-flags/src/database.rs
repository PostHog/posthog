use std::time::Duration;

use anyhow::Result;
use async_trait::async_trait;
use sqlx::{
    pool::PoolConnection,
    postgres::{PgPoolOptions, PgRow},
    Postgres,
};
use thiserror::Error;
use tokio::time::timeout;

use crate::config::Config;

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
    async fn run_query(
        &self,
        query: String,
        parameters: Vec<String>,
        timeout_ms: Option<u64>,
    ) -> Result<Vec<PgRow>, CustomDatabaseError>;
}

pub struct PgClient {
    pool: sqlx::PgPool,
}

impl PgClient {
    pub async fn new_read_client(config: &Config) -> Result<PgClient, CustomDatabaseError> {
        let pool = PgPoolOptions::new()
            .max_connections(config.max_pg_connections)
            .acquire_timeout(Duration::from_secs(1))
            .test_before_acquire(true)
            .connect(&config.read_database_url)
            .await?;

        Ok(PgClient { pool })
    }

    pub async fn new_write_client(config: &Config) -> Result<PgClient, CustomDatabaseError> {
        let pool = PgPoolOptions::new()
            .max_connections(config.max_pg_connections)
            .acquire_timeout(Duration::from_secs(1))
            .test_before_acquire(true)
            .connect(&config.write_database_url)
            .await?;

        Ok(PgClient { pool })
    }
}

#[async_trait]
impl Client for PgClient {
    async fn run_query(
        &self,
        query: String,
        parameters: Vec<String>,
        timeout_ms: Option<u64>,
    ) -> Result<Vec<PgRow>, CustomDatabaseError> {
        let built_query = sqlx::query(&query);
        let built_query = parameters
            .iter()
            .fold(built_query, |acc, param| acc.bind(param));
        let query_results = built_query.fetch_all(&self.pool);

        let timeout_ms = match timeout_ms {
            Some(ms) => ms,
            None => DATABASE_TIMEOUT_MILLISECS,
        };

        let fut = timeout(Duration::from_secs(timeout_ms), query_results).await?;

        Ok(fut?)
    }

    async fn get_connection(&self) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
        Ok(self.pool.acquire().await?)
    }
}
