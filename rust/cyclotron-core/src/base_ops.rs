//! # PgQueue
//!
//! A job queue implementation backed by a PostgreSQL table.

use std::str::FromStr;

use chrono::{self, DateTime, Utc};
use serde::{self, Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Deserialize, Serialize, sqlx::Type)]
#[serde(rename_all = "lowercase")]
#[sqlx(type_name = "JobState", rename_all = "lowercase")]
pub enum JobState {
    Available,
    Running,
    Completed,
    Failed,
    Paused,
}

impl FromStr for JobState {
    type Err = ();

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "available" => Ok(JobState::Available),
            "running" => Ok(JobState::Running),
            "completed" => Ok(JobState::Completed),
            "failed" => Ok(JobState::Failed),
            _ => Err(()),
        }
    }
}

#[derive(Debug, Deserialize, Serialize, sqlx::Type, Copy, Clone, Eq, PartialEq)]
#[serde(rename_all = "lowercase")]
#[sqlx(type_name = "WaitingOn", rename_all = "lowercase")]
pub enum WaitingOn {
    Fetch,
    Hog,
}

impl FromStr for WaitingOn {
    type Err = ();

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "fetch" => Ok(WaitingOn::Fetch),
            "hog" => Ok(WaitingOn::Hog),
            _ => Err(()),
        }
    }
}

// The chunk of data needed to enqueue a job
#[derive(Debug, Deserialize, Serialize, Clone, Eq, PartialEq)]
pub struct JobInit {
    pub team_id: i32,
    pub waiting_on: WaitingOn,
    pub queue_name: String,
    pub priority: i16,
    pub scheduled: DateTime<Utc>,
    pub function_id: Option<Uuid>,
    pub vm_state: Option<String>,
    pub parameters: Option<String>,
    pub metadata: Option<String>,
}

// TODO - there are certain things we might want to be on a per-team basis here... the ability to say
// "do not process any jobs for this team" independent of doing an operation on the job table seems powerful,
// but that requires a distinct team table. For now, I'm just making a note that it's something we might
// want (the command to modify the treatment of all jobs associated with a team should only need to be issued and
// processed /once/, not once per job, and should apply to all jobs both currently queued and any future ones). This
// can be added in a progressive way (by adding joins and clauses to the dequeue query), so we don't need to worry about
// it too much up front.
#[derive(Debug, Deserialize, Serialize)]
pub struct Job {
    pub id: Uuid,
    pub team_id: i32,
    pub state: JobState,
    pub waiting_on: WaitingOn,
    pub queue_name: String, // We can have multiple "virtual queues" workers pull from
    pub priority: i16,      // For sorting "available" jobs. Lower is higher priority
    pub function_id: Option<Uuid>, // Some jobs might not come from hog, and it doesn't /kill/ use to support that
    pub created: DateTime<Utc>,
    pub last_transition: DateTime<Utc>, // Last time the state of this job changed (since we transition to running on fetch)
    pub scheduled: DateTime<Utc>, // The next time this job is available to be picked up by a worker (for e.g. sleeping or retry backoff)
    pub transition_count: i16, // Number of times the state of this job has changed (so e.g. we can limit number of fetches a single function does, for example)
    pub vm_state: Option<String>, // The state of the VM this job is running on (if it exists)
    pub metadata: Option<String>, // Additional fields a worker can tack onto a job, for e.g. tracking some state across retries (or number of retries in general by a given class of worker)
    pub parameters: Option<String>, // The actual parameters of the job (function args for a hog function, http request for a fetch function)
}

pub async fn create_job<'c, E>(executor: E, data: JobInit) -> Result<(), sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let id = Uuid::now_v7();
    sqlx::query!(
        r#"
INSERT INTO cyclotron_jobs
    (id, team_id, state, waiting_on, queue_name, priority, function_id, created, last_transition, scheduled, transition_count, vm_state, metadata, parameters)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW(), $8, 0, $9, $10, $11)
    "#,
        id,
        data.team_id,
        JobState::Available as _, // sqlx requires this for inserting custom types
        data.waiting_on as _, // as above
        data.queue_name,
        data.priority,
        data.function_id,
        data.scheduled,
        data.vm_state,
        data.metadata,
        data.parameters,
    ).execute(executor).await?;

    Ok(())
}

