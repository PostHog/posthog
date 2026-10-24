//! Runs one persons DB operation: a connection acquire plus the queries on that connection.
//!
//! With a task cap, the operation runs in its own task. The task owns the connection and the
//! pool's operation gate slot. A caller that stops waiting, for example at the persons DB
//! deadline, drops only its handle, so the task does not stop. A query that the database
//! answers late then still finishes, and the connection goes back to the pool in a clean state.
//! A cancelled query leaves the connection mid-protocol, and sqlx pings it with no deadline
//! before it reuses it. On a frozen database, that ping holds the pool slot.
//!
//! The cap is the backstop for a database that never answers. When the cap passes, the task
//! closes its connection at once, with no release ping, and reports a failure to the gate.
//!
//! A spawned task does not inherit the request's canonical-log scope. An operation therefore
//! returns what the canonical log needs, and the caller writes it.

use std::{future::Future, pin::Pin, sync::Arc, time::Duration};

use common_database::Client;
use sqlx::postgres::PgConnection;
use tokio::time::{timeout_at, Instant};
use tracing::{warn, Instrument};

use crate::{
    api::errors::FlagError,
    database::{get_connection_for_operation, get_connection_with_metrics},
    metrics::consts::FLAG_PERSONS_DB_TASK_CAPPED_COUNTER,
};

/// The queries of one operation, run on the connection that the operation acquired.
pub type PersonsDbQuery<'c, T> = Pin<Box<dyn Future<Output = Result<T, FlagError>> + Send + 'c>>;

/// Acquires a connection from `client` and runs `query` on it.
///
/// `task_cap` `None` runs the operation inline, and dropping this future cancels it.
/// `Some(cap)` runs it in its own task that stops after `cap`, and dropping this future does not
/// cancel the task.
pub async fn run_persons_db_operation<T, F>(
    client: &Arc<dyn Client + Send + Sync>,
    pool_name: &'static str,
    operation: &'static str,
    task_cap: Option<Duration>,
    query: F,
) -> Result<T, FlagError>
where
    T: Send + 'static,
    F: for<'c> FnOnce(&'c mut PgConnection) -> PersonsDbQuery<'c, T> + Send + 'static,
{
    let Some(cap) = task_cap else {
        let mut conn = get_connection_with_metrics(client, pool_name, operation)
            .await
            .inspect_err(|e| log_acquire_failure(client, pool_name, operation, e))?;
        return query(&mut conn).await;
    };

    let task = tokio::spawn(
        run_capped(Arc::clone(client), pool_name, operation, cap, query).in_current_span(),
    );
    task.await.map_err(FlagError::persons_db_task_failed)?
}

async fn run_capped<T, F>(
    client: Arc<dyn Client + Send + Sync>,
    pool_name: &'static str,
    operation: &'static str,
    cap: Duration,
    query: F,
) -> Result<T, FlagError>
where
    F: for<'c> FnOnce(&'c mut PgConnection) -> PersonsDbQuery<'c, T>,
{
    let cap_ends = Instant::now() + cap;

    // A cap that passes during the acquire drops the gate permit unreported, which counts as a
    // gate failure.
    let mut conn = match timeout_at(
        cap_ends,
        get_connection_for_operation(&client, pool_name, operation),
    )
    .await
    {
        Ok(conn) => conn.inspect_err(|e| log_acquire_failure(&client, pool_name, operation, e))?,
        Err(_) => {
            count_capped(pool_name, operation, "acquire");
            return Err(FlagError::persons_db_task_cap());
        }
    };

    match timeout_at(cap_ends, query(&mut conn)).await {
        Ok(result) => {
            // A query error means that the database answered. Only a lost connection says that
            // the database is not available.
            let available = !matches!(result, Err(FlagError::DatabaseUnavailable));
            conn.record_gate_outcome(available);
            result
        }
        Err(_) => {
            conn.close_without_release_ping();
            count_capped(pool_name, operation, "query");
            Err(FlagError::persons_db_task_cap())
        }
    }
}

