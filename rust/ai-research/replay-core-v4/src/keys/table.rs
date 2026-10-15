//! Reads and conditional writes on the v4 key table.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use aws_sdk_dynamodb::error::{ProvideErrorMetadata, SdkError};
use aws_sdk_dynamodb::operation::put_item::PutItemError;
use aws_sdk_dynamodb::types::{KeysAndAttributes, ReturnValuesOnConditionCheckFailure};
use moka::future::Cache;
use rand::Rng;

use super::rows::{Item, Row, RowError, TableKey};

/// DynamoDB's limit on keys in one BatchGetItem request.
const BATCH_GET_LIMIT: usize = 100;

#[derive(Debug, Clone, thiserror::Error)]
pub enum TableError {
    #[error("key table request failed: {0}")]
    Request(String),
    #[error("key table read ran out of time with keys still unread")]
    ReadBudget,
    #[error(transparent)]
    Row(#[from] RowError),
}

/// The result of a conditional put.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PutOutcome {
    /// Our row is now the row at that key.
    Stored,
    /// Another writer stored a row first. The caller adopts it, or drops its data when it is a tombstone.
    Existing(Row),
}

#[async_trait]
pub trait KeyTable: Send + Sync {
    /// Reads rows with strongly consistent reads. A key with no row is absent from the result, and a row that gives no
    /// key reads as `Row::Unusable`.
    async fn batch_get(&self, keys: &[TableKey]) -> Result<HashMap<TableKey, Row>, TableError>;
    /// Stores `row` at `key` unless a row is already there.
    async fn put_if_absent(&self, key: &TableKey, row: &Row) -> Result<PutOutcome, TableError>;
}

pub struct AwsKeyTable {
    client: aws_sdk_dynamodb::Client,
    table: String,
    retry_budget: Duration,
}

impl AwsKeyTable {
    pub fn new(client: aws_sdk_dynamodb::Client, table: String) -> Self {
        Self {
            client,
            table,
            retry_budget: Duration::from_secs(30),
        }
    }
}

/// Throttling, server faults and transport failures pass. Any other error repeats on a retry.
fn transient<E: ProvideErrorMetadata>(error: &SdkError<E>) -> bool {
    match error {
        SdkError::TimeoutError(_) | SdkError::DispatchFailure(_) | SdkError::ResponseError(_) => {
            true
        }
        SdkError::ServiceError(_) => {
            matches!(
                error.code(),
                Some(
                    "ProvisionedThroughputExceededException"
                        | "ThrottlingException"
                        | "RequestLimitExceeded"
                        | "InternalServerError"
                        | "ServiceUnavailable"
                )
            ) || error
                .raw_response()
                .is_some_and(|r| r.status().is_server_error())
        }
        _ => false,
    }
}

fn now() -> i64 {
    chrono::Utc::now().timestamp()
}

/// The v3 backoff: doubling from 50 ms up to 3 s, with jitter so retrying pods spread out.
fn backoff(attempt: u32) -> Duration {
    let ceiling = 3_000u64.min(50u64.saturating_mul(1 << attempt.min(16)));
    Duration::from_millis(rand::thread_rng().gen_range(ceiling / 2..=ceiling))
}

