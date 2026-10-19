use std::future::Future;

use tokio::time::Instant;

pub async fn before_deadline<T, E>(
    deadline: Option<Instant>,
    call: impl Future<Output = Result<T, E>>,
    expired: impl FnOnce() -> E,
) -> Result<T, E> {
    let Some(deadline) = deadline else {
        return call.await;
    };
    // `timeout_at` polls `call` once before it checks the timer. Without this check, an
    // expired deadline still starts the call. A database call then takes a connection and
    // drops it mid-query. When a caller drops a connection mid-query, sqlx pings the
    // connection before it returns the connection to the pool. On a frozen database, that
    // ping never completes.
    if Instant::now() >= deadline {
        return Err(expired());
    }
    tokio::time::timeout_at(deadline, call)
        .await
        .unwrap_or_else(|_| Err(expired()))
}