// Dequeue the next job batch from the queue, skipping VM state since it can be large
pub async fn dequeue_jobs<'c, E>(
    executor: E,
    queue: &str,
    worker_type: WaitingOn,
    max: usize,
) -> Result<Vec<Job>, sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query_as!(
        Job,
        r#"
WITH available AS (
    SELECT
        id,
        state
    FROM cyclotron_jobs
    WHERE
        state = 'available'::JobState
        AND waiting_on = $1
        AND queue_name = $2
        AND scheduled <= NOW()
    ORDER BY
        priority ASC,
        scheduled ASC
    LIMIT $3
    FOR UPDATE SKIP LOCKED
)
UPDATE cyclotron_jobs
SET
    state = 'running'::JobState,
    last_transition = NOW(),
    transition_count = transition_count + 1
FROM available
WHERE
    cyclotron_jobs.id = available.id
RETURNING
    cyclotron_jobs.id,
    team_id,
    available.state as "state: JobState",
    waiting_on as "waiting_on: WaitingOn",
    queue_name,
    priority,
    function_id,
    created,
    last_transition,
    scheduled,
    transition_count,
    NULL as vm_state,
    metadata,
    parameters
    "#,
        worker_type as _,
        queue,
        max as i64,
    )
    .fetch_all(executor)
    .await
}

// Dequeue a batch of jobs, also returning their VM state. This is an optimisation - you could
// dequeue a batch of jobs and then fetch their VM state in a separate query, but this is hopefully less
// heavy on the DB, if a given worker knows it needs VM state for all dequeue jobs
pub async fn dequeue_with_vm_state<'c, E>(
    executor: E,
    queue: &str,
    worker_type: WaitingOn,
    max: usize,
) -> Result<Vec<Job>, sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query_as!(
        Job,
        r#"
WITH available AS (
    SELECT
        id,
        state
    FROM cyclotron_jobs
    WHERE
        state = 'available'::JobState
        AND waiting_on = $1
        AND queue_name = $2
        AND scheduled <= NOW()
    ORDER BY
        priority ASC,
        scheduled ASC
    LIMIT $3
    FOR UPDATE SKIP LOCKED
)
UPDATE cyclotron_jobs
SET
    state = 'running'::JobState,
    last_transition = NOW(),
    transition_count = transition_count + 1
FROM available
WHERE
    cyclotron_jobs.id = available.id
RETURNING
    cyclotron_jobs.id,
    team_id,
    available.state as "state: JobState",
    waiting_on as "waiting_on: WaitingOn",
    queue_name,
    priority,
    function_id,
    created,
    last_transition,
    scheduled,
    transition_count,
    vm_state,
    metadata,
    parameters
    "#,
        worker_type as _,
        queue,
        max as i64,
    )
    .fetch_all(executor)
    .await
}

// Grab a jobs VM state - for workers that might sometimes need a jobs vm state, but not always,
// this lets them use dequeue_jobs, and then fetch the states they need
pub async fn get_vm_state<'c, E>(executor: E, job_id: Uuid) -> Result<Option<String>, sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    struct VMState {
        vm_state: Option<String>,
    }

    // We use fetch_on here because giving us an unknown ID is an error
    let res = sqlx::query_as!(
        VMState,
        "SELECT vm_state FROM cyclotron_jobs WHERE id = $1",
        job_id
    )
    .fetch_one(executor)
    .await?;

    Ok(res.vm_state)
}

// A struct representing a set of updates for a job. Outer none values mean "don't update this field",
// with nested none values meaning "set this field to null" for nullable fields
#[derive(Debug, Deserialize, Serialize, Default)]
pub struct JobUpdate {
    pub state: Option<JobState>,
    pub waiting_on: Option<WaitingOn>,
    pub queue_name: Option<String>,
    pub priority: Option<i16>,
    pub scheduled: Option<DateTime<Utc>>,
    pub vm_state: Option<Option<String>>,
    pub metadata: Option<Option<String>>,
    pub parameters: Option<Option<String>>,
}

