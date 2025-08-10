use std::{sync::Arc, time::Duration};

use anyhow::Result;
use async_trait::async_trait;
use sqlx::{
    pool::PoolConnection,
    postgres::{PgPool, PgPoolOptions, PgRow},
    Postgres,
};
use thiserror::Error;
use tokio::time::timeout;

const DATABASE_TIMEOUT_MILLISECS: u64 = 1000;

#[derive(Error, Debug)]
pub enum CustomDatabaseError {
    #[error("Pg error: {0}")]
    Other(#[from] sqlx::Error),

    #[error("Timeout error")]
    Timeout(#[from] tokio::time::error::Elapsed),
}

pub type PostgresReader = Arc<dyn Client + Send + Sync>;
pub type PostgresWriter = Arc<dyn Client + Send + Sync>;

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

pub async fn get_pool(url: &str, max_connections: u32) -> Result<PgPool, sqlx::Error> {
    PgPoolOptions::new()
        .max_connections(max_connections)
        .acquire_timeout(Duration::from_secs(1))
        .test_before_acquire(true)
        .connect(url)
        .await
}

#[async_trait]
impl Client for PgPool {
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
        let query_results = built_query.fetch_all(self);

        let timeout_ms = match timeout_ms {
            Some(ms) => ms,
            None => DATABASE_TIMEOUT_MILLISECS,
        };

        let fut = timeout(Duration::from_secs(timeout_ms), query_results).await?;

        Ok(fut?)
    }

    async fn get_connection(&self) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
        Ok(self.acquire().await?)
    }
}
