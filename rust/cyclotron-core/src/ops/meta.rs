use sqlx::postgres::PgQueryResult;
use uuid::Uuid;

use crate::error::QueueError;

pub async fn count_total_waiting_jobs<'c, E>(executor: E) -> Result<u64, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let res = sqlx::query!(
        "SELECT COUNT(*) FROM cyclotron_jobs WHERE state = 'available' AND scheduled <= NOW()",
    )
    .fetch_one(executor)
    .await?;

    let res = res.count.unwrap_or(0);
    Ok(res as u64)
}

pub async fn get_metadata<'c, E>(executor: E, key: &str) -> Result<Option<String>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let res = sqlx::query_scalar!("SELECT value FROM cyclotron_metadata WHERE key = $1", key)
        .fetch_optional(executor)
        .await?;

    Ok(res)
}

// Set metadata key to value, returning the old value if it exists
pub async fn set_metadata<'c, E>(
    executor: E,
    key: &str,
    value: &str,
) -> Result<Option<String>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let res = sqlx::query_scalar!(
        "INSERT INTO cyclotron_metadata (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value RETURNING value",
        key,
        value,
    )
    .fetch_optional(executor)
    .await?;

    Ok(res)
}

pub fn throw_if_no_rows(res: PgQueryResult, job: Uuid, lock: Uuid) -> Result<(), QueueError> {
    if res.rows_affected() == 0 {
        Err(QueueError::InvalidLock(lock, job))
    } else {
        Ok(())
    }
}
