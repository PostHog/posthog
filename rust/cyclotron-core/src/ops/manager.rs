use chrono::{DateTime, Utc};
use uuid::Uuid;

use crate::{
    error::QueueError,
    types::{JobInit, JobState},
};

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
        parameters,
        blob
    )
VALUES
    ($1, $2, $3, NOW(), NULL, NULL, 0, 0, NOW(), $4, $5, $6, $7, $8, $9, $10, $11)
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
        data.parameters,
        data.blob
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
    let mut blob = Vec::with_capacity(jobs.len());

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
        blob.push(d.blob.clone());
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
        parameters,
        blob
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
        $16,
        $17
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
    .bind(blob)
    .execute(executor)
    .await?;

    Ok(())
}