// TODO - I should think about a bulk-flush interface at /some/ point, although we expect jobs to be
// high variance with respect to work time, so maybe that wouldn't be that useful in the end.
// TODO - this isn't the cheapest way to update a row in a table... I could probably do better by instead
// using a query builder, but I wanted sqlx's nice macro handling, at least while iterating on the schema.
// If/when we start hitting perf issues, this is a good place to start.
pub async fn flush_job<'c, C>(
    connection: &mut C,
    job_id: Uuid,
    updates: JobUpdate,
) -> Result<(), sqlx::Error>
where
    C: sqlx::Connection<Database = sqlx::Postgres>,
{
    let mut txn = connection.begin().await?;

    if let Some(state) = updates.state {
        set_state(&mut *txn, job_id, state).await?;
    }

    if let Some(waiting_on) = updates.waiting_on {
        set_waiting_on(&mut *txn, job_id, waiting_on).await?;
    }

    if let Some(queue_name) = updates.queue_name {
        set_queue(&mut *txn, job_id, &queue_name).await?;
    }

    if let Some(priority) = updates.priority {
        set_priority(&mut *txn, job_id, priority).await?;
    }

    if let Some(scheduled) = updates.scheduled {
        set_scheduled(&mut *txn, job_id, scheduled).await?;
    }

    if let Some(vm_state) = updates.vm_state {
        set_vm_state(&mut *txn, job_id, vm_state).await?;
    }

    if let Some(metadata) = updates.metadata {
        set_metadata(&mut *txn, job_id, metadata).await?;
    }

    if let Some(parameters) = updates.parameters {
        set_parameters(&mut *txn, job_id, parameters).await?;
    }

    txn.commit().await?;

    Ok(())
}

// Most of the rest of these functions are designed to be used as part of larger transactions, e.g.
// "completing" a job means updating various rows and then marking it complete, and we can build that
// by composing a set of individual queries together using a transaction.

// Update the state of a job, also tracking the transition count and last transition time
pub async fn set_state<'c, E>(executor: E, job_id: Uuid, state: JobState) -> Result<(), sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query!(
        "UPDATE cyclotron_jobs SET state = $1, last_transition = NOW(), transition_count = transition_count + 1 WHERE id = $2",
        state as _,
        job_id
    )
    .execute(executor)
    .await?;

    Ok(())
}

pub async fn set_waiting_on<'c, E>(
    executor: E,
    job_id: Uuid,
    waiting_on: WaitingOn,
) -> Result<(), sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query!(
        "UPDATE cyclotron_jobs SET waiting_on = $1 WHERE id = $2",
        waiting_on as _,
        job_id
    )
    .execute(executor)
    .await?;

    Ok(())
}

pub async fn set_queue<'c, E>(executor: E, job_id: Uuid, queue: &str) -> Result<(), sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query!(
        "UPDATE cyclotron_jobs SET queue_name = $1 WHERE id = $2",
        queue,
        job_id
    )
    .execute(executor)
    .await?;

    Ok(())
}

pub async fn set_priority<'c, E>(
    executor: E,
    job_id: Uuid,
    priority: i16,
) -> Result<(), sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query!(
        "UPDATE cyclotron_jobs SET priority = $1 WHERE id = $2",
        priority,
        job_id
    )
    .execute(executor)
    .await?;

    Ok(())
}

pub async fn set_scheduled<'c, E>(
    executor: E,
    job_id: Uuid,
    scheduled: DateTime<Utc>,
) -> Result<(), sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query!(
        "UPDATE cyclotron_jobs SET scheduled = $1 WHERE id = $2",
        scheduled,
        job_id
    )
    .execute(executor)
    .await?;

    Ok(())
}

pub async fn set_vm_state<'c, E>(
    executor: E,
    job_id: Uuid,
    vm_state: Option<String>,
) -> Result<(), sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query!(
        "UPDATE cyclotron_jobs SET vm_state = $1 WHERE id = $2",
        vm_state,
        job_id
    )
    .execute(executor)
    .await?;

    Ok(())
}

pub async fn set_metadata<'c, E>(
    executor: E,
    job_id: Uuid,
    metadata: Option<String>,
) -> Result<(), sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query!(
        "UPDATE cyclotron_jobs SET metadata = $1 WHERE id = $2",
        metadata,
        job_id
    )
    .execute(executor)
    .await?;

    Ok(())
}

pub async fn set_parameters<'c, E>(
    executor: E,
    job_id: Uuid,
    parameters: Option<String>,
) -> Result<(), sqlx::Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    sqlx::query!(
        "UPDATE cyclotron_jobs SET parameters = $1 WHERE id = $2",
        parameters,
        job_id
    )
    .execute(executor)
    .await?;

    Ok(())
}
