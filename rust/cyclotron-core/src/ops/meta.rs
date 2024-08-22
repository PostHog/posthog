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

pub fn throw_if_no_rows(res: PgQueryResult, job: Uuid, lock: Uuid) -> Result<(), QueueError> {
    if res.rows_affected() == 0 {
        Err(QueueError::InvalidLock(lock, job))
    } else {
        Ok(())
    }
}
