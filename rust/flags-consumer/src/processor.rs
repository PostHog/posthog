use std::future::Future;
use std::time::Duration;

use common_database::is_transient_error;

use crate::config::Config;
use crate::metric_consts;
use crate::storage::error::CdcError;
use crate::storage::postgres::{
    DistinctIdAssignmentData, DistinctIdDeletionData, PersonDeletionData, PersonUpdateData,
    PostgresStorage,
};
use crate::types::CdcEvent;

/// Process a batch of CDC events by dispatching them to the appropriate
/// storage methods.
///
/// Events are separated into four categories and executed in order:
/// 1. Person upserts (UNNEST batch)
/// 2. Person deletions (UNNEST batch)
/// 3. Distinct-ID assignments (individual transactions)
/// 4. Distinct-ID deletions (individual)
pub async fn process_batch(
    events: &[CdcEvent],
    storage: &PostgresStorage,
    config: &Config,
) -> Result<(), CdcError> {
    let start = std::time::Instant::now();

    let mut person_updates: Vec<PersonUpdateData> = Vec::new();
    let mut person_deletions: Vec<PersonDeletionData> = Vec::new();
    let mut did_assignments: Vec<DistinctIdAssignmentData> = Vec::new();
    let mut did_deletions: Vec<DistinctIdDeletionData> = Vec::new();

    for event in events {
        match event {
            CdcEvent::PersonUpdate {
                team_id,
                person_uuid,
                properties,
                version,
            } => {
                person_updates.push(PersonUpdateData {
                    team_id: *team_id,
                    person_uuid: *person_uuid,
                    properties: properties.clone(),
                    version: *version,
                });
            }
            CdcEvent::PersonDeletion {
                team_id,
                person_uuid,
                version,
            } => {
                person_deletions.push(PersonDeletionData {
                    team_id: *team_id,
                    person_uuid: *person_uuid,
                    version: *version,
                });
            }
            CdcEvent::DistinctIdAssignment {
                team_id,
                person_uuid,
                distinct_id,
                version,
            } => {
                did_assignments.push(DistinctIdAssignmentData {
                    team_id: *team_id,
                    person_uuid: *person_uuid,
                    distinct_id: distinct_id.clone(),
                    version: *version,
                });
            }
            CdcEvent::DistinctIdDeletion {
                team_id,
                person_uuid,
                distinct_id,
                version,
            } => {
                did_deletions.push(DistinctIdDeletionData {
                    team_id: *team_id,
                    person_uuid: *person_uuid,
                    distinct_id: distinct_id.clone(),
                    version: *version,
                });
            }
        }
    }

    // Execute in order: person upserts, then deletions, then distinct-ID ops.
    if !person_updates.is_empty() {
        with_retry(config, || storage.batch_upsert_persons(&person_updates)).await?;
        metrics::counter!(
            metric_consts::MESSAGES_PROCESSED,
            "operation" => "person_upsert"
        )
        .increment(person_updates.len() as u64);
    }

    if !person_deletions.is_empty() {
        with_retry(config, || storage.batch_delete_persons(&person_deletions)).await?;
        metrics::counter!(
            metric_consts::MESSAGES_PROCESSED,
            "operation" => "person_delete"
        )
        .increment(person_deletions.len() as u64);
    }

    // Distinct-ID operations need individual transactions (two-row atomic
    // update), so they can't be batched via UNNEST. At ~750 msg/s for
    // distinct_ids, individual transactions are fine.
    for assignment in &did_assignments {
        with_retry(config, || storage.upsert_distinct_id(assignment)).await?;
    }
    if !did_assignments.is_empty() {
        metrics::counter!(
            metric_consts::MESSAGES_PROCESSED,
            "operation" => "did_assign"
        )
        .increment(did_assignments.len() as u64);
    }

    for deletion in &did_deletions {
        with_retry(config, || storage.delete_distinct_id(deletion)).await?;
    }
    if !did_deletions.is_empty() {
        metrics::counter!(
            metric_consts::MESSAGES_PROCESSED,
            "operation" => "did_delete"
        )
        .increment(did_deletions.len() as u64);
    }

    let elapsed_ms = start.elapsed().as_millis() as f64;
    metrics::histogram!(metric_consts::BATCH_PROCESS_DURATION_MS).record(elapsed_ms);

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
