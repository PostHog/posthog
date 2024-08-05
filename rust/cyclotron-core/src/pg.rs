//! # PgQueue
//!
//! A job queue implementation backed by a PostgreSQL table.
use std::time;
use std::{str::FromStr, sync::Arc};

use async_trait::async_trait;
use chrono::{self, DateTime, Utc};
use serde::{self, Deserialize, Serialize};
use sqlx::postgres::{PgConnectOptions, PgPool, PgPoolOptions};
use tokio::sync::Mutex;
use uuid::Uuid;

#[derive(Debug, Deserialize, Serialize, sqlx::Type)]
#[serde(rename_all = "lowercase")]
#[sqlx(type_name = "job_state", rename_all = "lowercase")]
pub enum JobState {
    Available,
    Running,
    Completed,
    Failed,
}
#[derive(Debug, Deserialize, Serialize, sqlx::Type)]
#[serde(rename_all = "lowercase")]
#[sqlx(type_name = "waiting_on", rename_all = "lowercase")]
pub enum WaitingOn {
    Fetch,
    Hog,
}

// The chunk of data needed to enqueue a job
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub struct JobInit {
    pub team_id: i32,
    pub waiting_on: WaitingOn,
    pub queue_name: Option<String>,
    pub priority: Option<i16>,
    pub function_id: Option<Uuid>,
    pub vm_state: Option<String>,
    pub parameters: Option<String>,
    pub metadata: Option<String>,
    pub scheduled: Option<DateTime<Utc>>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
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

// Dequeue the next job from the queue, skipping VM state since it is expensive to fetch (users should fetch it seperately if)
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
        id
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
    state as "state: JobState",
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

// Grab a jobs VM state
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
