mod cohort;
mod distinct_id;
mod feature_flag;
mod group;
mod person;

use std::time::Instant;

use sqlx::pool::PoolConnection;
use sqlx::postgres::PgPool;
use sqlx::Postgres;

use super::error::StorageError;

pub(crate) const DB_QUERY_DURATION: &str = "personhog_replica_db_query_duration_ms";
pub(crate) const DB_POOL_ACQUIRE_DURATION: &str = "personhog_replica_db_pool_acquire_duration_ms";
pub(crate) const DB_ROWS_RETURNED: &str = "personhog_replica_db_rows_returned";
pub(crate) const DB_BULK_CHUNKS: &str = "personhog_replica_db_bulk_chunks";

/// Consistency level for read operations
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum ConsistencyLevel {
    /// Read from replica (may have replication lag)
    #[default]
    Eventual,
    /// Read from primary (guaranteed latest data)
    Strong,
}

/// Postgres implementation of storage traits with dual-pool support
/// for primary (strong consistency) and replica (eventual consistency) databases,
/// plus dedicated bulk pools for heavy batch operations.
pub struct PostgresStorage {
    /// Connection pool for the primary database (writes + strong consistency reads)
    pub primary_pool: PgPool,
    /// Connection pool for the replica database (eventual consistency reads)
    pub replica_pool: PgPool,
    /// Bulk pool for the primary database (heavy deletes, batch writes)
    pub bulk_primary_pool: PgPool,
    /// Bulk pool for the replica database (large batch reads)
    pub bulk_replica_pool: PgPool,
    pub(crate) bulk_chunk_size: usize,
    pub(crate) bulk_max_concurrent_chunks: usize,
}

impl PostgresStorage {
    /// Create a new PostgresStorage with separate primary, replica, and bulk pools.
    pub fn new(
        primary_pool: PgPool,
        replica_pool: PgPool,
        bulk_primary_pool: PgPool,
        bulk_replica_pool: PgPool,
        bulk_chunk_size: usize,
        bulk_max_concurrent_chunks: usize,
    ) -> Self {
        Self {
            primary_pool,
            replica_pool,
            bulk_primary_pool,
            bulk_replica_pool,
            bulk_chunk_size,
            bulk_max_concurrent_chunks,
        }
    }

    /// Get the appropriate pool based on consistency level.
    /// Strong consistency always uses the primary pool.
    /// Eventual consistency uses the replica pool.
    pub(crate) fn pool_for_consistency(&self, consistency: ConsistencyLevel) -> &PgPool {
        match consistency {
            ConsistencyLevel::Strong => &self.primary_pool,
            ConsistencyLevel::Eventual => &self.replica_pool,
        }
    }

    /// Get the appropriate bulk pool based on consistency level.
    pub(crate) fn bulk_pool_for_consistency(&self, consistency: ConsistencyLevel) -> &PgPool {
        match consistency {
            ConsistencyLevel::Strong => &self.bulk_primary_pool,
            ConsistencyLevel::Eventual => &self.bulk_replica_pool,
        }
    }

    pub(crate) fn bulk_pool_label(consistency: ConsistencyLevel) -> &'static str {
        match consistency {
            ConsistencyLevel::Strong => "bulk_primary",
            ConsistencyLevel::Eventual => "bulk_replica",
        }
    }

    /// Returns the pool label for the given consistency level.
    pub(crate) fn pool_label(consistency: ConsistencyLevel) -> &'static str {
        match consistency {
            ConsistencyLevel::Strong => "primary",
            ConsistencyLevel::Eventual => "replica",
        }
    }

    /// Acquire a connection from the given pool, recording the acquisition time
    /// as `personhog_replica_db_pool_acquire_duration_ms` with `pool`, `client`,
    /// and `method` labels.
    pub(crate) async fn acquire_timed(
        pool: &PgPool,
        pool_label: &str,
    ) -> Result<PoolConnection<Postgres>, StorageError> {
        let start = Instant::now();
        let conn = pool.acquire().await.map_err(StorageError::from)?;
        let elapsed_ms = start.elapsed().as_secs_f64() * 1000.0;
        common_metrics::histogram(
            DB_POOL_ACQUIRE_DURATION,
            &[
                ("pool".to_string(), pool_label.to_string()),
                (
                    "client".to_string(),
                    personhog_common::grpc::current_client_name().to_string(),
                ),
                (
                    "method".to_string(),
                    personhog_common::grpc::current_method_name().to_string(),
                ),
            ],
            elapsed_ms,
        );
        Ok(conn)
    }

    /// Get the primary pool (for writes).
    #[allow(dead_code)]
    pub(crate) fn primary_pool(&self) -> &PgPool {
        &self.primary_pool
    }

    /// Get the replica pool (for eventual consistency reads).
    #[allow(dead_code)]
    pub(crate) fn replica_pool(&self) -> &PgPool {
        &self.replica_pool
    }
}

impl From<sqlx::Error> for StorageError {
    fn from(err: sqlx::Error) -> Self {
        match &err {
            sqlx::Error::PoolTimedOut | sqlx::Error::PoolClosed => StorageError::PoolExhausted,

            sqlx::Error::Io(_) | sqlx::Error::Tls(_) => StorageError::Connection(err.to_string()),

            _ => StorageError::Query(err.to_string()),
        }
    }
}
