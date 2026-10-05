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
    // `timeout_at` polls `call` once before it checks the timer, so an expired deadline
    // still starts the call. A database call then takes a connection and drops it
    // mid-query. sqlx pings a connection that it drops mid-query before it returns the
    // connection to the pool, and on a frozen database that ping never completes.
    if Instant::now() >= deadline {
        return Err(expired());
    }
    tokio::time::timeout_at(deadline, call)
        .await
        .unwrap_or_else(|_| Err(expired()))
}
