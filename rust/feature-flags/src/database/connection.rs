use common_database::{Client, CustomDatabaseError};
use common_metrics::inc;
use sqlx::{pool::PoolConnection, Postgres};
use std::sync::Arc;

use crate::metrics::consts::{FLAG_ACQUIRE_TIMEOUT_COUNTER, FLAG_DB_CONNECTION_TIME};

/// Acquires a database connection while tracking acquisition time and timeout metrics.
///
/// This helper wraps the standard `get_connection()` call and:
/// - Records acquisition time to `flags_db_connection_time`
/// - Increments `flags_acquire_timeout_total` when pool acquisition times out
///
/// Works with any database client (reader or writer pools) since PostgresReader and
/// PostgresWriter are both `Arc<dyn Client + Send + Sync>`.
///
/// # Arguments
/// * `client` - The database client (reader or writer pool)
/// * `pool_name` - Name of the pool for metrics (e.g., "persons_reader", "non_persons_writer")
/// * `operation` - Name of the operation for metrics (e.g., "fetch_flags", "write_hash_key")
///
/// # Returns
/// * `Result<PoolConnection<Postgres>, CustomDatabaseError>` - The connection or an error
///
/// # Example
/// ```ignore
/// let conn = get_connection_with_metrics(
///     &reader,
///     "persons_reader",
///     "fetch_person_properties"
/// ).await?;
/// ```
pub async fn get_connection_with_metrics(
    client: &Arc<dyn Client + Send + Sync>,
    pool_name: &str,
    operation: &str,
) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
    let labels = vec![
        ("pool".to_string(), pool_name.to_string()),
        ("operation".to_string(), operation.to_string()),
    ];
    let _conn_timer = common_metrics::timing_guard(FLAG_DB_CONNECTION_TIME, &labels);

    let result = client.get_connection().await;

    // Track pool acquisition timeouts specifically
    if let Err(e) = &result {
        if matches!(e, CustomDatabaseError::Other(sqlx::Error::PoolTimedOut)) {
            inc(FLAG_ACQUIRE_TIMEOUT_COUNTER, &labels, 1);
        }
    }

    result
}

/// Acquires a writer database connection while tracking acquisition time and timeout metrics.
///
/// This is a convenience alias for `get_connection_with_metrics` for semantic clarity when
/// working with writer pools.
#[inline]
pub async fn get_writer_connection_with_metrics(
    client: &Arc<dyn Client + Send + Sync>,
    pool_name: &str,
    operation: &str,
) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
    get_connection_with_metrics(client, pool_name, operation).await
}
