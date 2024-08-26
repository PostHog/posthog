use std::sync::atomic::AtomicUsize;

use chrono::{DateTime, Duration, Utc};
use sqlx::PgPool;
use tokio::sync::RwLock;

use crate::{
    config::{DEFAULT_QUEUE_DEPTH_LIMIT, DEFAULT_SHARD_HEALTH_CHECK_INTERVAL},
    ops::{
        manager::{bulk_create_jobs, create_job},
        meta::count_total_waiting_jobs,
    },
    BulkInsertResult, JobInit, ManagerConfig, QueueError,
};

pub struct Shard {
    pub pool: PgPool,
    pub last_healthy: RwLock<DateTime<Utc>>,
    pub check_interval: Duration,
    pub depth_limit: u64,
}

pub struct QueueManager {
    shards: RwLock<Vec<Shard>>,
    next_shard: AtomicUsize,
}

impl QueueManager {
    pub async fn new(config: ManagerConfig) -> Result<Self, QueueError> {
        let mut shards = vec![];
        let depth_limit = config
            .shard_depth_limit
            .unwrap_or(DEFAULT_QUEUE_DEPTH_LIMIT);
        let check_interval = Duration::seconds(
            config
                .shard_depth_check_interval_seconds
                .unwrap_or(DEFAULT_SHARD_HEALTH_CHECK_INTERVAL) as i64,
        );
        for shard in config.shards {
            let pool = shard.connect().await.unwrap();
            let shard = Shard::new(pool, depth_limit, check_interval);
            shards.push(shard);
        }
        Ok(Self {
            shards: RwLock::new(shards),
            next_shard: AtomicUsize::new(0),
        })
    }

    #[doc(hidden)] // Mostly for testing, but safe to expose
    pub fn from_pool(pool: PgPool) -> Self {
        Self {
            shards: RwLock::new(vec![Shard::new(
                pool,
                DEFAULT_QUEUE_DEPTH_LIMIT,
                Duration::seconds(DEFAULT_SHARD_HEALTH_CHECK_INTERVAL as i64),
            )]),
            next_shard: AtomicUsize::new(0),
        }
    }

    pub async fn create_job(&self, init: JobInit) -> Result<(), QueueError> {
        // TODO - here is where a lot of shard health and failover logic will go, eventually.
        let next = self
            .next_shard
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let shards = self.shards.read().await;
        let shard = &shards[next % shards.len()];
        shard.create_job(init).await
    }

    pub async fn create_job_blocking(
        &self,
        init: JobInit,
        timeout: Option<Duration>,
    ) -> Result<(), QueueError> {
        let next = self
            .next_shard
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let shards = self.shards.read().await;
        let shard = &shards[next % shards.len()];
        shard.create_job_blocking(init, timeout).await
    }

    pub async fn bulk_create_jobs(&self, inits: Vec<JobInit>) -> BulkInsertResult {
        let shards = self.shards.read().await;
        let chunk_size = inits.len() / shards.len();
        let mut result = BulkInsertResult::new();
        // TODO - at some point, we should dynamically re-acquire the lock each time, to allow
        // for re-routing jobs away from a bad shard during a bulk insert, but right now, we
        // don't even re-try inserts. Later work.
        for chunk in inits.chunks(chunk_size) {
            let next_shard = self
                .next_shard
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let shard = &shards[next_shard % shards.len()];
            let shard_result = shard.bulk_create_jobs(chunk).await;
            if let Err(err) = shard_result {
                result.add_failure(err, chunk.to_vec());
            }
        }

        result
    }

    pub async fn bulk_create_jobs_blocking(
        &self,
        inits: Vec<JobInit>,
        timeout: Option<Duration>,
    ) -> BulkInsertResult {
        let shards = self.shards.read().await;
        let chunk_size = inits.len() / shards.len();
        let mut result = BulkInsertResult::new();
        for chunk in inits.chunks(chunk_size) {
            let next_shard = self
                .next_shard
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let shard = &shards[next_shard % shards.len()];
            // TODO - we sequentially try each shard, but we could try to parallelize this.
            let shard_result = shard.bulk_create_jobs_blocking(chunk, timeout).await;
            if let Err(err) = shard_result {
                result.add_failure(err, chunk.to_vec());
            }
        }

        result
    }
}

impl Shard {
    pub fn new(pool: PgPool, depth_limit: u64, check_interval: Duration) -> Self {
        Self {
            pool,
            last_healthy: RwLock::new(Utc::now() - check_interval),
            check_interval,
            depth_limit,
        }
    }

    // Inserts a job, failing if the shard is at capacity
    pub async fn create_job(&self, init: JobInit) -> Result<(), QueueError> {
        self.insert_guard().await?;
        create_job(&self.pool, init).await
    }

    // Inserts a vec of jobs, failing if the shard is at capacity. Note "capacity" here just
    // means "it isn't totally full" - if there's "capacity" for 1 job, and this is a vec of
    // 1000, we still insert all 1000.
    pub async fn bulk_create_jobs(&self, inits: &[JobInit]) -> Result<(), QueueError> {
        self.insert_guard().await?;
        bulk_create_jobs(&self.pool, inits).await
    }

    // Inserts a job, blocking until there's capacity (or until the timeout is reached)
    pub async fn create_job_blocking(
        &self,
        init: JobInit,
        timeout: Option<Duration>,
    ) -> Result<(), QueueError> {
        let start = Utc::now();
        while self.is_full().await? {
            tokio::time::sleep(Duration::milliseconds(100).to_std().unwrap()).await;
            if let Some(timeout) = &timeout {
                if Utc::now() - start > *timeout {
                    return Err(QueueError::TimedOutWaitingForCapacity);
                }
            }
        }

        create_job(&self.pool, init).await
    }

    // As above, with the same caveats about what "capacity" means
    pub async fn bulk_create_jobs_blocking(
        &self,
        inits: &[JobInit],
        timeout: Option<Duration>,
    ) -> Result<(), QueueError> {
        let start = Utc::now();
        while self.is_full().await? {
            tokio::time::sleep(Duration::milliseconds(100).to_std().unwrap()).await;
            if let Some(timeout) = &timeout {
                if Utc::now() - start > *timeout {
                    return Err(QueueError::TimedOutWaitingForCapacity);
                }
            }
        }

        bulk_create_jobs(&self.pool, inits).await
    }

    pub async fn insert_guard(&self) -> Result<(), QueueError> {
        if self.is_full().await? {
            return Err(QueueError::ShardFull(self.depth_limit));
        }

        Ok(())
    }

    pub async fn is_full(&self) -> Result<bool, QueueError> {
        let last_healthy = self.last_healthy.read().await;
        // If we were healthy less than the check interval ago, assume we are still
        if Utc::now() - *last_healthy < self.check_interval {
            return Ok(false);
        }

        // Grab a write lock. This constrains the number of concurrent capacity checks
        // to 1, purposefully - if someone spawns a thousand tasks to blockingly create
        // a job, we don't want all of them to be querying the available count at once.
        drop(last_healthy);
        let mut last_healthy = self.last_healthy.write().await;
        // TOCTOU - multiple tasks could be racing to re-do the check, and the firs time one
        // succeeds all the rest should skip it.
        if Utc::now() - *last_healthy < self.check_interval {
            return Ok(false);
        }

        let pending = count_total_waiting_jobs(&self.pool).await?;
        let is_full = pending >= self.depth_limit;
        if !is_full {
            *last_healthy = Utc::now();
        }
        Ok(is_full)
    }
}
