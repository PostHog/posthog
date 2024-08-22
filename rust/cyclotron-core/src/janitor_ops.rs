use chrono::{Duration, Utc};

use crate::error::QueueError;

// As a general rule, janitor operations are not queue specific (as in, they don't account for the
// queue name). We can revisit this later, if we decide we need the ability to do janitor operations
// on a per-queue basis.
pub async fn delete_completed_jobs<'c, E>(executor: E) -> Result<u64, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let result = sqlx::query!("DELETE FROM cyclotron_jobs WHERE state = 'completed'")
        .execute(executor)
        .await
        .map_err(QueueError::from)?;

    Ok(result.rows_affected())
}

pub async fn delete_failed_jobs<'c, E>(executor: E) -> Result<u64, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let result = sqlx::query!("DELETE FROM cyclotron_jobs WHERE state = 'failed'")
        .execute(executor)
        .await
        .map_err(QueueError::from)?;

    Ok(result.rows_affected())
}

// Jobs are considered stalled if their lock is held and their last_heartbeat is older than `timeout`.
// NOTE - because this runs on running jobs, it can stall workers trying to flush updates as it
// executes. I need to use some of the load generators alongside explain/analyze to optimise this (and
// the set of DB indexes)
// TODO - this /could/ return the lock_id's held, which might help with debugging (if workers reported
// the lock_id's they dequeue'd), but lets not do that right now.
pub async fn reset_stalled_jobs<'c, E>(executor: E, timeout: Duration) -> Result<u64, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let oldest_valid_heartbeat = Utc::now() - timeout;
    let result = sqlx::query!(r#"
WITH stalled AS (
    SELECT id FROM cyclotron_jobs WHERE state = 'running' AND COALESCE(last_heartbeat, $1) <= $1 FOR UPDATE SKIP LOCKED
)
UPDATE cyclotron_jobs
SET state = 'available', lock_id = NULL, last_heartbeat = NULL, janitor_touch_count = janitor_touch_count + 1
FROM stalled
WHERE cyclotron_jobs.id = stalled.id
    "#,
        oldest_valid_heartbeat
    )
        .execute(executor)
        .await
        .map_err(QueueError::from)?;

    Ok(result.rows_affected())
}

// Poison pills are jobs whose lock is held and whose heartbeat is older than `timeout`, that have
// been returned to the queue by the janitor more than `max_janitor_touched` times.
// NOTE - this has the same performance caveat as reset_stalled_jobs
// TODO - This shoud, instead, move the job row to a dead letter table, for later investigation. Of course,
// rather than doing that, it could just put the job in a "dead letter" state, and no worker or janitor process
// will touch it... maybe the table moving isn't needed? but either way, being able to debug jobs that cause workers
// to stall would be good (and, thinking about it, moving it to a new table means we don't have to clear the lock,
// so have a potential way to trace back to the last worker that died holding the job)
pub async fn delete_poison_pills<'c, E>(
    executor: E,
    timeout: Duration,
    max_janitor_touched: i16,
) -> Result<u64, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let oldest_valid_heartbeat = Utc::now() - timeout;
    // NOTE - we don't check the lock_id here, because it probably doesn't matter (the lock_id should be set if the
    // job state is "running"), but perhaps we should only delete jobs with a set lock_id, and report an error
    // if we find a job with a state of "running" and no lock_id. Also, we delete jobs whose last_heartbeat is
    // null, which again should never happen (dequeuing a job should always set the last_heartbeat), but for
    // robustness sake we may as well handle it
    let result = sqlx::query!(
        r#"
DELETE FROM cyclotron_jobs WHERE state = 'running' AND COALESCE(last_heartbeat, $1) <= $1 AND janitor_touch_count >= $2
        "#,
        oldest_valid_heartbeat,
        max_janitor_touched
    ).execute(executor)
        .await
        .map_err(QueueError::from)?;

    Ok(result.rows_affected())
}
