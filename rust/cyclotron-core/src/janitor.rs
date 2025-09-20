use crate::DEAD_LETTER_QUEUE;
use chrono::Duration;
use sqlx::PgPool;

use crate::{
    ops::{
        janitor::{delete_completed_and_failed_jobs, detect_poison_pills, reset_stalled_jobs},
        meta::{count_total_waiting_jobs, dead_letter, run_migrations},
    },
    types::AggregatedDelete,
    PoolConfig, QueueError,
};

// Thin layer on top of the raw janitor operations - mostly just avoids users having to take a dep on sqlx
pub struct Janitor {
    pub pool: PgPool,
}

impl Janitor {
    pub async fn new(config: PoolConfig) -> Result<Self, QueueError> {
        let pool = config.connect().await?;
        Ok(Self { pool })
    }

    pub fn from_pool(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn run_migrations(&self) {
        run_migrations(&self.pool).await;
    }

    pub async fn delete_completed_and_failed_jobs(
        &self,
    ) -> Result<Vec<AggregatedDelete>, QueueError> {
        delete_completed_and_failed_jobs(&self.pool).await
    }

    pub async fn reset_stalled_jobs(&self, timeout: Duration) -> Result<u64, QueueError> {
        reset_stalled_jobs(&self.pool, timeout).await
    }

    pub async fn delete_poison_pills(
        &self,
        timeout: Duration,
        max_janitor_touched: i16,
    ) -> Result<u64, QueueError> {
        let poison = detect_poison_pills(&self.pool, timeout, max_janitor_touched).await?;

        for job in &poison {
            dead_letter(
                &self.pool,
                *job,
                &format!("poison pill detected based on a timeout of {timeout}"),
            )
            .await?;
        }

        Ok(poison.len() as u64)
    }

    pub async fn waiting_jobs(&self) -> Result<Vec<(u64, String)>, QueueError> {
        count_total_waiting_jobs(&self.pool).await
    }

    pub async fn count_dlq_depth(&self) -> Result<u64, QueueError> {
        let result = sqlx::query_scalar!(
            "SELECT COUNT(*) FROM cyclotron_jobs WHERE queue_name = $1",
            DEAD_LETTER_QUEUE
        )
        .fetch_one(&self.pool)
        .await
        .map_err(QueueError::from)?;

        Ok(result.unwrap_or(0) as u64)
    }
}
