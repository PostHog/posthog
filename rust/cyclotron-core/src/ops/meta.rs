use sqlx::{postgres::PgQueryResult, PgPool};
use uuid::Uuid;

use crate::{
    error::{JobError, QueueError},
    DEAD_LETTER_QUEUE,
};

pub async fn count_total_waiting_jobs<'c, E>(executor: E) -> Result<Vec<(u64, String)>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    struct Count {
        count: Option<i64>,
        queue_name: String,
    }

    let res = sqlx::query_as!(
        Count,
        "SELECT COUNT(*), queue_name FROM cyclotron_jobs WHERE state = 'available' AND scheduled <= NOW() GROUP BY queue_name",
    )
    .fetch_all(executor)
    .await?;

    Ok(res
        .into_iter()
        .map(|r| (r.count.unwrap_or(0) as u64, r.queue_name))
        .collect())
}

// Returns an InvalidLock error if the query run did not affect any rows.
pub fn throw_if_no_rows(res: PgQueryResult, job: Uuid, lock: Uuid) -> Result<(), JobError> {
    if res.rows_affected() == 0 {
        Err(JobError::InvalidLock(lock, job))
    } else {
        Ok(())
    }
}

/// Run the latest cyclotron migrations. Panics if the migrations can't be run - failure to run migrations is purposefully fatal.
pub async fn run_migrations(pool: &PgPool) {
    sqlx::migrate!("./migrations")
        .run(pool)
        .await
        .expect("Failed to run migrations");
}

/// Move a job into the dead letter queue, also updating the metadata table. Note that this operation does not
/// require a lock on the job. This is because the janitor needs to DLQ jobs that are stalled. The worker wrapper
/// around this operation should check that the job is "known" (owned by it) before calling this function.
pub async fn dead_letter<'c, E>(executor: E, job: Uuid, reason: &str) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres> + Clone,
{
    // The first thing we do here is forcefully take the lock on this job, ensuring any subsequent worker
    // operations will fail - we do this because the janitor can move jobs out from under workers. We mark
    // the job as "running" and heartbeat so nothing else messes with it.
    let lock = Uuid::now_v7();
    let original_queue_name = sqlx::query_scalar!(
        "UPDATE cyclotron_jobs SET state = 'running', lock_id = $1, last_heartbeat=NOW() WHERE id = $2 returning queue_name",
        lock,
        job
    )
    .fetch_optional(executor.clone())
    .await?;

    let Some(original_queue_name) = original_queue_name else {
        return Err(JobError::UnknownJobId(job).into());
    };

    // Now we add an entry to the dead metadata queue
    sqlx::query!(
        "INSERT INTO cyclotron_dead_letter_metadata (job_id, original_queue_name, reason, dlq_time) VALUES ($1, $2, $3, NOW())",
        job,
        original_queue_name,
        reason
    ).execute(executor.clone()).await?;

    // And finally, we move the job to the dead letter queue. Jobs in the DLQ are "available", because if they ever
    // get moved back to a queue, they should be re-run.
    sqlx::query!(
        "UPDATE cyclotron_jobs SET state = 'available', lock_id = NULL, queue_name = $1 WHERE id = $2",
        DEAD_LETTER_QUEUE,
        job
    )
    .execute(executor)
    .await?;

    Ok(())
}
