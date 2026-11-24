use std::time::Duration;

use common_database::{error_class, install_idle_ping};
use sqlx::{
    postgres::{PgConnectOptions, PgPoolOptions},
    PgPool, Row,
};

/// `#[sqlx::test]` sets a 1 s idle timeout, and its reaper could close the connection under test.
fn single_connection_pool(pool_opts: PgPoolOptions) -> PgPoolOptions {
    pool_opts
        .min_connections(0)
        .max_connections(1)
        .idle_timeout(None)
}

async fn backend_pid(pool: &PgPool) -> i32 {
    sqlx::query("SELECT pg_backend_pid()")
        .fetch_one(pool)
        .await
        .expect("pid query failed")
        .get(0)
}

/// sqlx pings a dropped connection in a spawned task before it goes back to the idle queue. A
/// backend terminated before that ping ends would be caught by the release ping, not the hook.
async fn wait_until_idle(pool: &PgPool) {
    tokio::time::timeout(Duration::from_secs(5), async {
        while pool.num_idle() == 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("the connection did not go back to the idle queue");
}

async fn terminate_backend(connect_opts: PgConnectOptions, pid: i32) {
    let sidecar = PgPoolOptions::new()
        .max_connections(1)
        .connect_with(connect_opts)
        .await
        .expect("sidecar connect failed");
    let terminated: bool = sqlx::query_scalar("SELECT pg_terminate_backend($1, 5000)")
        .bind(pid)
        .fetch_one(&sidecar)
        .await
        .expect("terminate failed");
    assert!(terminated, "expected backend {pid} to exit");
    sidecar.close().await;
}

#[sqlx::test]
async fn replaces_a_dead_connection_idle_past_the_threshold(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let pool = install_idle_ping(single_connection_pool(pool_opts), Duration::ZERO)
        .connect_with(connect_opts.clone())
        .await
        .expect("connect failed");

    let doomed_pid = backend_pid(&pool).await;
    assert_eq!(
        backend_pid(&pool).await,
        doomed_pid,
        "a connection whose ping passes should be kept, not reopened"
    );

    wait_until_idle(&pool).await;
    terminate_backend(connect_opts, doomed_pid).await;

    assert_ne!(
        backend_pid(&pool).await,
        doomed_pid,
        "the acquire ping should have failed on the dead socket and opened a replacement"
    );

    pool.close().await;
}

#[sqlx::test]
async fn skips_the_ping_for_a_connection_idle_under_the_threshold(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let pool = install_idle_ping(single_connection_pool(pool_opts), Duration::from_secs(3600))
        .connect_with(connect_opts.clone())
        .await
        .expect("connect failed");

    let doomed_pid = backend_pid(&pool).await;
    wait_until_idle(&pool).await;
    terminate_backend(connect_opts, doomed_pid).await;

    let err = sqlx::query("SELECT 1")
        .execute(&pool)
        .await
        .expect_err("a dead connection handed out without a ping should fail the query");
    assert!(
        matches!(error_class(&err), "server_shutdown" | "io"),
        "expected the terminated backend's error, got {err:?}"
    );

    pool.close().await;
}