#[async_trait]
impl KeyTable for AwsKeyTable {
    async fn batch_get(&self, keys: &[TableKey]) -> Result<HashMap<TableKey, Row>, TableError> {
        let started = Instant::now();
        let now = now();
        let mut rows = HashMap::new();
        for chunk in keys.chunks(BATCH_GET_LIMIT) {
            let mut pending: Vec<Item> = chunk.iter().map(TableKey::to_item).collect();
            let mut attempt = 0;
            while !pending.is_empty() {
                if attempt > 0 {
                    if started.elapsed() >= self.retry_budget {
                        return Err(TableError::ReadBudget);
                    }
                    tokio::time::sleep(backoff(attempt)).await;
                }
                attempt += 1;
                let request = KeysAndAttributes::builder()
                    .set_keys(Some(pending.clone()))
                    .consistent_read(true)
                    .build()
                    .map_err(|e| TableError::Request(e.to_string()))?;
                let output = match self
                    .client
                    .batch_get_item()
                    .request_items(&self.table, request)
                    .send()
                    .await
                {
                    Ok(output) => output,
                    Err(error) if transient(&error) => continue,
                    Err(error) => return Err(TableError::Request(error.to_string())),
                };
                for item in output
                    .responses()
                    .and_then(|r| r.get(&self.table))
                    .into_iter()
                    .flatten()
                {
                    rows.insert(TableKey::from_item(item)?, Row::read(item, now));
                }
                // DynamoDB returns the keys it skipped under throttling, and they must be asked for again.
                pending = output
                    .unprocessed_keys()
                    .and_then(|u| u.get(&self.table))
                    .map(|u| u.keys().to_vec())
                    .unwrap_or_default();
            }
        }
        Ok(rows)
    }

    async fn put_if_absent(&self, key: &TableKey, row: &Row) -> Result<PutOutcome, TableError> {
        let item = row.to_item(key)?;
        let started = Instant::now();
        let mut attempt = 0;
        let result = loop {
            let result = self
                .client
                .put_item()
                .table_name(&self.table)
                .set_item(Some(item.clone()))
                .condition_expression("attribute_not_exists(pk)")
                .return_values_on_condition_check_failure(
                    ReturnValuesOnConditionCheckFailure::AllOld,
                )
                .send()
                .await;
            match &result {
                Err(error) if transient(error) && started.elapsed() < self.retry_budget => {}
                _ => break result,
            }
            attempt += 1;
            tokio::time::sleep(backoff(attempt)).await;
        };
        match result {
            Ok(_) => Ok(PutOutcome::Stored),
            Err(error) => {
                // A retry after a put that landed meets its own row here, which the caller adopts as it would a winner.
                let Some(PutItemError::ConditionalCheckFailedException(conflict)) =
                    error.as_service_error()
                else {
                    return Err(TableError::Request(error.to_string()));
                };
                if let Some(item) = conflict.item() {
                    return Ok(PutOutcome::Existing(Row::read(item, now())));
                }
                // DynamoDB may omit the winning item, so read it.
                let winner = self.batch_get(std::slice::from_ref(key)).await?.remove(key);
                winner.map(PutOutcome::Existing).ok_or_else(|| {
                    TableError::Request("conditional put lost to a row that is gone".to_owned())
                })
            }
        }
    }
}

/// Caches the rows the table holds, as v3 does.
///
/// The only change a stored key row ever sees is the deletion tombstone, so a cached row is stale only for a deletion,
/// and the cache lifetime bounds how late a writer sees one. A missing row is never cached: another writer may store
/// it at any moment, and a cached miss would make this process store a second key for the same session. An unusable
/// row is not cached either, so a repaired row is seen at once. The cache lifetimes are far shorter than a row's
/// 90 days, so a cached row cannot outlive its expiry by a meaningful time.
pub struct CachedKeyTable<T> {
    inner: T,
    sessions: Cache<TableKey, Row>,
    team_days: Cache<TableKey, Row>,
}

impl<T: KeyTable> CachedKeyTable<T> {
    pub fn new(
        inner: T,
        max_rows: u64,
        session_lifetime: Duration,
        team_day_lifetime: Duration,
    ) -> Self {
        Self {
            inner,
            sessions: Cache::builder()
                .max_capacity(max_rows)
                .time_to_live(session_lifetime)
                .build(),
            team_days: Cache::builder()
                .max_capacity(max_rows)
                .time_to_live(team_day_lifetime)
                .build(),
        }
    }

    async fn hold(&self, key: &TableKey, row: &Row) {
        if !matches!(row, Row::Unusable(_)) {
            self.cache_for(key).insert(key.clone(), row.clone()).await;
        }
    }

