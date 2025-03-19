use chrono::{DateTime, Utc};
use sqlx::{postgres::PgPoolCopyExt, Pool, Postgres};
use uuid::Uuid;

use crate::{
    error::QueueError,
    ops::compress::compress_vm_state,
    types::{Bytes, JobInit, JobState},
};
use common_metrics::inc;

// used in bulk_create_jobs_copy
const CSV_NULL: &str = "_NULL_";
const ZERO_VALUE: &str = "0";
const ESTIMATED_RECORD_SIZE: usize = 1024;

pub async fn create_job<'c, E>(
    executor: E,
    mut data: JobInit,
    should_compress_vm_state: bool,
) -> Result<Uuid, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let id = Uuid::now_v7();

    if should_compress_vm_state {
        data.vm_state = compress_vm_state(data.vm_state)?;
    }

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

    Ok(id)
}

pub async fn bulk_create_jobs_upsert<'c, E>(
    executor: E,
    jobs: &[JobInit],
    should_compress_vm_state: bool,
) -> Result<Vec<Uuid>, QueueError>
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
        let vm_state = d.vm_state.clone();
        if should_compress_vm_state {
            vm_states.push(compress_vm_state(vm_state)?);
        } else {
            vm_states.push(vm_state);
        }

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
    .bind(&ids)
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

    Ok(ids)
}

// experimental variant of bulk_create_jobs_upsert using Postgres COPY for batch writes
pub async fn bulk_create_jobs_copy(
    pool: &Pool<Postgres>,
    jobs: &[JobInit],
    should_compress_vm_state: bool,
) -> Result<Vec<Uuid>, QueueError> {
    let copy_in_stmt = format!(
        r#"
COPY cyclotron_jobs (
    id, team_id, function_id, created, lock_id, last_heartbeat,
    janitor_touch_count, transition_count, last_transition, queue_name,
    state, scheduled, priority, vm_state, metadata, parameters, blob
)
FROM STDIN WITH BINARY NULL AS '{}'
"#,
        CSV_NULL
    );

    let mut ids = Vec::with_capacity(jobs.len());
    let now = Utc::now().to_rfc3339();

    // set up CSV in mem buffer for capturing the row data; try to
    // avoid too many buffer extension allocations as we fill it
    let estimated_buffer_size = jobs.len() * ESTIMATED_RECORD_SIZE;
    let buffer = Bytes::with_capacity(estimated_buffer_size);
    let mut csv_writer = csv::WriterBuilder::new()
        .has_headers(false)
        .from_writer(buffer);

    for j in jobs {
        let new_id = Uuid::now_v7();
        ids.push(new_id);

        let mut vm_state = j.vm_state.clone();
        if should_compress_vm_state {
            vm_state = compress_vm_state(vm_state)?;
        }

        // write all columns of CSV record in order defined in COPY stmt
        csv_writer
            .write_field(new_id)
            .map_err(|e| QueueError::CSVError("id", e))?;
        csv_writer
            .write_field(j.team_id.to_string())
            .map_err(|e| QueueError::CSVError("team_id", e))?;
        if let Some(id) = j.function_id {
            csv_writer
                .write_field(id.to_string())
                .map_err(|e| QueueError::CSVError("function_id", e))?;
        } else {
            csv_writer
                .write_field(CSV_NULL)
                .map_err(|e| QueueError::CSVError("null_function_id", e))?;
        }
        csv_writer
            .write_field(&now)
            .map_err(|e| QueueError::CSVError("created", e))?;
        csv_writer
            .write_field(CSV_NULL)
            .map_err(|e| QueueError::CSVError("lock_id", e))?;
        csv_writer
            .write_field(CSV_NULL)
            .map_err(|e| QueueError::CSVError("last_heartbeat", e))?;
        csv_writer
            .write_field(ZERO_VALUE)
            .map_err(|e| QueueError::CSVError("janitor_touch_count", e))?;
        csv_writer
            .write_field(ZERO_VALUE)
            .map_err(|e| QueueError::CSVError("transition_count", e))?;
        csv_writer
            .write_field(&now)
            .map_err(|e| QueueError::CSVError("last_transition", e))?;
        csv_writer
            .write_field(&j.queue_name)
            .map_err(|e| QueueError::CSVError("queue_name", e))?;
        csv_writer
            .write_field((JobState::Available as u32).to_string())
            .map_err(|e| QueueError::CSVError("state", e))?;
        csv_writer
            .write_field(j.scheduled.to_string())
            .map_err(|e| QueueError::CSVError("scheduled", e))?;
        csv_writer
            .write_field(j.priority.to_string())
            .map_err(|e| QueueError::CSVError("priority", e))?;
        if let Some(vs) = vm_state {
            csv_writer
                .write_field(vs)
                .map_err(|e| QueueError::CSVError("vm_state", e))?;
        } else {
            csv_writer
                .write_field(CSV_NULL)
                .map_err(|e| QueueError::CSVError("null_vm_state", e))?;
        }
        if let Some(m) = &j.metadata {
            csv_writer
                .write_field(&m[..])
                .map_err(|e| QueueError::CSVError("metadata", e))?;
        } else {
            csv_writer
                .write_field(CSV_NULL)
                .map_err(|e| QueueError::CSVError("null_metadata", e))?;
        }
        if let Some(ps) = &j.parameters {
            csv_writer
                .write_field(&ps[..])
                .map_err(|e| QueueError::CSVError("parameters", e))?;
        } else {
            csv_writer
                .write_field(CSV_NULL)
                .map_err(|e| QueueError::CSVError("null_parameters", e))?;
        }
        if let Some(b) = &j.blob {
            csv_writer
                .write_field(&b[..])
                .map_err(|e| QueueError::CSVError("blob", e))?;
        } else {
            csv_writer
                .write_field(CSV_NULL)
                .map_err(|e| QueueError::CSVError("null_blob", e))?;
        }

        csv_writer
            .write_record(None::<&[u8]>)
            .map_err(|e| QueueError::CSVError("csv_row", e))?; // terminate CSV row
    }

    csv_writer
        .flush()
        .map_err(|e| QueueError::CSVError("csv_flush", e.into()))?;

    let mut stream = pool.copy_in_raw(&copy_in_stmt).await?;
    let _ = stream.send(&csv_writer.get_ref()[..]).await?;
    let rows_affected = stream.finish().await?;
    inc("bulk_create_jobs_copy_rows_affected", &[], rows_affected);

    Ok(ids)
}
