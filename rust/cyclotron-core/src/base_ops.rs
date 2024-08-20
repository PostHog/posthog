//! # PgQueue
//!
//! A job queue implementation backed by a PostgreSQL table.

use std::str::FromStr;

use chrono::{self, DateTime, Utc};
use serde::{self, Deserialize, Serialize};
use sqlx::{
    postgres::{PgArguments, PgHasArrayType, PgQueryResult, PgTypeInfo},
    query::Query,
};
use uuid::Uuid;

use crate::error::QueueError;

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

impl PgHasArrayType for JobState {
    fn array_type_info() -> sqlx::postgres::PgTypeInfo {
        // Postgres default naming convention for array types is "_typename"
        PgTypeInfo::with_name("_JobState")
    }
}

// The chunk of data needed to enqueue a job
#[derive(Debug, Deserialize, Serialize, Clone, Eq, PartialEq)]
pub struct JobInit {
    pub team_id: i32,
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
    // Job metadata
    pub id: Uuid,
    pub team_id: i32,
    pub function_id: Option<Uuid>, // Some jobs might not come from hog, and it doesn't /kill/ use to support that
    pub created: DateTime<Utc>,

    // Queue bookkeeping
    // This will be set for any worker that ever has a job in the "running" state (so any worker that dequeues a job)
    // but I don't want to do the work to encode that in the type system right now - later it should be
    pub lock_id: Option<Uuid>,
    pub last_heartbeat: Option<DateTime<Utc>>,
    pub janitor_touch_count: i16,
    pub transition_count: i16,
    pub last_transition: DateTime<Utc>,

    // Virtual queue components
    pub queue_name: String, // We can have multiple "virtual queues" workers pull from

    // Job availability
    pub state: JobState,
    pub priority: i16, // For sorting "available" jobs. Lower is higher priority
    pub scheduled: DateTime<Utc>,

    // Job data
    pub vm_state: Option<String>, // The state of the VM this job is running on (if it exists)
    pub metadata: Option<String>, // Additional fields a worker can tack onto a job, for e.g. tracking some state across retries (or number of retries in general by a given class of worker)
    pub parameters: Option<String>, // The actual parameters of the job (function args for a hog function, http request for a fetch function)
}

pub async fn create_job<'c, E>(executor: E, data: JobInit) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let id = Uuid::now_v7();
    sqlx::query!(
        r#"
INSERT INTO cyclotron_jobs
    (
        id,
        team_id,
        function_id,
        created,
        lock_id,
        last_heartbeat,
        janitor_touch_count,
        transition_count,
        last_transition,
        queue_name,
        state,
        scheduled,
        priority,
        vm_state,
        metadata,
        parameters
    )
VALUES
    ($1, $2, $3, NOW(), NULL, NULL, 0, 0, NOW(), $4, $5, $6, $7, $8, $9, $10)
    "#,
        id,
        data.team_id,
        data.function_id,
        data.queue_name,
        JobState::Available as _,
        data.scheduled,
        data.priority,
        data.vm_state,
        data.metadata,
        data.parameters
    )
    .execute(executor)
    .await?;

    Ok(())
}

pub async fn bulk_create_jobs<'c, E>(executor: E, jobs: &[JobInit]) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let now = Utc::now();
    // Flatten these jobs into a series of vecs of arguments PG can unnest
    let mut ids = Vec::with_capacity(jobs.len());
    let mut team_ids = Vec::with_capacity(jobs.len());
    let mut function_ids = Vec::with_capacity(jobs.len());
    let mut created_at = Vec::with_capacity(jobs.len());
    let mut lock_ids = Vec::with_capacity(jobs.len());
    let mut last_heartbeats = Vec::with_capacity(jobs.len());
    let mut janitor_touch_counts = Vec::with_capacity(jobs.len());
    let mut transition_counts = Vec::with_capacity(jobs.len());
    let mut last_transitions = Vec::with_capacity(jobs.len());
    let mut queue_names = Vec::with_capacity(jobs.len());
    let mut states = Vec::with_capacity(jobs.len());
    let mut scheduleds = Vec::with_capacity(jobs.len());
    let mut priorities = Vec::with_capacity(jobs.len());
    let mut vm_states = Vec::with_capacity(jobs.len());
    let mut metadatas = Vec::with_capacity(jobs.len());
    let mut parameters = Vec::with_capacity(jobs.len());

    for d in jobs {
        ids.push(Uuid::now_v7());
        team_ids.push(d.team_id);
        function_ids.push(d.function_id);
        created_at.push(now);
        lock_ids.push(None::<Uuid>);
        last_heartbeats.push(None::<DateTime<Utc>>);
        janitor_touch_counts.push(0);
        transition_counts.push(0);
        last_transitions.push(now);
        queue_names.push(d.queue_name.clone());
        states.push(JobState::Available);
        scheduleds.push(d.scheduled);
        priorities.push(d.priority);
        vm_states.push(d.vm_state.clone());
        metadatas.push(d.metadata.clone());
        parameters.push(d.parameters.clone());
    }

    // Using the "unnest" function to turn an array of rows into a set of rows
    sqlx::query(
        r#"
INSERT INTO cyclotron_jobs
    (
        id,
        team_id,
        function_id,
        created,
        lock_id,
        last_heartbeat,
        janitor_touch_count,
        transition_count,
        last_transition,
        queue_name,
        state,
        scheduled,
        priority,
        vm_state,
        metadata,
        parameters
    )
SELECT *
FROM UNNEST(
        $1,
        $2,
        $3,
        $4,
        $5,
        $6,
        $7,
        $8,
        $9,
        $10,
        $11,
        $12,
        $13,
        $14,
        $15,
        $16
    )
"#,
    )
    .bind(ids)
    .bind(team_ids)
    .bind(function_ids)
    .bind(created_at)
    .bind(lock_ids)
    .bind(last_heartbeats)
    .bind(janitor_touch_counts)
    .bind(transition_counts)
    .bind(last_transitions)
    .bind(queue_names)
    .bind(states)
    .bind(scheduleds)
    .bind(priorities)
    .bind(vm_states)
    .bind(metadatas)
    .bind(parameters)
    .execute(executor)
    .await?;

    Ok(())
}

