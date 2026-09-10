use std::collections::btree_map::Entry;
use std::collections::BTreeMap;
use std::future::Future;
use std::time::Duration;

use anyhow::Context;
use common_database::is_transient_error;
use common_kafka::kafka_consumer::Offset;

use crate::config::Config;
use crate::metric_consts;
use crate::pipeline::batch::EventWithOffset;
use crate::storage::postgres::PostgresStorage;
use crate::storage::types::{
    DistinctIdAssignmentData, DistinctIdDeletionData, PersonDeletionData, PersonUpdateData,
};
use crate::types::CdcEvent;

#[derive(Debug)]
enum PersonMutation {
    Update(PersonUpdateData),
    Deletion(PersonDeletionData),
}

type DistinctIdKey = (i32, Box<str>);

trait VersionedMutation {
    fn version(&self) -> i64;
    fn is_deletion(&self) -> bool;
}

impl VersionedMutation for PersonMutation {
    fn version(&self) -> i64 {
        match self {
            Self::Update(data) => data.version,
            Self::Deletion(data) => data.version,
        }
    }

    fn is_deletion(&self) -> bool {
        matches!(self, Self::Deletion(_))
    }
}

trait DistinctIdWrite {
    fn version(&self) -> i64;
    fn person_uuid(&self) -> uuid::Uuid;
}

impl DistinctIdWrite for DistinctIdAssignmentData {
    fn version(&self) -> i64 {
        self.version
    }

    fn person_uuid(&self) -> uuid::Uuid {
        self.person_uuid
    }
}

impl DistinctIdWrite for DistinctIdDeletionData {
    fn version(&self) -> i64 {
        self.version
    }

    fn person_uuid(&self) -> uuid::Uuid {
        self.person_uuid
    }
}

fn insert_latest<K: Ord, V: VersionedMutation>(
    mutations: &mut BTreeMap<K, V>,
    key: K,
    candidate: V,
) {
    match mutations.entry(key) {
        Entry::Vacant(entry) => {
            entry.insert(candidate);
        }
        Entry::Occupied(mut entry) => {
            let current = entry.get();
            // Tombstones win version ties so an ambiguous batch cannot resurrect a key.
            if (candidate.version(), candidate.is_deletion())
                > (current.version(), current.is_deletion())
            {
                entry.insert(candidate);
            }
        }
    }
}

fn insert_latest_distinct_id<T: DistinctIdWrite>(
    writes: &mut BTreeMap<DistinctIdKey, T>,
    key: DistinctIdKey,
    candidate: T,
) {
    match writes.entry(key) {
        Entry::Vacant(entry) => {
            entry.insert(candidate);
        }
        Entry::Occupied(mut entry) => {
            let current = entry.get();
            if (candidate.version(), candidate.person_uuid())
                > (current.version(), current.person_uuid())
            {
                entry.insert(candidate);
            }
        }
    }
}

fn reconcile_distinct_id_writes(
    assignments: &mut BTreeMap<DistinctIdKey, DistinctIdAssignmentData>,
    deletions: &mut BTreeMap<DistinctIdKey, DistinctIdDeletionData>,
) {
    let shared_keys: Vec<DistinctIdKey> = assignments
        .keys()
        .filter(|key| deletions.contains_key(*key))
        .cloned()
        .collect();

    for key in shared_keys {
        let assignment = &assignments[&key];
        let deletion = &deletions[&key];
        if assignment.person_uuid != deletion.person_uuid {
            // Snapshot deletes can race moves; keep both so the owner guard decides after assignment.
            continue;
        }

        if assignment.version > deletion.version {
            deletions.remove(&key);
        } else {
            assignments.remove(&key);
        }
    }
}

#[derive(Default)]
struct InputCounts {
    person_updates: u64,
    person_deletions: u64,
    did_assignments: u64,
    did_deletions: u64,
}

