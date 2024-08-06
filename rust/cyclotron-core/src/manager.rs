use std::sync::atomic::AtomicUsize;

use serde::{Deserialize, Serialize};
use sqlx::PgPool;
use tokio::sync::RwLock;

use crate::{
    base_ops::{create_job, JobInit},
    error::QueueError,
    PoolConfig,
};

// TODO - right now, a lot of this sharding stuff will be hollow, but later we'll add logic like
// e.g. routing work to alive shards if one is down, or reporting shard failure, etc.
// TODO - here's also where queue management commands will go, like "downgrade the priority of this function"
// or "pause jobs for this team", but we're going to add those ad-hoc as they're needed, not up front
#[derive(Debug, Serialize, Deserialize)]
pub struct ManagerConfig {
    pub shards: Vec<PoolConfig>,
}

pub struct QueueManager {
    shards: RwLock<Vec<PgPool>>,
    next_shard: AtomicUsize,
}

impl QueueManager {
    pub async fn new(config: ManagerConfig) -> Result<Self, QueueError> {
        let mut shards = vec![];
        for shard in config.shards {
            let pool = shard.connect().await.unwrap();
            shards.push(pool);
        }
        Ok(Self {
            shards: RwLock::new(shards),
            next_shard: AtomicUsize::new(0),
        })
    }

    // Designed mostly to be used for testing, but safe enough to expose publicly
    pub fn from_pool(pool: PgPool) -> Self {
        Self {
            shards: RwLock::new(vec![pool]),
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

        Ok(create_job(shard, init).await?)
    }
}
