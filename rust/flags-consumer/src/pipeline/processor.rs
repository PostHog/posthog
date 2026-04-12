use std::future::Future;
use std::time::Duration;

use common_database::is_transient_error;
use common_kafka::kafka_consumer::Offset;

use crate::config::Config;
use crate::metric_consts;
use crate::pipeline::batch::EventWithOffset;
use crate::storage::error::CdcError;
use crate::storage::postgres::PostgresStorage;
use crate::storage::types::{
    DistinctIdAssignmentData, DistinctIdDeletionData, PersonDeletionData, PersonUpdateData,
};
use crate::types::CdcEvent;

/// Process a batch of CDC events by dispatching them to the appropriate
/// storage methods.
///
/// Accepts a `drain` iterator over `EventWithOffset` to avoid intermediate
/// allocations — events are moved directly into storage data types while
/// offsets are collected for the caller to store after processing.
///
/// Events are separated into four categories and executed in order:
/// 1. Person upserts (UNNEST batch)
/// 2. Person deletions (UNNEST batch)
/// 3. Distinct-ID assignments (individual transactions)
/// 4. Distinct-ID deletions (individual)
///
/// Returns all offsets regardless of success/failure — the caller decides
/// whether to store them (POC: always store for forward progress).
pub async fn process_batch(
    items: impl Iterator<Item = EventWithOffset>,
    size_hint: usize,
    storage: &PostgresStorage,
    config: &Config,
) -> Vec<Offset> {
    let start = std::time::Instant::now();

    let mut offsets = Vec::with_capacity(size_hint);
    let mut person_updates: Vec<PersonUpdateData> = Vec::new();
    let mut person_deletions: Vec<PersonDeletionData> = Vec::new();
    let mut did_assignments: Vec<DistinctIdAssignmentData> = Vec::new();
    let mut did_deletions: Vec<DistinctIdDeletionData> = Vec::new();

    for item in items {
        offsets.push(item.offset);
        match item.event {
            CdcEvent::PersonUpdate {
                team_id,
                person_uuid,
                properties,
                version,
            } => {
                person_updates.push(PersonUpdateData {
                    team_id,
                    person_uuid,
                    properties,
                    version,
                });
            }
            CdcEvent::PersonDeletion {
                team_id,
                person_uuid,
                version,
            } => {
                person_deletions.push(PersonDeletionData {
                    team_id,
                    person_uuid,
                    version,
                });
            }
            CdcEvent::DistinctIdAssignment {
                team_id,
                person_uuid,
                distinct_id,
                version,
            } => {
                did_assignments.push(DistinctIdAssignmentData {
                    team_id,
                    person_uuid,
                    distinct_id,
                    version,
                });
            }
            CdcEvent::DistinctIdDeletion {
                team_id,
                person_uuid,
                distinct_id,
                version,
            } => {
                did_deletions.push(DistinctIdDeletionData {
                    team_id,
                    person_uuid,
                    distinct_id,
                    version,
                });
            }
        }
    }

    if let Err(e) = execute_writes(
        storage,
        config,
        &person_updates,
        &person_deletions,
        &did_assignments,
        &did_deletions,
    )
    .await
    {
        tracing::error!(
            batch_size = offsets.len(),
            error = %e,
            "batch processing failed, skipping"
        );
    } else {
        tracing::debug!(batch_size = offsets.len(), "batch processed successfully");
    }

    let elapsed_ms = start.elapsed().as_millis() as f64;
    metrics::histogram!(metric_consts::BATCH_PROCESS_DURATION_MS).record(elapsed_ms);

    offsets
}

/// Execute all storage writes for a classified batch.
async fn execute_writes(
    storage: &PostgresStorage,
    config: &Config,
    person_updates: &[PersonUpdateData],
    person_deletions: &[PersonDeletionData],
    did_assignments: &[DistinctIdAssignmentData],
    did_deletions: &[DistinctIdDeletionData],
) -> Result<(), CdcError> {
    if !person_updates.is_empty() {
        with_retry(config, || storage.batch_upsert_persons(person_updates)).await?;
        metrics::counter!(
            metric_consts::MESSAGES_PROCESSED,
            "operation" => "person_upsert"
        )
        .increment(person_updates.len() as u64);
    }

    if !person_deletions.is_empty() {
        with_retry(config, || storage.batch_delete_persons(person_deletions)).await?;
        metrics::counter!(
            metric_consts::MESSAGES_PROCESSED,
            "operation" => "person_delete"
        )
        .increment(person_deletions.len() as u64);
    }

    for assignment in did_assignments {
        with_retry(config, || storage.upsert_distinct_id(assignment)).await?;
    }
    if !did_assignments.is_empty() {
        metrics::counter!(
            metric_consts::MESSAGES_PROCESSED,
            "operation" => "did_assign"
        )
        .increment(did_assignments.len() as u64);
    }

    for deletion in did_deletions {
        with_retry(config, || storage.delete_distinct_id(deletion)).await?;
    }
    if !did_deletions.is_empty() {
        metrics::counter!(
            metric_consts::MESSAGES_PROCESSED,
            "operation" => "did_delete"
        )
        .increment(did_deletions.len() as u64);
    }

    Ok(())
}

/// Retry a fallible async operation with exponential backoff.
///
/// Uses `common_database::is_transient_error()` to classify errors by
/// SQLSTATE. Transient errors (connection loss, deadlock, resource
/// exhaustion) are retried; permanent errors (constraint violations,
/// syntax errors) fail immediately.
async fn with_retry<F, Fut, T>(config: &Config, f: F) -> Result<T, CdcError>
where
    F: Fn() -> Fut,
    Fut: Future<Output = Result<T, sqlx::Error>>,
{
    let mut attempt = 0u32;
    loop {
        match f().await {
            Ok(v) => return Ok(v),
            Err(e) if is_transient_error(&e) && attempt < config.max_retries => {
                attempt += 1;
                let backoff =
                    Duration::from_millis(config.retry_backoff_base_ms * 2u64.pow(attempt - 1));
                tracing::warn!(
                    attempt,
                    max = config.max_retries,
                    backoff_ms = backoff.as_millis() as u64,
                    error = %e,
                    "transient DB error, retrying"
                );
                metrics::counter!(metric_consts::DB_RETRIES).increment(1);
                tokio::time::sleep(backoff).await;
            }
            Err(e) => {
                let transient = is_transient_error(&e);
                metrics::counter!(
                    metric_consts::DB_ERRORS,
                    "transient" => if transient { "true" } else { "false" }
                )
                .increment(1);

                if transient {
                    return Err(CdcError::RetriesExhausted {
                        attempts: attempt + 1,
                        source: e,
                    });
                }
                return Err(CdcError::Database(e));
            }
        }
    }
}