impl InputCounts {
    fn record_success(&self) {
        for (operation, count) in [
            ("person_upsert", self.person_updates),
            ("person_delete", self.person_deletions),
            ("did_assign", self.did_assignments),
            ("did_delete", self.did_deletions),
        ] {
            if count > 0 {
                metrics::counter!(metric_consts::MESSAGES_PROCESSED, "operation" => operation)
                    .increment(count);
            }
        }
    }
}

#[derive(Default)]
struct PendingWrites {
    person_mutations: BTreeMap<(i32, uuid::Uuid), PersonMutation>,
    did_assignments: BTreeMap<DistinctIdKey, DistinctIdAssignmentData>,
    did_deletions: BTreeMap<DistinctIdKey, DistinctIdDeletionData>,
    input_counts: InputCounts,
}

impl PendingWrites {
    fn push(&mut self, event: CdcEvent) {
        match event {
            CdcEvent::PersonUpdate {
                team_id,
                person_uuid,
                properties,
                version,
            } => {
                self.input_counts.person_updates += 1;
                insert_latest(
                    &mut self.person_mutations,
                    (team_id, person_uuid),
                    PersonMutation::Update(PersonUpdateData {
                        team_id,
                        person_uuid,
                        properties,
                        version,
                    }),
                );
            }
            CdcEvent::PersonDeletion {
                team_id,
                person_uuid,
                version,
            } => {
                self.input_counts.person_deletions += 1;
                insert_latest(
                    &mut self.person_mutations,
                    (team_id, person_uuid),
                    PersonMutation::Deletion(PersonDeletionData {
                        team_id,
                        person_uuid,
                        version,
                    }),
                );
            }
            CdcEvent::DistinctIdAssignment {
                team_id,
                person_uuid,
                distinct_id,
                version,
            } => {
                self.input_counts.did_assignments += 1;
                insert_latest_distinct_id(
                    &mut self.did_assignments,
                    (team_id, distinct_id.clone()),
                    DistinctIdAssignmentData {
                        team_id,
                        person_uuid,
                        distinct_id,
                        version,
                    },
                );
            }
            CdcEvent::DistinctIdDeletion {
                team_id,
                person_uuid,
                distinct_id,
                version,
            } => {
                self.input_counts.did_deletions += 1;
                insert_latest_distinct_id(
                    &mut self.did_deletions,
                    (team_id, distinct_id.clone()),
                    DistinctIdDeletionData {
                        team_id,
                        person_uuid,
                        distinct_id,
                        version,
                    },
                );
            }
        }
    }

    fn finish(mut self) -> BatchWrites {
        reconcile_distinct_id_writes(&mut self.did_assignments, &mut self.did_deletions);

        let mut writes = BatchWrites {
            did_assignments: self.did_assignments.into_values().collect(),
            did_deletions: self.did_deletions.into_values().collect(),
            input_counts: self.input_counts,
            ..Default::default()
        };

        for mutation in self.person_mutations.into_values() {
            match mutation {
                PersonMutation::Update(data) => writes.person_updates.push(data),
                PersonMutation::Deletion(data) => writes.person_deletions.push(data),
            }
        }
        writes
    }
}

#[derive(Default)]
struct BatchWrites {
    person_updates: Vec<PersonUpdateData>,
    person_deletions: Vec<PersonDeletionData>,
    did_assignments: Vec<DistinctIdAssignmentData>,
    did_deletions: Vec<DistinctIdDeletionData>,
    input_counts: InputCounts,
}

#[cfg(test)]
fn dedupe_events(events: impl IntoIterator<Item = CdcEvent>) -> BatchWrites {
    let mut pending = PendingWrites::default();
    for event in events {
        pending.push(event);
    }
    pending.finish()
}

