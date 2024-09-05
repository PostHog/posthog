use chrono::{DateTime, Utc};
use sqlx::{postgres::PgArguments, query::Query};
use uuid::Uuid;

use crate::{
    error::QueueError,
    types::{Bytes, Job, JobState, JobUpdate},
};

use super::meta::throw_if_no_rows;

// Dequeue the next job batch from the queue, skipping VM state since it can be large
pub async fn dequeue_jobs<'c, E>(
    executor: E,
    queue: &str,
    max: usize,
) -> Result<Vec<Job>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    // Transient lock id. This could be a worker ID, or something, but for now it's totally random (per-batch)
    let lock_id = Uuid::now_v7();
    Ok(sqlx::query_as!(
        Job,
        r#"
WITH available AS (
    SELECT
        id,
        state
    FROM cyclotron_jobs
    WHERE
        state = 'available'::JobState
        AND queue_name = $1
        AND scheduled <= NOW()
    ORDER BY
        priority ASC,
        scheduled ASC
    LIMIT $2
    FOR UPDATE SKIP LOCKED
)
UPDATE cyclotron_jobs
SET
    state = 'running'::JobState,
    lock_id = $3,
    last_heartbeat = NOW(),
    last_transition = NOW(),
    transition_count = transition_count + 1
FROM available
WHERE
    cyclotron_jobs.id = available.id
RETURNING
    cyclotron_jobs.id,
    team_id,
    available.state as "state: JobState",
    queue_name,
    priority,
    function_id,
    created,
    last_transition,
    scheduled,
    transition_count,
    NULL::bytea as vm_state,
    metadata,
    parameters,
    blob,
    lock_id,
    last_heartbeat,
    janitor_touch_count
    "#,
        queue,
        max as i64,
        lock_id
    )
    .fetch_all(executor)
    .await?)
}

// Dequeue a batch of jobs, with their VM state.
pub async fn dequeue_with_vm_state<'c, E>(
    executor: E,
    queue: &str,
    max: usize,
) -> Result<Vec<Job>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let lock_id = Uuid::now_v7();
    Ok(sqlx::query_as!(
        Job,
        r#"
WITH available AS (
    SELECT
        id,
        state
    FROM cyclotron_jobs
    WHERE
        state = 'available'::JobState
        AND queue_name = $1
        AND scheduled <= NOW()
    ORDER BY
        priority ASC,
        scheduled ASC
    LIMIT $2
    FOR UPDATE SKIP LOCKED
)
UPDATE cyclotron_jobs
SET
    state = 'running'::JobState,
    lock_id = $3,
    last_heartbeat = NOW(),
    last_transition = NOW(),
    transition_count = transition_count + 1
FROM available
WHERE
    cyclotron_jobs.id = available.id
RETURNING
    cyclotron_jobs.id,
    team_id,
    available.state as "state: JobState",
    queue_name,
    priority,
    function_id,
    created,
    last_transition,
    scheduled,
    transition_count,
    vm_state,
    metadata,
    parameters,
    blob,
    lock_id,
    last_heartbeat,
    janitor_touch_count
    "#,
        queue,
        max as i64,
        lock_id
    )
    .fetch_all(executor)
    .await?)
}

pub async fn get_vm_state<'c, E>(
    executor: E,
    job_id: Uuid,
    lock_id: Uuid,
) -> Result<Option<Bytes>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    struct VMState {
        vm_state: Option<Bytes>,
    }

    let res = sqlx::query_as!(
        VMState,
        "SELECT vm_state FROM cyclotron_jobs WHERE id = $1 AND lock_id = $2",
        job_id,
        lock_id
    )
    .fetch_one(executor)
    .await?;

    Ok(res.vm_state)
}

// TODO - this isn't the cheapest way to update a row in a table... we could probably do better by instead
// using a query builder, but that means no longer using query_as! and query! macros, unfortunately.
// If/when we start hitting perf issues, this is a good place to start.
//
// NOTE - this clears the lock_id when the job state is set to anything other than "running", since that indicates
// the worker is finished with the job. This means subsequent flushes with the same lock_id will fail.
pub async fn flush_job<'c, C>(
    connection: &mut C,
    job_id: Uuid,
    updates: JobUpdate,
) -> Result<(), QueueError>
where
    C: sqlx::Connection<Database = sqlx::Postgres>,
{
    let mut txn = connection.begin().await?;

    let job_returned = !matches!(updates.state, Some(JobState::Running));
    let lock_id = updates.lock_id;

    if let Some(state) = updates.state {
        set_state(&mut *txn, job_id, lock_id, state).await?;
    }

    if let Some(queue_name) = updates.queue_name {
        set_queue(&mut *txn, job_id, &queue_name, lock_id).await?;
    }

    if let Some(priority) = updates.priority {
        set_priority(&mut *txn, job_id, lock_id, priority).await?;
    }

    if let Some(scheduled) = updates.scheduled {
        set_scheduled(&mut *txn, job_id, scheduled, lock_id).await?;
    }

    if let Some(vm_state) = updates.vm_state {
        set_vm_state(&mut *txn, job_id, vm_state, lock_id).await?;
    }

    if let Some(metadata) = updates.metadata {
        set_metadata(&mut *txn, job_id, metadata, lock_id).await?;
    }

    if let Some(parameters) = updates.parameters {
        set_parameters(&mut *txn, job_id, parameters, lock_id).await?;
    }

    if let Some(blob) = updates.blob {
        set_blob(&mut *txn, job_id, blob, lock_id).await?;
    }

    // Calling flush indicates forward progress, so we should touch the heartbeat
    set_heartbeat(&mut *txn, job_id, lock_id).await?;

    // We do this here, instead of in the set_state call, because otherwise the lock_id passed to other
    // updates would be invalid
    if job_returned {
        let query = sqlx::query!(
            "UPDATE cyclotron_jobs SET lock_id = NULL, last_heartbeat = NULL WHERE id = $1 AND lock_id = $2",
            job_id,
            lock_id
        );
        assert_does_update(&mut *txn, job_id, lock_id, query).await?;
    }

    txn.commit().await?;

    Ok(())
}

