use std::io;
use std::time::Duration;

use personhog_leader::cache::PersonCacheKey;
use personhog_leader::pg::{load_person_from_pg, LoadError};
use sqlx::postgres::{PgConnectOptions, PgPoolOptions};

#[sqlx::test]
async fn an_unanswered_load_fails_and_frees_its_pool_slot(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let pool = pool_opts
        .max_connections(1)
        .acquire_timeout(Duration::from_secs(2))
        .idle_timeout(None)
        .connect_with(connect_opts.clone())
        .await
        .expect("connect failed");
    sqlx::query(
        "CREATE TABLE person_probe (id bigint, team_id int, uuid uuid, properties jsonb, \
         created_at timestamptz, version bigint, is_identified bool, last_seen_at timestamptz, \
         is_deleted bool)",
    )
    .execute(&pool)
    .await
    .expect("create failed");

    let sidecar = PgPoolOptions::new()
        .max_connections(1)
        .connect_with(connect_opts)
        .await
        .expect("sidecar connect failed");
    let mut lock = sidecar.begin().await.expect("begin failed");
    sqlx::query("LOCK TABLE person_probe IN ACCESS EXCLUSIVE MODE")
        .execute(&mut *lock)
        .await
        .expect("lock failed");

    let key = PersonCacheKey {
        team_id: 1,
        person_id: 1,
    };
    let err = load_person_from_pg(&pool, "person_probe", &key)
        .await
        .expect_err("the load should give up at its deadline");
    assert!(
        matches!(&err, LoadError::Query(sqlx::Error::Io(e)) if e.kind() == io::ErrorKind::TimedOut),
        "expected the deadline error, got {err:?}"
    );

    pool.acquire()
        .await
        .expect("the timed-out connection should have freed the pool's only slot");

    sqlx::query(
        "SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity \
         WHERE datname = current_database() AND wait_event_type = 'Lock'",
    )
    .execute(&mut *lock)
    .await
    .expect("terminate failed");
    lock.rollback().await.expect("rollback failed");
    sidecar.close().await;
    pool.close().await;
}