/// Classify events into operation types, execute DB writes, return offsets.
///
/// Returns offsets only on success — the caller stores them to advance
/// the consumer group. On failure, offsets are dropped so Kafka redelivers
/// the batch on restart.
pub async fn process_batch(
    items: impl Iterator<Item = EventWithOffset>,
    size_hint: usize,
    storage: &PostgresStorage,
    config: &Config,
) -> anyhow::Result<Vec<Offset>> {
    let start = std::time::Instant::now();

    let mut offsets = Vec::with_capacity(size_hint);
    let mut pending = PendingWrites::default();

    for item in items {
        offsets.push(item.offset);
        pending.push(item.event);
    }

    let writes = pending.finish();
    let result = execute_writes(storage, config, &writes).await;

    let elapsed_ms = start.elapsed().as_millis() as f64;
    metrics::histogram!(metric_consts::BATCH_PROCESS_DURATION_MS).record(elapsed_ms);

    result?;
    writes.input_counts.record_success();

    tracing::debug!(batch_size = offsets.len(), "batch processed successfully");
    Ok(offsets)
}

/// Execute all four storage batches with retry handling.
async fn execute_writes(
    storage: &PostgresStorage,
    config: &Config,
    writes: &BatchWrites,
) -> anyhow::Result<()> {
    with_retry(config, || {
        storage.batch_upsert_persons(&writes.person_updates)
    })
    .await?;
    with_retry(config, || {
        storage.batch_delete_persons(&writes.person_deletions)
    })
    .await?;
    with_retry(config, || {
        storage.batch_upsert_distinct_ids(&writes.did_assignments)
    })
    .await?;
    with_retry(config, || {
        storage.batch_delete_distinct_ids(&writes.did_deletions)
    })
    .await?;

    Ok(())
}