fn count_capped(pool_name: &'static str, operation: &'static str, stage: &'static str) {
    warn!(
        pool = pool_name,
        operation = operation,
        stage = stage,
        "Persons DB task passed its cap"
    );
    metrics::counter!(
        FLAG_PERSONS_DB_TASK_CAPPED_COUNTER,
        "pool" => pool_name,
        "operation" => operation,
        "stage" => stage
    )
    .increment(1);
}

fn log_acquire_failure(
    client: &Arc<dyn Client + Send + Sync>,
    pool_name: &'static str,
    operation: &'static str,
    error: &common_database::CustomDatabaseError,
) {
    let (pool_size, pool_idle) = client
        .get_pool_stats()
        .map(|stats| (stats.size, stats.num_idle as u32))
        .unwrap_or_default();
    warn!(
        pool = pool_name,
        operation = operation,
        pool_size = pool_size,
        pool_idle = pool_idle,
        pool_in_use = pool_size.saturating_sub(pool_idle),
        error = ?error,
        "Failed to acquire persons DB connection"
    );
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicBool, Ordering};

    use common_database::{
        get_pool_with_config, BreakerState, GatedClient, OperationGate, OperationGateConfig,
        PoolConfig,
    };

    use super::*;
    use crate::config::DEFAULT_TEST_CONFIG;

    /// A one-connection pool behind a gate that opens on the first failure.
    fn gated_client() -> (Arc<dyn Client + Send + Sync>, OperationGate) {
        let pool = get_pool_with_config(
            &DEFAULT_TEST_CONFIG.persons_read_database_url,
            PoolConfig {
                min_connections: 0,
                max_connections: 1,
                ..PoolConfig::default()
            },
        )
        .expect("pool");
        let gate = OperationGate::new(OperationGateConfig {
            max_concurrent: 1,
            min_calls: 1,
            open_jitter: 0.0,
            ..OperationGateConfig::default()
        });
        (
            Arc::new(GatedClient::new(Arc::new(pool), gate.clone())),
            gate,
        )
    }

    fn pool_size_and_idle(client: &Arc<dyn Client + Send + Sync>) -> (u32, usize) {
        let stats = client.get_pool_stats().expect("pool stats");
        (stats.size, stats.num_idle)
    }

    #[tokio::test]
    async fn a_caller_that_stops_waiting_does_not_cancel_the_task() {
        let (client, gate) = gated_client();
        let finished = Arc::new(AtomicBool::new(false));
        let finished_in_task = Arc::clone(&finished);

        let wait = tokio::time::timeout(
            Duration::from_millis(50),
            run_persons_db_operation(
                &client,
                "test_pool",
                "test_operation",
                Some(Duration::from_secs(5)),
                move |conn| {
                    Box::pin(async move {
                        sqlx::query("SELECT pg_sleep(0.3)")
                            .execute(&mut *conn)
                            .await?;
                        finished_in_task.store(true, Ordering::SeqCst);
                        Ok(())
                    })
                },
            ),
        )
        .await;
        assert!(wait.is_err());

        tokio::time::sleep(Duration::from_millis(600)).await;
        assert!(finished.load(Ordering::SeqCst));
        assert_eq!(pool_size_and_idle(&client), (1, 1));
        assert_eq!(gate.state(), BreakerState::Closed);
    }

    #[tokio::test]
    async fn a_task_past_its_cap_closes_its_connection_and_reports_a_gate_failure() {
        let (client, gate) = gated_client();

        let result = run_persons_db_operation(
            &client,
            "test_pool",
            "test_operation",
            Some(Duration::from_millis(200)),
            |conn| {
                Box::pin(async move {
                    sqlx::query("SELECT pg_sleep(5)")
                        .execute(&mut *conn)
                        .await?;
                    Ok(())
                })
            },
        )
        .await;

        assert!(matches!(
            result,
            Err(FlagError::TimeoutError(Some(ref t))) if t == "persons_db_task_cap"
        ));
        // A connection that waited for a release ping would still count toward the pool size.
        assert_eq!(pool_size_and_idle(&client), (0, 0));
        assert_eq!(gate.state(), BreakerState::Open);
    }
}
