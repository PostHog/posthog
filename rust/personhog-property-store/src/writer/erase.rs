//! Erasure of a deleted team's keys from the owned shards, one bounded batch at a time.

use std::time::{Duration, Instant};

use bytes::Bytes;
use metrics::counter;
use slatedb::{Db, WriteBatch};

use super::{PropertyWriter, MAINTENANCE_STEP_TIMEOUT};
use crate::encoding::{encode_key, person_id_of};
use crate::PropertyStoreError;

const ERASE_BATCH_KEYS: usize = 10_000;

impl PropertyWriter {
    /// Deletes every key of a team from the owned shards and returns how many there were.
    pub async fn erase_team(&self, team_id: i64) -> Result<usize, PropertyStoreError> {
        self.erase_team_in_batches(team_id, ERASE_BATCH_KEYS, MAINTENANCE_STEP_TIMEOUT)
            .await
    }

    /// Each batch is scanned, deleted and made durable before the next, so memory stays at one
    /// batch and a restart resumes past the keys already gone. Each batch's I/O is bounded by
    /// `step_timeout`, since SlateDB retries object store errors without limit: a shard that
    /// cannot finish a batch is left for the next pass, and the other shards go on.
    pub async fn erase_team_in_batches(
        &self,
        team_id: i64,
        batch_keys: usize,
        step_timeout: Duration,
    ) -> Result<usize, PropertyStoreError> {
        let batch_keys = batch_keys.max(1);
        let end = Bytes::copy_from_slice(&encode_key(team_id, i64::MAX));
        let mut erased = 0;
        let mut failed = None;
        for (shard, db) in self.open_dbs().await {
            let mut from = 0;
            let mut in_shard = 0;
            let outcome: Result<(), PropertyStoreError> = async {
                loop {
                    let start = Bytes::copy_from_slice(&encode_key(team_id, from));
                    let keys = scan_keys(
                        &db,
                        start..=end.clone(),
                        batch_keys,
                        Instant::now() + step_timeout,
                    )
                    .await?;
                    let Some(last) = keys.last().and_then(|key| person_id_of(key)) else {
                        break;
                    };
                    tokio::time::timeout(step_timeout, delete_keys(&db, &keys))
                        .await
                        .map_err(|_| PropertyStoreError::Timeout)??;
                    in_shard += keys.len();
                    if last == i64::MAX {
                        break;
                    }
                    from = last + 1;
                }
                Ok(())
            }
            .await;
            if in_shard > 0 {
                counter!("personhog_property_store_erased_keys_total").increment(in_shard as u64);
                tracing::info!(
                    team_id,
                    shard,
                    keys = in_shard,
                    "erased a deleted team's keys"
                );
            }
            erased += in_shard;
            if let Err(e) = outcome {
                counter!("personhog_property_store_erase_failures_total", "kind" => e.class())
                    .increment(1);
                tracing::warn!(team_id, shard, error = %e, "erasing a deleted team's keys from a shard stopped; the next pass retries it");
                failed.get_or_insert(e);
            }
        }
        match failed {
            Some(e) => Err(e),
            None => Ok(erased),
        }
    }
}

/// Up to `limit` keys, or those reached by `deadline`: a slow store makes smaller batches, not none.
async fn scan_keys(
    db: &Db,
    range: std::ops::RangeInclusive<Bytes>,
    limit: usize,
    deadline: Instant,
) -> Result<Vec<Bytes>, PropertyStoreError> {
    let deadline = tokio::time::Instant::from_std(deadline);
    let mut keys = Vec::with_capacity(limit);
    let mut found = tokio::time::timeout_at(deadline, db.scan(range))
        .await
        .map_err(|_| PropertyStoreError::Timeout)??;
    while keys.len() < limit {
        match tokio::time::timeout_at(deadline, found.next()).await {
            Ok(next) => match next? {
                Some(kv) => keys.push(kv.key),
                None => break,
            },
            Err(_) if !keys.is_empty() => break,
            Err(_) => return Err(PropertyStoreError::Timeout),
        }
    }
    Ok(keys)
}

async fn delete_keys(db: &Db, keys: &[Bytes]) -> Result<(), PropertyStoreError> {
    let mut batch = WriteBatch::new();
    for key in keys {
        batch.delete(key.clone());
    }
    let written = db.write(batch).await?;
    db.flush().await?;
    written.await_durable().await?;
    Ok(())
}
