use std::time::Duration;

use common_database::is_transient_error;
use sqlx::{pool::PoolConnection, PgPool, Postgres};
use tracing::warn;

use crate::metric_consts::{PG_ACQUIRE_RETRY, PG_ACQUIRE_RETRY_EXHAUSTED};

/// Acquire a connection from the pool, retrying a bounded number of times on transient
/// connection errors before giving up.
///
/// The pool is configured with `test_before_acquire`, so a stale connection that was
/// closed server-side is detected and discarded at acquire time rather than failing on
/// first use. This retry covers the remaining window where opening a *fresh* connection
/// also blips transiently (e.g. a brief network hiccup or pgbouncer restart) — without it
/// a one-off infra blip surfaces as a `/process` pipeline failure.
pub async fn acquire_with_retry(
    pool: &PgPool,
    max_retries: u32,
) -> Result<PoolConnection<Postgres>, sqlx::Error> {
    let mut attempt: u32 = 0;
    loop {
        match pool.acquire().await {
            Ok(conn) => return Ok(conn),
            Err(e) if attempt < max_retries && is_transient_error(&e) => {
                attempt += 1;
                metrics::counter!(PG_ACQUIRE_RETRY).increment(1);
                warn!(
                    attempt,
                    max_retries,
                    error = %e,
                    "Transient error acquiring Postgres connection, retrying"
                );
                // Brief linear backoff to let a momentary blip clear before retrying.
                tokio::time::sleep(Duration::from_millis(50 * attempt as u64)).await;
            }
            Err(e) => {
                if is_transient_error(&e) {
                    metrics::counter!(PG_ACQUIRE_RETRY_EXHAUSTED).increment(1);
                }
                return Err(e);
            }
        }
    }
}
