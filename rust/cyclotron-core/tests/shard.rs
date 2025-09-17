use chrono::{Duration, Utc};
use common::create_new_job;
use cyclotron_core::test_support::Shard;
use sqlx::PgPool;
use tokio::sync::RwLock;

mod common;

pub fn get_shard(db: PgPool) -> Shard {
    Shard {
        pool: db,
        last_healthy: RwLock::new(Utc::now()),
        check_interval: Duration::milliseconds(0), // We always want to check the limit, for these tests
        depth_limit: 10,
        should_compress_vm_state: true, // enabled by default in test suite
        should_use_bulk_job_copy: true, // enabled by default in test suite
    }
}

#[sqlx::test(migrations = "./migrations")]
pub async fn test_shard_limiting(db: PgPool) {
    let shard = get_shard(db.clone());

    // We should be able to insert 10 jobs
    for _ in 0..10 {
        shard.create_job(create_new_job()).await.unwrap();
    }

    // And then we should fail on the 11th
    let result = shard.create_job(create_new_job()).await;
    assert!(result.is_err());
}

#[sqlx::test(migrations = "./migrations")]
pub async fn test_shard_blocking_insert_waits(db: PgPool) {
    let shard = get_shard(db.clone());

    // We should be able to insert 10 jobs
    for _ in 0..10 {
        shard.create_job(create_new_job()).await.unwrap();
    }

    let timeout = Some(Duration::milliseconds(50));

    let start = Utc::now();
    // And then we should fail on the 11th
    let result = shard.create_job_blocking(create_new_job(), timeout).await;
    assert!(result.is_err());

    // We should have waited at least 50ms
    assert!(Utc::now() - start >= Duration::milliseconds(50));
}

#[sqlx::test(migrations = "./migrations")]
pub async fn test_shard_allows_bulk_inserts_beyond_capacity(db: PgPool) {
    let shard = get_shard(db.clone());

    // We should be able to insert 10 jobs
    for _ in 0..9 {
        shard.create_job(create_new_job()).await.unwrap();
    }

    // And then we should be able to bulk insert 1000
    let inits = (0..1000).map(|_| create_new_job()).collect::<Vec<_>>();
    shard.bulk_create_jobs(inits).await.unwrap();

    // And the next insert should fail
    let result = shard.create_job(create_new_job()).await;
    assert!(result.is_err());
}