/// Retry with exponential backoff on transient DB errors (SQLSTATE-classified).
async fn with_retry<F, Fut, T>(config: &Config, f: F) -> anyhow::Result<T>
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
                    return Err(e).with_context(|| {
                        format!("retries exhausted after {} attempts", attempt + 1)
                    });
                }
                return Err(e.into());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn did_assignment(person_uuid: uuid::Uuid, distinct_id: &str, version: i64) -> CdcEvent {
        CdcEvent::DistinctIdAssignment {
            team_id: 1,
            person_uuid,
            distinct_id: distinct_id.into(),
            version,
        }
    }

    fn did_deletion(person_uuid: uuid::Uuid, distinct_id: &str, version: i64) -> CdcEvent {
        CdcEvent::DistinctIdDeletion {
            team_id: 1,
            person_uuid,
            distinct_id: distinct_id.into(),
            version,
        }
    }

    #[test]
    fn dedupes_person_mutations_by_primary_key_and_version() {
        let update_wins = uuid::Uuid::from_u128(1);
        let deletion_wins = uuid::Uuid::from_u128(2);
        let tied = uuid::Uuid::from_u128(3);
        let writes = dedupe_events([
            CdcEvent::PersonUpdate {
                team_id: 1,
                person_uuid: update_wins,
                properties: serde_json::json!({"version": 1}),
                version: 1,
            },
            CdcEvent::PersonDeletion {
                team_id: 1,
                person_uuid: update_wins,
                version: 3,
            },
            CdcEvent::PersonUpdate {
                team_id: 1,
                person_uuid: update_wins,
                properties: serde_json::json!({"version": 4}),
                version: 4,
            },
            CdcEvent::PersonUpdate {
                team_id: 1,
                person_uuid: deletion_wins,
                properties: serde_json::json!({}),
                version: 5,
            },
            CdcEvent::PersonDeletion {
                team_id: 1,
                person_uuid: deletion_wins,
                version: 6,
            },
            CdcEvent::PersonUpdate {
                team_id: 1,
                person_uuid: tied,
                properties: serde_json::json!({}),
                version: 7,
            },
            CdcEvent::PersonDeletion {
                team_id: 1,
                person_uuid: tied,
                version: 7,
            },
        ]);

        assert_eq!(writes.person_updates.len(), 1);
        assert_eq!(writes.person_updates[0].person_uuid, update_wins);
        assert_eq!(writes.person_updates[0].version, 4);
        assert_eq!(writes.person_deletions.len(), 2);
        assert_eq!(writes.person_deletions[0].person_uuid, deletion_wins);
        assert_eq!(writes.person_deletions[0].version, 6);
        assert_eq!(writes.person_deletions[1].person_uuid, tied);
        assert_eq!(writes.person_deletions[1].version, 7);
    }

    #[test]
    fn cross_owner_assignment_and_deletion_survive_in_both_orders() {
        let old_owner = uuid::Uuid::from_u128(1);
        let new_owner = uuid::Uuid::from_u128(2);
        for order in [[0, 1], [1, 0]] {
            let writes = dedupe_events(order.map(|index| match index {
                0 => did_assignment(new_owner, "did", 11),
                _ => did_deletion(old_owner, "did", 110),
            }));

            assert_eq!(writes.did_assignments.len(), 1);
            assert_eq!(writes.did_assignments[0].person_uuid, new_owner);
            assert_eq!(writes.did_deletions.len(), 1);
            assert_eq!(writes.did_deletions[0].person_uuid, old_owner);
        }
    }

    #[test]
    fn three_cycle_resolves_after_per_operation_dedupe() {
        let owner_a = uuid::Uuid::from_u128(1);
        let owner_b = uuid::Uuid::from_u128(2);
        for order in [
            [0, 1, 2],
            [0, 2, 1],
            [1, 0, 2],
            [1, 2, 0],
            [2, 0, 1],
            [2, 1, 0],
        ] {
            let writes = dedupe_events(order.map(|index| match index {
                0 => did_assignment(owner_a, "did", 1),
                1 => did_deletion(owner_b, "did", 100),
                _ => did_assignment(owner_b, "did", 2),
            }));

            assert!(writes.did_assignments.is_empty());
            assert_eq!(writes.did_deletions.len(), 1);
            assert_eq!(writes.did_deletions[0].person_uuid, owner_b);
            assert_eq!(writes.did_deletions[0].version, 100);
        }
    }

    #[test]
    fn stale_cross_owner_assignment_and_latest_deletion_survive() {
        let stale_owner = uuid::Uuid::from_u128(1);
        let current_owner = uuid::Uuid::from_u128(2);
        for order in [
            [0, 1, 2],
            [0, 2, 1],
            [1, 0, 2],
            [1, 2, 0],
            [2, 0, 1],
            [2, 1, 0],
        ] {
            let writes = dedupe_events(order.map(|index| match index {
                0 => did_assignment(stale_owner, "did", 5),
                1 => did_deletion(current_owner, "did", 100),
                _ => did_deletion(current_owner, "did", 110),
            }));

            assert_eq!(writes.did_assignments.len(), 1);
            assert_eq!(writes.did_assignments[0].person_uuid, stale_owner);
            assert_eq!(writes.did_assignments[0].version, 5);
            assert_eq!(writes.did_deletions.len(), 1);
            assert_eq!(writes.did_deletions[0].person_uuid, current_owner);
            assert_eq!(writes.did_deletions[0].version, 110);
        }
    }

    #[test]
    fn same_owner_assignment_and_deletion_choose_max_version() {
        let owner = uuid::Uuid::from_u128(1);
        for (assignment_version, deletion_version, deletion_wins) in
            [(12, 11, false), (11, 12, true), (13, 13, true)]
        {
            for deletion_first in [false, true] {
                let events = if deletion_first {
                    [
                        did_deletion(owner, "did", deletion_version),
                        did_assignment(owner, "did", assignment_version),
                    ]
                } else {
                    [
                        did_assignment(owner, "did", assignment_version),
                        did_deletion(owner, "did", deletion_version),
                    ]
                };
                let writes = dedupe_events(events);

                assert_eq!(writes.did_assignments.len(), usize::from(!deletion_wins));
                assert_eq!(writes.did_deletions.len(), usize::from(deletion_wins));
                if deletion_wins {
                    assert_eq!(writes.did_deletions[0].version, deletion_version);
                } else {
                    assert_eq!(writes.did_assignments[0].version, assignment_version);
                }
            }
        }
    }
}
