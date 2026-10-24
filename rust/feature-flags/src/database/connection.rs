use common_database::{Client, CustomDatabaseError, GatePermit};
use common_metrics::{gauge, histogram, inc};
use sqlx::{pool::PoolConnection, postgres::PgConnection, Postgres};
use std::{
    ops::{Deref, DerefMut},
    sync::Arc,
    time::Instant,
};

use crate::metrics::consts::{
    FLAG_ACQUIRE_TIMEOUT_COUNTER, FLAG_CONNECTION_HOLD_TIME, FLAG_DB_CONNECTION_TIME,
    FLAG_POOL_UTILIZATION_GAUGE,
};

/// A wrapper around `PoolConnection<Postgres>` that tracks how long the connection is held.
/// When dropped, it records the hold time to `flags_connection_hold_time_ms`.
pub struct TrackedConnection {
    /// `None` only after `close_without_release_ping` takes the connection.
    conn: Option<PoolConnection<Postgres>>,
    start: Instant,
    labels: [(String, String); 2],
    /// Holds the pool's operation gate slot until the caller drops the connection.
    permit: Option<GatePermit>,
}

const DETACHED: &str = "TrackedConnection is used after close_without_release_ping";

impl TrackedConnection {
    fn new(
        conn: PoolConnection<Postgres>,
        labels: [(String, String); 2],
        permit: Option<GatePermit>,
    ) -> Self {
        Self {
            conn: Some(conn),
            start: Instant::now(),
            labels,
            permit,
        }
    }

    /// Close on drop instead of returning to the pool: sqlx's return-to-pool path pings
    /// with no deadline, so abandoning a stalled connection would hold the pool slot.
    pub fn close_on_drop(&mut self) {
        self.conn.as_mut().expect(DETACHED).close_on_drop();
    }

    /// Reports the operation outcome to the pool's operation gate, if it has one. Only the
    /// first report counts.
    pub fn record_gate_outcome(&mut self, success: bool) {
        if let Some(permit) = self.permit.as_mut() {
            if success {
                permit.record_success();
            } else {
                permit.record_failure();
            }
        }
    }

    /// Closes the connection at once and counts a gate failure. The pool does not ping the
    /// connection and does not send a graceful Terminate, so a frozen database cannot hold the
    /// pool slot. The pool opens a replacement in the background when `min_connections` is
    /// above zero.
    pub fn close_without_release_ping(mut self) {
        self.record_gate_outcome(false);
        if let Some(conn) = self.conn.take() {
            // Dropping the detached connection closes its socket without a protocol message.
            drop(conn.detach());
        }
    }
}

impl Deref for TrackedConnection {
    type Target = PgConnection;

    fn deref(&self) -> &Self::Target {
        self.conn.as_ref().expect(DETACHED)
    }
}

impl DerefMut for TrackedConnection {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.conn.as_mut().expect(DETACHED)
    }
}

impl Drop for TrackedConnection {
    fn drop(&mut self) {
        histogram(
            FLAG_CONNECTION_HOLD_TIME,
            &self.labels,
            self.start.elapsed().as_millis() as f64,
        );
    }
}

/// Acquires a database connection while tracking metrics.
///
/// This helper wraps the standard `get_connection()` call and:
/// - Records acquisition time to `flags_db_connection_time`
/// - Emits pool utilization ratio to `flags_pool_utilization_ratio`
/// - Increments `flags_acquire_timeout_total` when pool acquisition times out
/// - Records connection hold time to `flags_connection_hold_time_ms` when the connection is dropped
/// - Passes the client's operation gate first, when it has one. A rejected call returns
///   `CustomDatabaseError::GateRejected` without touching the pool. The gate slot stays taken
///   until the connection drops. The acquire result is the outcome that the gate's breaker
///   counts, and an acquire that the caller abandons counts as a failure.
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
/// * `Result<TrackedConnection, CustomDatabaseError>` - A wrapped connection that records hold time on drop
///
/// # Example
/// ```ignore
/// let mut conn = get_connection_with_metrics(
///     &reader,
///     "persons_reader",
///     "fetch_person_properties"
/// ).await?;
/// // Use conn like a normal connection via Deref/DerefMut
/// // Hold time is automatically recorded when conn goes out of scope
/// ```
pub async fn get_connection_with_metrics(
    client: &Arc<dyn Client + Send + Sync>,
    pool_name: &str,
    operation: &str,
) -> Result<TrackedConnection, CustomDatabaseError> {
    let mut conn = acquire_tracked(client, pool_name, operation).await?;
    conn.record_gate_outcome(true);
    Ok(conn)
}

/// Like `get_connection_with_metrics`, but a successful acquire reports no gate outcome. The
/// caller reports the outcome of the whole operation with `TrackedConnection::record_gate_outcome`.
/// A connection that drops with no report counts as a gate failure.
pub async fn get_connection_for_operation(
    client: &Arc<dyn Client + Send + Sync>,
    pool_name: &str,
    operation: &str,
) -> Result<TrackedConnection, CustomDatabaseError> {
    acquire_tracked(client, pool_name, operation).await
}

async fn acquire_tracked(
    client: &Arc<dyn Client + Send + Sync>,
    pool_name: &str,
    operation: &str,
) -> Result<TrackedConnection, CustomDatabaseError> {
    // Allocate labels once, reuse everywhere
    let labels: [(String, String); 2] = [
        ("pool".to_string(), pool_name.to_string()),
        ("operation".to_string(), operation.to_string()),
    ];

    // Record pool utilization before acquisition to capture state at request time
    if let Some(stats) = client.as_ref().get_pool_stats() {
        let utilization = if stats.size > 0 {
            stats.size.saturating_sub(stats.num_idle as u32) as f64 / stats.size as f64
        } else {
            0.0
        };
        gauge(FLAG_POOL_UTILIZATION_GAUGE, &labels[..1], utilization);
    }

    let permit = match client.operation_gate() {
        Some(gate) => Some(gate.enter().await?),
        None => None,
    };

    // Time connection acquisition (guard records on drop). Use the
    // sub-ms-precision variant: warm pool acquires complete in tens of
    // microseconds; the integer-ms variant rounds them all to the 1ms
    // bucket and hides tail behavior. Bucket overrides for this metric
    // (`flags_db_connection_time`) start at 0.05ms — see metrics::buckets.
    let result = {
        let _conn_timer =
            common_metrics::timing_guard_high_precision(FLAG_DB_CONNECTION_TIME, &labels);
        client.get_connection().await
    };

    // Track pool acquisition timeouts specifically
    if let Err(e) = &result {
        if matches!(e, CustomDatabaseError::Other(sqlx::Error::PoolTimedOut)) {
            inc(FLAG_ACQUIRE_TIMEOUT_COUNTER, &labels, 1);
        }
    }

    // On error, the permit drops here and the gate counts a failure.
    Ok(TrackedConnection::new(result?, labels, permit))
}

/// Acquires a writer database connection while tracking metrics.
///
/// This is a convenience alias for `get_connection_with_metrics` for semantic clarity when
/// working with writer pools.
#[inline]
pub async fn get_writer_connection_with_metrics(
    client: &Arc<dyn Client + Send + Sync>,
    pool_name: &str,
    operation: &str,
) -> Result<TrackedConnection, CustomDatabaseError> {
    get_connection_with_metrics(client, pool_name, operation).await
}
