//! Proves the writer guard does the one thing it exists for: get a pool off a connection
//! whose server stopped accepting writes, without restarting the process.
//!
//! `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` reproduces what a demoted Aurora
//! reader looks like to a pooled connection — the socket stays healthy and answers sqlx's
//! ping, but `transaction_read_only` reads `on` and writes are refused with SQLSTATE 25006.

use std::time::Duration;

use common_database::{install_writer_guard, WriterGuard, WriterGuardConfig};
use sqlx::{
    postgres::{PgConnectOptions, PgPoolOptions},
    PgPool, Row,
};

/// Probe on every acquire, so the tests never depend on wall-clock timing.
fn always_probing_guard() -> WriterGuard {
    WriterGuard::new(WriterGuardConfig {
        heartbeat: Duration::ZERO,
        ..Default::default()
    })
}

/// A single-connection pool, so the connection handed back on the second acquire is
/// deterministically the same one the first acquire poisoned.
fn single_connection_pool(pool_opts: PgPoolOptions) -> PgPoolOptions {
    pool_opts.min_connections(0).max_connections(1)
}

async fn backend_pid(pool: &PgPool) -> i32 {
    sqlx::query("SELECT pg_backend_pid()")
        .fetch_one(pool)
        .await
        .expect("pid query failed")
        .get(0)
}

async fn transaction_read_only(pool: &PgPool) -> String {
    sqlx::query_scalar("SHOW transaction_read_only")
        .fetch_one(pool)
        .await
        .expect("read-only setting query failed")
}

/// Turns the pool's one connection into a stand-in for a demoted writer, and returns the
/// backend PID it is running on.
async fn poison_the_pooled_connection(pool: &PgPool) -> i32 {
    let mut conn = pool.acquire().await.expect("acquire failed");
    let pid: i32 = sqlx::query("SELECT pg_backend_pid()")
        .fetch_one(&mut *conn)
        .await
        .expect("pid query failed")
        .get(0);
    sqlx::query("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        .execute(&mut *conn)
        .await
        .expect("failed to set the session read-only");
    drop(conn);
    pid
}

#[sqlx::test]
async fn discards_a_read_only_connection_and_reopens_against_the_writer(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let guard = always_probing_guard();
    let pool = install_writer_guard(single_connection_pool(pool_opts), &guard)
        .connect_with(connect_opts)
        .await
        .expect("connect failed");

    let poisoned_pid = poison_the_pooled_connection(&pool).await;

    // The pool is capped at one connection, so this either reuses the poisoned one or the
    // guard replaced it.
    assert_ne!(
        backend_pid(&pool).await,
        poisoned_pid,
        "the guard should have discarded the read-only connection and opened a new one"
    );
    assert_eq!(
        transaction_read_only(&pool).await,
        "off",
        "the replacement connection should accept writes"
    );

    pool.close().await;
}

#[sqlx::test]
async fn writes_succeed_again_without_restarting_the_pool(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let guard = always_probing_guard();
    let pool = install_writer_guard(single_connection_pool(pool_opts), &guard)
        .connect_with(connect_opts)
        .await
        .expect("connect failed");

    sqlx::query("CREATE TABLE guard_probe (id int primary key)")
        .execute(&pool)
        .await
        .expect("setup failed");

    poison_the_pooled_connection(&pool).await;

    // The write that would have failed with 25006 for the next 30 minutes.
    sqlx::query("INSERT INTO guard_probe (id) VALUES (1)")
        .execute(&pool)
        .await
        .expect("write should succeed on the replacement connection");

    let rows: i64 = sqlx::query_scalar("SELECT count(*) FROM guard_probe")
        .fetch_one(&pool)
        .await
        .expect("count failed");
    assert_eq!(rows, 1);

    pool.close().await;
}

/// The control. Without the guard, sqlx keeps the poisoned connection — its ping succeeds, so
/// `test_before_acquire` sees nothing wrong — and writes stay broken. This is what the
/// production incident looked like, and it is what makes the two tests above meaningful
/// rather than a tautology about a healthy database.
#[sqlx::test]
async fn without_the_guard_the_poisoned_connection_survives_and_writes_fail(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let pool = single_connection_pool(pool_opts)
        .connect_with(connect_opts)
        .await
        .expect("connect failed");

    sqlx::query("CREATE TABLE guard_probe (id int primary key)")
        .execute(&pool)
        .await
        .expect("setup failed");

    let poisoned_pid = poison_the_pooled_connection(&pool).await;

    assert_eq!(
        backend_pid(&pool).await,
        poisoned_pid,
        "sqlx has no reason to drop a connection that pings fine, so it hands the same one back"
    );
    assert_eq!(transaction_read_only(&pool).await, "on");

    let err = sqlx::query("INSERT INTO guard_probe (id) VALUES (1)")
        .execute(&pool)
        .await
        .expect_err("the write should be refused");
    assert!(
        common_database::is_read_only_error(&err),
        "expected SQLSTATE 25006, got {err:?}"
    );

    pool.close().await;
}