// Dequeue the next job batch from the queue, skipping VM state since it can be large
pub async fn dequeue_jobs<'c, E>(
    executor: E,
    queue: &str,
    max: usize,
) -> Result<Vec<Job>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    // TODO - right now, locks are completely transient. We could instead have the lock_id act like a
    // "worker_id", and be provided by the caller, which would let workers do less bookkeeping, and make
    // some kinds of debugging easier, but I prefer locks being opaque to workers for now, to avoid any
    // confusion or potential for accidental deadlocking (e.g. if someone persisted the worker_id across
    // process restarts).
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
    NULL as vm_state,
    metadata,
    parameters,
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

// Dequeue a batch of jobs, also returning their VM state. This is an optimisation - you could
// dequeue a batch of jobs and then fetch their VM state in a separate query, but this is hopefully less
// heavy on the DB, if a given worker knows it needs VM state for all dequeue jobs
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

// Grab a jobs VM state - for workers that might sometimes need a jobs vm state, but not always,
// this lets them use dequeue_jobs, and then fetch the states they need. VM state can only be retrieved
// by workers holding a job lock
pub async fn get_vm_state<'c, E>(
    executor: E,
    job_id: Uuid,
    lock_id: Uuid,
) -> Result<Option<String>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    struct VMState {
        vm_state: Option<String>,
    }

    // We use fetch_on here because giving us an unknown ID is an error
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

// A struct representing a set of updates for a job. Outer none values mean "don't update this field",
// with nested none values meaning "set this field to null" for nullable fields
#[derive(Debug, Deserialize, Serialize)]
pub struct JobUpdate {
    pub lock_id: Uuid, // The ID of the lock acquired when this worker dequeued the job, required for any update to be valid
    pub state: Option<JobState>,
    pub queue_name: Option<String>,
    pub priority: Option<i16>,
    pub scheduled: Option<DateTime<Utc>>,
    pub vm_state: Option<Option<String>>,
    pub metadata: Option<Option<String>>,
    pub parameters: Option<Option<String>>,
}

impl JobUpdate {
    pub fn new(lock_id: Uuid) -> Self {
        Self {
            lock_id,
            state: None,
            queue_name: None,
            priority: None,
            scheduled: None,
            vm_state: None,
            metadata: None,
            parameters: None,
        }
    }
}

// TODO - I should think about a bulk-flush interface at /some/ point, although we expect jobs to be
// high variance with respect to work time, so maybe that wouldn't be that useful in the end.
// TODO - this isn't the cheapest way to update a row in a table... I could probably do better by instead
// using a query builder, but I wanted sqlx's nice macro handling, at least while iterating on the schema.
// If/when we start hitting perf issues, this is a good place to start.
// NOTE - this function permits multiple flushes to the same job, without losing the lock on it, but
// high level implementations are recommended to avoid this - ideally, for every de/requeue, there should be
// exactly 2 database operations.
pub async fn flush_job<'c, C>(
    connection: &mut C,
    job_id: Uuid,
    updates: JobUpdate,
) -> Result<(), QueueError>
where
    C: sqlx::Connection<Database = sqlx::Postgres>,
{
    let mut txn = connection.begin().await?;

    // Flushing any job state except "running" is a signal that the worker no longer holds this job
    let job_returned = !matches!(updates.state, Some(JobState::Running));
    let lock_id = updates.lock_id;

    if let Some(state) = updates.state {
        set_state(&mut *txn, job_id, updates.lock_id, state).await?;
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

// Most of the rest of these functions are designed to be used as part of larger transactions, e.g.
// "completing" a job means updating various rows and then marking it complete, and we can build that
// by composing a set of individual queries together using a transaction.
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
    vm_state: Option<String>,
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
    metadata: Option<String>,
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
    parameters: Option<String>,
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

fn throw_if_no_rows(res: PgQueryResult, job: Uuid, lock: Uuid) -> Result<(), QueueError> {
    if res.rows_affected() == 0 {
        Err(QueueError::InvalidLock(lock, job))
    } else {
        Ok(())
    }
}
