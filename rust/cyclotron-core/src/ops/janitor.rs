use chrono::{Duration, Utc};
use uuid::Uuid;

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
//
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

// Poison pills are stalled jobs that have been reset by the janitor more than `max_janitor_touched` times.
pub async fn detect_poison_pills<'c, E>(
    executor: E,
    timeout: Duration,
    max_janitor_touched: i16,
) -> Result<Vec<Uuid>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let oldest_valid_heartbeat = Utc::now() - timeout;
    // KLUDGE - the lock_id being set isn't checked here. A job in a running state without a lock id is violating an invariant,
    // and would be useful to report.
    let result = sqlx::query_scalar!(
        r#"
DELETE FROM cyclotron_jobs WHERE state = 'running' AND COALESCE(last_heartbeat, $1) <= $1 AND janitor_touch_count >= $2 returning id
        "#,
        oldest_valid_heartbeat,
        max_janitor_touched
    ).fetch_all(executor)
        .await
        .map_err(QueueError::from)?;

    Ok(result)
}
