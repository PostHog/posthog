use std::sync::atomic::AtomicUsize;

use chrono::{DateTime, Duration, Utc};
use sqlx::PgPool;
use tokio::sync::RwLock;
use uuid::Uuid;

use crate::{
    config::{DEFAULT_QUEUE_DEPTH_LIMIT, DEFAULT_SHARD_HEALTH_CHECK_INTERVAL},
    ops::{
        manager::{bulk_create_jobs_copy, bulk_create_jobs_upsert, create_job},
        meta::count_total_waiting_jobs,
    },
    JobInit, ManagerConfig, QueueError,
};

pub struct Shard {
    pub pool: PgPool,
    pub last_healthy: RwLock<DateTime<Utc>>,
    pub check_interval: Duration,
    pub depth_limit: u64,
    pub should_compress_vm_state: bool,
    pub should_use_bulk_job_copy: bool,
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
        let should_compress_vm_state = config.should_compress_vm_state.unwrap_or(false);
        let should_use_bulk_job_copy = config.should_use_bulk_job_copy.unwrap_or(false);

        for shard in config.shards {
            let pool = shard.connect().await.unwrap();
            let shard = Shard::new(
                pool,
                depth_limit,
                check_interval,
                should_compress_vm_state,
                should_use_bulk_job_copy,
            );
            shards.push(shard);
        }
        Ok(Self {
            shards: RwLock::new(shards),
            next_shard: AtomicUsize::new(0),
        })
    }

    #[doc(hidden)] // Mostly for testing, but safe to expose
    pub fn from_pool(
        pool: PgPool,
        should_compress_vm_state: bool,
        should_use_bulk_job_copy: bool,
    ) -> Self {
        Self {
            shards: RwLock::new(vec![Shard::new(
                pool,
                DEFAULT_QUEUE_DEPTH_LIMIT,
                Duration::seconds(DEFAULT_SHARD_HEALTH_CHECK_INTERVAL as i64),
                should_compress_vm_state,
                should_use_bulk_job_copy,
            )]),
            next_shard: AtomicUsize::new(0),
        }
    }

    pub async fn create_job(&self, init: JobInit) -> Result<Uuid, QueueError> {
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
    ) -> Result<Uuid, QueueError> {
        let next = self
            .next_shard
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let shards = self.shards.read().await;
        let shard = &shards[next % shards.len()];
        shard.create_job_blocking(init, timeout).await
    }

    pub async fn bulk_create_jobs(&self, inits: Vec<JobInit>) -> Result<Vec<Uuid>, QueueError> {
        let next = self
            .next_shard
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let shards = self.shards.read().await;
        shards[next % shards.len()].bulk_create_jobs(inits).await
    }

    pub async fn bulk_create_jobs_blocking(
        &self,
        inits: Vec<JobInit>,
        timeout: Option<Duration>,
    ) -> Result<Vec<Uuid>, QueueError> {
        let next = self
            .next_shard
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let shards = self.shards.read().await;
        shards[next % shards.len()]
            .bulk_create_jobs_blocking(inits, timeout)
            .await
    }
}

impl Shard {
    pub fn new(
        pool: PgPool,
        depth_limit: u64,
        check_interval: Duration,
        should_compress_vm_state: bool,
        should_use_bulk_job_copy: bool,
    ) -> Self {
        Self {
            pool,
            last_healthy: RwLock::new(Utc::now() - check_interval),
            check_interval,
            depth_limit,
            should_compress_vm_state,
            should_use_bulk_job_copy,
        }
    }

    // Inserts a job, failing if the shard is at capacity
    pub async fn create_job(&self, init: JobInit) -> Result<Uuid, QueueError> {
        self.insert_guard().await?;
        create_job(&self.pool, init, self.should_compress_vm_state).await
    }

    // Inserts a vec of jobs, failing if the shard is at capacity. Note "capacity" here just
    // means "it isn't totally full" - if there's "capacity" for 1 job, and this is a vec of
    // 1000, we still insert all 1000.
    pub async fn bulk_create_jobs(&self, inits: Vec<JobInit>) -> Result<Vec<Uuid>, QueueError> {
        self.insert_guard().await?;
        if self.should_use_bulk_job_copy {
            bulk_create_jobs_copy(&self.pool, inits, self.should_compress_vm_state).await
        } else {
            bulk_create_jobs_upsert(&self.pool, inits, self.should_compress_vm_state).await
        }
    }

    // Inserts a job, blocking until there's capacity (or until the timeout is reached)
    pub async fn create_job_blocking(
        &self,
        init: JobInit,
        timeout: Option<Duration>,
    ) -> Result<Uuid, QueueError> {
        let start = Utc::now();
        while self.is_full().await? {
            tokio::time::sleep(Duration::milliseconds(100).to_std().unwrap()).await;
            if let Some(timeout) = &timeout {
                if Utc::now() - start > *timeout {
                    return Err(QueueError::TimedOutWaitingForCapacity);
                }
            }
        }

        create_job(&self.pool, init, self.should_compress_vm_state).await
    }

    // As above, with the same caveats about what "capacity" means
    pub async fn bulk_create_jobs_blocking(
        &self,
        inits: Vec<JobInit>,
        timeout: Option<Duration>,
    ) -> Result<Vec<Uuid>, QueueError> {
        let start = Utc::now();
        while self.is_full().await? {
            tokio::time::sleep(Duration::milliseconds(100).to_std().unwrap()).await;
            if let Some(timeout) = &timeout {
                if Utc::now() - start > *timeout {
                    return Err(QueueError::TimedOutWaitingForCapacity);
                }
            }
        }

        if self.should_use_bulk_job_copy {
            bulk_create_jobs_copy(&self.pool, inits, self.should_compress_vm_state).await
        } else {
            bulk_create_jobs_upsert(&self.pool, inits, self.should_compress_vm_state).await
        }
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
        let total_pending = pending.iter().map(|(count, _)| count).sum::<u64>();
        let is_full = total_pending >= self.depth_limit;
        if !is_full {
            *last_healthy = Utc::now();
        }
        Ok(is_full)
    }
}