// ----------------------
// Setters
//
// Most of the rest of these functions are designed to be used as part of larger transactions, e.g.
// "completing" a job means updating various rows and then marking it complete, and we can build that
// by composing a set of individual queries together using a transaction.
//
// ----------------------

// Update the state of a job, also tracking the transition count and last transition time
pub async fn set_state<'c, E>(
    executor: E,
    job_id: Uuid,
    lock_id: Uuid,
    state: JobState,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let q = sqlx::query!(
        r#"UPDATE cyclotron_jobs
            SET state = $1, last_transition = NOW(), transition_count = transition_count + 1
            WHERE id = $2 AND lock_id = $3"#,
        state as _,
        job_id,
        lock_id
    );

    assert_does_update(executor, job_id, lock_id, q).await
}

pub async fn set_queue<'c, E>(
    executor: E,
    job_id: Uuid,
    queue: &str,
    lock_id: Uuid,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let q = sqlx::query!(
        "UPDATE cyclotron_jobs SET queue_name = $1 WHERE id = $2 AND lock_id = $3",
        queue,
        job_id,
        lock_id
    );
    assert_does_update(executor, job_id, lock_id, q).await
}

pub async fn set_priority<'c, E>(
    executor: E,
    job_id: Uuid,
    lock_id: Uuid,
    priority: i16,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let q = sqlx::query!(
        "UPDATE cyclotron_jobs SET priority = $1 WHERE id = $2 AND lock_id = $3",
        priority,
        job_id,
        lock_id
    );
    assert_does_update(executor, job_id, lock_id, q).await
}

pub async fn set_scheduled<'c, E>(
    executor: E,
    job_id: Uuid,
    scheduled: DateTime<Utc>,
    lock_id: Uuid,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let q = sqlx::query!(
        "UPDATE cyclotron_jobs SET scheduled = $1 WHERE id = $2 AND lock_id = $3",
        scheduled,
        job_id,
        lock_id
    );
    assert_does_update(executor, job_id, lock_id, q).await
}

pub async fn set_vm_state<'c, E>(
    executor: E,
    job_id: Uuid,
    vm_state: Option<Bytes>,
    lock_id: Uuid,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let q = sqlx::query!(
        "UPDATE cyclotron_jobs SET vm_state = $1 WHERE id = $2 AND lock_id = $3",
        vm_state,
        job_id,
        lock_id
    );
    assert_does_update(executor, job_id, lock_id, q).await
}

pub async fn set_metadata<'c, E>(
    executor: E,
    job_id: Uuid,
    metadata: Option<Bytes>,
    lock_id: Uuid,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let q = sqlx::query!(
        "UPDATE cyclotron_jobs SET metadata = $1 WHERE id = $2 AND lock_id = $3",
        metadata,
        job_id,
        lock_id
    );
    assert_does_update(executor, job_id, lock_id, q).await
}

pub async fn set_parameters<'c, E>(
    executor: E,
    job_id: Uuid,
    parameters: Option<Bytes>,
    lock_id: Uuid,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let q = sqlx::query!(
        "UPDATE cyclotron_jobs SET parameters = $1 WHERE id = $2 AND lock_id = $3",
        parameters,
        job_id,
        lock_id
    );
    assert_does_update(executor, job_id, lock_id, q).await
}

pub async fn set_blob<'c, E>(
    executor: E,
    job_id: Uuid,
    blob: Option<Bytes>,
    lock_id: Uuid,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let q = sqlx::query!(
        "UPDATE cyclotron_jobs SET blob = $1 WHERE id = $2 AND lock_id = $3",
        blob,
        job_id,
        lock_id
    );
    assert_does_update(executor, job_id, lock_id, q).await
}

pub async fn set_heartbeat<'c, E>(
    executor: E,
    job_id: Uuid,
    lock_id: Uuid,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let q = sqlx::query!(
        "UPDATE cyclotron_jobs SET last_heartbeat = NOW() WHERE id = $1 AND lock_id = $2",
        job_id,
        lock_id
    );
    assert_does_update(executor, job_id, lock_id, q).await
}

// Simple wrapper, that just executes a query and throws an error if no rows were affected
async fn assert_does_update<'c, E>(
    executor: E,
    job_id: Uuid,
    lock_id: Uuid,
    query: Query<'_, sqlx::Postgres, PgArguments>,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let res = query.execute(executor).await?;
    throw_if_no_rows(res, job_id, lock_id)
}