    fn cache_for(&self, key: &TableKey) -> &Cache<TableKey, Row> {
        if key.sk.starts_with("session:") {
            &self.sessions
        } else {
            &self.team_days
        }
    }
}

#[async_trait]
impl<T: KeyTable> KeyTable for CachedKeyTable<T> {
    async fn batch_get(&self, keys: &[TableKey]) -> Result<HashMap<TableKey, Row>, TableError> {
        let mut rows = HashMap::new();
        let mut missing = Vec::new();
        for key in keys {
            match self.cache_for(key).get(key).await {
                Some(row) => {
                    rows.insert(key.clone(), row);
                }
                None => missing.push(key.clone()),
            }
        }
        if !missing.is_empty() {
            for (key, row) in self.inner.batch_get(&missing).await? {
                self.hold(&key, &row).await;
                rows.insert(key, row);
            }
        }
        Ok(rows)
    }

    async fn put_if_absent(&self, key: &TableKey, row: &Row) -> Result<PutOutcome, TableError> {
        let outcome = self.inner.put_if_absent(key, row).await?;
        let stored = match &outcome {
            PutOutcome::Stored => row,
            PutOutcome::Existing(winner) => winner,
        };
        self.hold(key, stored).await;
        Ok(outcome)
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::Ordering;

    use super::*;
    use crate::keys::memory::MemoryTable;
    use crate::keys::rows::Unusable;

    fn cached() -> CachedKeyTable<MemoryTable> {
        CachedKeyTable::new(
            MemoryTable::default(),
            100,
            Duration::from_secs(300),
            Duration::from_secs(3600),
        )
    }

    fn team_day_row(wrapped: u8) -> Row {
        Row::TeamDay {
            team_id: 7,
            key_day: "2026-10-15".to_owned(),
            wrapped_key: vec![wrapped],
        }
    }

    #[tokio::test]
    async fn sees_a_row_another_writer_stores_after_a_miss_or_an_unusable_row() {
        let unusable = Row::Unusable(Unusable::Malformed("wrapped_key"));
        for earlier in [None, Some(unusable)] {
            let table = cached();
            let key = TableKey::team_day(7, "2026-10-15");
            if let Some(row) = &earlier {
                table.inner.store(key.clone(), row.clone());
            }
            let first = table.batch_get(std::slice::from_ref(&key)).await.unwrap();
            assert_eq!(first.get(&key), earlier.as_ref());

            table.inner.store(key.clone(), team_day_row(1));
            assert_eq!(
                table
                    .batch_get(std::slice::from_ref(&key))
                    .await
                    .unwrap()
                    .get(&key),
                Some(&team_day_row(1))
            );
        }
    }

    #[tokio::test]
    async fn serves_stored_rows_and_tombstones_from_the_cache() {
        let table = cached();
        let team_day = TableKey::team_day(7, "2026-10-15");
        let session = TableKey::session(7, "019a2f3e-8c00-7000-8000-000000000007");
        table.inner.store(session.clone(), Row::Deleted);
        table.inner.store(team_day.clone(), team_day_row(1));
        let keys = [team_day.clone(), session.clone()];

        table.batch_get(&keys).await.unwrap();
        let rows = table.batch_get(&keys).await.unwrap();
        assert_eq!(table.inner.reads.load(Ordering::SeqCst), 1);
        assert_eq!(rows.get(&session), Some(&Row::Deleted));

        // A lost race returns the winner, and the cache holds the winner rather than the row this writer offered.
        let outcome = table
            .put_if_absent(&team_day, &team_day_row(2))
            .await
            .unwrap();
        assert_eq!(outcome, PutOutcome::Existing(team_day_row(1)));
        assert_eq!(
            table
                .batch_get(std::slice::from_ref(&team_day))
                .await
                .unwrap()[&team_day],
            team_day_row(1)
        );
    }
}
