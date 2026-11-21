mod cohort;
mod distinct_id;
mod feature_flag;
mod group;
mod person;
mod repair;

use std::time::Instant;

use personhog_common::properties::{PROPERTIES_SIZE_LIMIT_BYTES, PROPERTIES_TRIM_TARGET_BYTES};
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
    pub(crate) tombstoned_delete_max_rows: usize,
    pub(crate) hash_key_override_statement_timeout_ms: u64,
    pub(crate) properties_size_limit: usize,
    pub(crate) properties_trim_target: usize,
}

impl PostgresStorage {
    /// Create a new PostgresStorage with separate primary, replica, and bulk pools.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        primary_pool: PgPool,
        replica_pool: PgPool,
        bulk_primary_pool: PgPool,
        bulk_replica_pool: PgPool,
        bulk_chunk_size: usize,
        bulk_max_concurrent_chunks: usize,
        tombstoned_delete_max_rows: usize,
        hash_key_override_statement_timeout_ms: u64,
    ) -> Self {
        Self {
            primary_pool,
            replica_pool,
            bulk_primary_pool,
            bulk_replica_pool,
            bulk_chunk_size,
            bulk_max_concurrent_chunks,
            tombstoned_delete_max_rows,
            hash_key_override_statement_timeout_ms,
            properties_size_limit: PROPERTIES_SIZE_LIMIT_BYTES,
            properties_trim_target: PROPERTIES_TRIM_TARGET_BYTES,
        }
    }

    /// Override the person properties size limits. Tests use small limits, because the
    /// `check_properties_size` constraint rejects a row over the real limit.
    pub fn with_properties_size_limits(mut self, limit: usize, trim_target: usize) -> Self {
        self.properties_size_limit = limit;
        self.properties_trim_target = trim_target;
        self
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

#[cfg(test)]
mod tests {
    use std::path::Path;

    #[test]
    fn every_compile_time_query_carries_its_query_tag() {
        let prefix = format!("/* service='{}', operation='", env!("CARGO_PKG_NAME"));
        let tagged = |query: &str| {
            query
                .strip_prefix(&prefix)
                .and_then(|rest| rest.split_once("' */"))
                .is_some_and(|(operation, _)| {
                    !operation.is_empty()
                        && operation
                            .chars()
                            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
                })
        };
        let cache = Path::new(env!("CARGO_MANIFEST_DIR")).join(".sqlx");
        let mut untagged: Vec<String> = std::fs::read_dir(&cache)
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .filter(|path| path.extension().is_some_and(|ext| ext == "json"))
            .filter_map(|path| {
                let entry: serde_json::Value =
                    serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
                let query = entry["query"].as_str().unwrap();
                (!tagged(query)).then(|| query.to_string())
            })
            .collect();
        untagged.sort();
        assert!(
            untagged.is_empty(),
            "queries without a `{prefix}<snake_case>' */` tag: {untagged:#?}"
        );
    }
}
