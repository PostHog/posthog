use std::collections::{HashMap, HashSet};

use async_trait::async_trait;
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

use super::person::{
    bulk_primary_labels, claim_lifecycle_marks, lock_persons_by_uuids, release_lifecycle_marks,
    LockedPerson, MarkKind,
};
use super::{PostgresStorage, DB_QUERY_DURATION};
use crate::storage::error::{StorageError, StorageResult};
use crate::storage::traits::PersonRepair;
use crate::storage::types::{
    DistinctIdRow, DistinctIdWrite, DistinctIdWriteAction, DistinctIdWriteOutcome,
    DistinctIdWriteResult, RaiseOutcome, RaiseResult, RestoreOutcome, RestoreResult,
    RestoredPerson,
};

#[async_trait]
impl PersonRepair for PostgresStorage {
    async fn raise_person_version_floors(
        &self,
        team_id: i64,
        floors: &[(Uuid, i64)],
    ) -> StorageResult<Vec<RaiseResult>> {
        if floors.is_empty() {
            return Ok(Vec::new());
        }
        let labels = bulk_primary_labels("raise_person_version_floors");
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut tx = begin_with_lock_timeout(self).await?;
        let uuids: Vec<Uuid> = floors.iter().map(|(uuid, _)| *uuid).collect();
        let locked = lock_persons_by_uuids(&mut tx, team_id, &uuids).await?;

        let (raise_ids, raise_mins): (Vec<i64>, Vec<i64>) = floors
            .iter()
            .filter_map(|(uuid, min_version)| {
                locked
                    .get(uuid)
                    .filter(|row| !row.is_deleted && row.version < *min_version)
                    .map(|row| (row.id, *min_version))
            })
            .unzip();
        if !raise_ids.is_empty() {
            sqlx::query!(
                r#"
                UPDATE posthog_person p
                SET version = f.min_version
                FROM UNNEST($2::bigint[], $3::bigint[]) AS f(id, min_version)
                WHERE p.team_id = $1 AND p.id = f.id AND p.is_deleted = false
                  AND COALESCE(p.version, 0) < f.min_version
                "#,
                team_id as i32,
                &raise_ids,
                &raise_mins
            )
            .execute(&mut *tx)
            .await?;
        }
        tx.commit().await?;

        Ok(floors
            .iter()
            .map(|(uuid, min_version)| match locked.get(uuid) {
                None => RaiseResult {
                    uuid: *uuid,
                    outcome: RaiseOutcome::Missing,
                    version: 0,
                },
                Some(row) if row.is_deleted => RaiseResult {
                    uuid: *uuid,
                    outcome: RaiseOutcome::NotLive,
                    version: row.version,
                },
                Some(row) if row.version >= *min_version => RaiseResult {
                    uuid: *uuid,
                    outcome: RaiseOutcome::AtOrAbove,
                    version: row.version,
                },
                Some(_) => RaiseResult {
                    uuid: *uuid,
                    outcome: RaiseOutcome::Raised,
                    version: *min_version,
                },
            })
            .collect())
    }

    async fn restore_persons(
        &self,
        team_id: i64,
        persons: &[RestoredPerson],
    ) -> StorageResult<Vec<RestoreResult>> {
        if persons.is_empty() {
            return Ok(Vec::new());
        }
        let labels = bulk_primary_labels("restore_persons");
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut tx = begin_with_lock_timeout(self).await?;
        let uuids: Vec<Uuid> = persons.iter().map(|p| p.uuid).collect();
        let mut existing = lock_persons_by_uuids(&mut tx, team_id, &uuids).await?;

        // Insert in uuid order, so two calls racing on the same uuids cannot deadlock.
        let mut absent: Vec<&RestoredPerson> = persons
            .iter()
            .filter(|p| !existing.contains_key(&p.uuid))
            .collect();
        absent.sort_unstable_by_key(|p| p.uuid);
        let inserted: HashMap<Uuid, i64> = if absent.is_empty() {
            HashMap::new()
        } else {
            sqlx::query!(
                r#"
                INSERT INTO posthog_person (uuid, team_id, properties, properties_last_updated_at,
                                            properties_last_operation, created_at, version,
                                            is_identified, is_deleted)
                SELECT f.uuid, $1, f.properties::jsonb, '{}'::jsonb, '{}'::jsonb, f.created_at,
                       f.version, f.is_identified, false
                FROM UNNEST($2::uuid[], $3::text[], $4::timestamptz[], $5::bigint[], $6::bool[])
                    AS f(uuid, properties, created_at, version, is_identified)
                ON CONFLICT (team_id, uuid) DO NOTHING
                RETURNING id::bigint as "id!", uuid as "uuid!"
                "#,
                team_id as i32,
                &absent.iter().map(|p| p.uuid).collect::<Vec<_>>(),
                &absent
                    .iter()
                    .map(|p| p.properties.to_string())
                    .collect::<Vec<_>>(),
                &absent.iter().map(|p| p.created_at).collect::<Vec<_>>(),
                &absent.iter().map(|p| p.version).collect::<Vec<_>>(),
                &absent.iter().map(|p| p.is_identified).collect::<Vec<_>>()
            )
            .fetch_all(&mut *tx)
            .await?
            .into_iter()
            .map(|row| (row.uuid, row.id))
            .collect()
        };

        // ON CONFLICT DO NOTHING waited for a concurrent insert of the same uuid and skipped it.
        let raced: Vec<Uuid> = absent
            .iter()
            .map(|p| p.uuid)
            .filter(|uuid| !inserted.contains_key(uuid))
            .collect();
        if !raced.is_empty() {
            let late = lock_persons_by_uuids(&mut tx, team_id, &raced).await?;
            if late.len() != raced.len() {
                return Err(StorageError::FailedPrecondition(format!(
                    "person rows changed during restore_persons (team_id={team_id}); retry"
                )));
            }
            existing.extend(late);
        }
        tx.commit().await?;

        persons
            .iter()
            .map(|p| {
                if let Some(id) = inserted.get(&p.uuid) {
                    return Ok(RestoreResult {
                        uuid: p.uuid,
                        outcome: RestoreOutcome::Inserted,
                        person_id: *id,
                        version: p.version,
                    });
                }
                let row = existing.get(&p.uuid).ok_or_else(|| {
                    StorageError::Query(format!("restore_persons did not classify uuid {}", p.uuid))
                })?;
                Ok(RestoreResult {
                    uuid: p.uuid,
                    outcome: if row.is_deleted {
                        RestoreOutcome::ExistsTombstoned
                    } else {
                        RestoreOutcome::ExistsLive
                    },
                    person_id: row.id,
                    version: row.version,
                })
            })
            .collect()
    }

    async fn write_distinct_ids(
        &self,
        team_id: i64,
        writes: &[DistinctIdWrite],
    ) -> StorageResult<Vec<DistinctIdWriteResult>> {
        if writes.is_empty() {
            return Ok(Vec::new());
        }
        let labels = bulk_primary_labels("write_distinct_ids");
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut tx = begin_with_lock_timeout(self).await?;
        let mut target_uuids: Vec<Uuid> = writes.iter().map(|w| w.person_uuid).collect();
        target_uuids.sort_unstable();
        target_uuids.dedup();

        // Marks first, then person rows, then mapping rows: the order the tombstone RPC and
        // ingestion take, so none of them can deadlock with this call.
        let (mark_op_id, _) =
            claim_lifecycle_marks(&mut tx, team_id, &target_uuids, MarkKind::Restore).await?;
        let persons = lock_persons_by_uuids(&mut tx, team_id, &target_uuids).await?;
        let distinct_ids: Vec<String> = writes.iter().map(|w| w.distinct_id.clone()).collect();
        let current = lock_distinct_id_rows(&mut tx, team_id, &distinct_ids).await?;

        let mut outcomes: HashMap<&str, DistinctIdWriteOutcome> = HashMap::new();
        let mut inserts: Vec<(&DistinctIdWrite, i64)> = Vec::new();
        let mut updates: Vec<(&str, i64, bool)> = Vec::new();
        for write in writes {
            let person = persons.get(&write.person_uuid);
            let row = current.get(&write.distinct_id);
            let outcome = match plan_write(write, person, row) {
                Planned::Insert(person_id) => {
                    inserts.push((write, person_id));
                    continue;
                }
                Planned::Update {
                    version,
                    is_deleted,
                } => {
                    updates.push((write.distinct_id.as_str(), version, is_deleted));
                    DistinctIdWriteOutcome::Applied
                }
                Planned::Done(outcome) => outcome,
            };
            outcomes.insert(write.distinct_id.as_str(), outcome);
        }

        if !inserts.is_empty() {
            let inserted: HashSet<String> = sqlx::query_scalar!(
                r#"
                INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version, is_deleted)
                SELECT f.distinct_id, f.person_id, $1, f.version, false
                FROM UNNEST($2::text[], $3::bigint[], $4::bigint[]) AS f(distinct_id, person_id, version)
                ON CONFLICT (team_id, distinct_id) DO NOTHING
                RETURNING distinct_id as "distinct_id!"
                "#,
                team_id as i32,
                &inserts.iter().map(|(w, _)| w.distinct_id.clone()).collect::<Vec<_>>(),
                &inserts.iter().map(|(_, id)| *id).collect::<Vec<_>>(),
                &inserts.iter().map(|(w, _)| w.min_version).collect::<Vec<_>>()
            )
            .fetch_all(&mut *tx)
            .await?
            .into_iter()
            .collect();
            for (write, _) in &inserts {
                // A row a concurrent writer inserted first is not the absent row this write expected.
                let outcome = if inserted.contains(&write.distinct_id) {
                    DistinctIdWriteOutcome::Applied
                } else {
                    DistinctIdWriteOutcome::PreconditionFailed
                };
                outcomes.insert(write.distinct_id.as_str(), outcome);
            }
        }

        if !updates.is_empty() {
            sqlx::query!(
                r#"
                UPDATE posthog_persondistinctid d
                SET version = f.version, is_deleted = f.is_deleted
                FROM UNNEST($2::text[], $3::bigint[], $4::bool[]) AS f(distinct_id, version, is_deleted)
                WHERE d.team_id = $1 AND d.distinct_id = f.distinct_id
                "#,
                team_id as i32,
                &updates.iter().map(|(d, _, _)| d.to_string()).collect::<Vec<_>>(),
                &updates.iter().map(|(_, v, _)| *v).collect::<Vec<_>>(),
                &updates.iter().map(|(_, _, del)| *del).collect::<Vec<_>>()
            )
            .execute(&mut *tx)
            .await?;
        }

        let after = read_distinct_id_rows(&mut tx, team_id, &distinct_ids).await?;
        if let Some(op_id) = mark_op_id {
            release_lifecycle_marks(&mut tx, team_id, op_id, MarkKind::Restore).await?;
        }
        tx.commit().await?;

        Ok(writes
            .iter()
            .map(|write| DistinctIdWriteResult {
                distinct_id: write.distinct_id.clone(),
                outcome: outcomes[write.distinct_id.as_str()],
                row: after.get(&write.distinct_id).cloned(),
            })
            .collect())
    }
}

enum Planned {
    Insert(i64),
    Update { version: i64, is_deleted: bool },
    Done(DistinctIdWriteOutcome),
}

struct LockedRow {
    person_id: i64,
    version: i64,
    is_deleted: bool,
}

/// Decide one mapping write from the locked person and mapping rows. Raise and tombstone act
/// only on a live row of the named person (holding `expected_version` when given); insert only
/// where no row exists. Tombstone accepts a tombstoned owner: that is the stray it removes.
fn plan_write(
    write: &DistinctIdWrite,
    person: Option<&LockedPerson>,
    row: Option<&LockedRow>,
) -> Planned {
    let Some(person) = person else {
        return Planned::Done(DistinctIdWriteOutcome::PersonNotLive);
    };
    if person.is_deleted && write.action != DistinctIdWriteAction::Tombstone {
        return Planned::Done(DistinctIdWriteOutcome::PersonNotLive);
    }
    match (write.action, row) {
        (DistinctIdWriteAction::Insert, None) => Planned::Insert(person.id),
        (DistinctIdWriteAction::Insert, Some(_)) => {
            Planned::Done(DistinctIdWriteOutcome::PreconditionFailed)
        }
        (_, None) => Planned::Done(DistinctIdWriteOutcome::PreconditionFailed),
        (action, Some(row)) => {
            let expected_ok = write.expected_version.is_none_or(|v| v == row.version);
            if row.is_deleted || row.person_id != person.id || !expected_ok {
                return Planned::Done(DistinctIdWriteOutcome::PreconditionFailed);
            }
            match action {
                DistinctIdWriteAction::Raise if row.version >= write.min_version => {
                    Planned::Done(DistinctIdWriteOutcome::Unchanged)
                }
                DistinctIdWriteAction::Raise => Planned::Update {
                    version: write.min_version,
                    is_deleted: false,
                },
                DistinctIdWriteAction::Tombstone => Planned::Update {
                    version: (row.version + 1).max(write.min_version),
                    is_deleted: true,
                },
                DistinctIdWriteAction::Insert => unreachable!("insert handled above"),
            }
        }
    }
}

async fn begin_with_lock_timeout(
    storage: &PostgresStorage,
) -> StorageResult<Transaction<'static, Postgres>> {
    let mut tx = storage.bulk_primary_pool.begin().await?;
    // A held row means a merge, revival or delete in flight: fail fast and let the
    // caller retry instead of queueing behind it.
    sqlx::query("SET LOCAL lock_timeout = '2s'")
        .execute(&mut *tx)
        .await?;
    Ok(tx)
}

async fn lock_distinct_id_rows(
    tx: &mut Transaction<'_, Postgres>,
    team_id: i64,
    distinct_ids: &[String],
) -> StorageResult<HashMap<String, LockedRow>> {
    Ok(sqlx::query!(
        r#"
        SELECT distinct_id as "distinct_id!", person_id as "person_id!",
               COALESCE(version, 0)::bigint as "version!", is_deleted as "is_deleted!"
        FROM posthog_persondistinctid
        WHERE team_id = $1 AND distinct_id = ANY($2)
        ORDER BY distinct_id FOR UPDATE
        "#,
        team_id as i32,
        distinct_ids
    )
    .fetch_all(&mut **tx)
    .await?
    .into_iter()
    .map(|r| {
        (
            r.distinct_id,
            LockedRow {
                person_id: r.person_id,
                version: r.version,
                is_deleted: r.is_deleted,
            },
        )
    })
    .collect())
}

async fn read_distinct_id_rows(
    tx: &mut Transaction<'_, Postgres>,
    team_id: i64,
    distinct_ids: &[String],
) -> StorageResult<HashMap<String, DistinctIdRow>> {
    Ok(sqlx::query!(
        r#"
        SELECT d.distinct_id as "distinct_id!", d.person_id as "person_id!", p.uuid as "person_uuid?",
               COALESCE(d.version, 0)::bigint as "version!", d.is_deleted as "is_deleted!",
               p.is_deleted as "person_is_deleted?"
        FROM posthog_persondistinctid d
        LEFT JOIN posthog_person p ON p.team_id = d.team_id AND p.id = d.person_id
        WHERE d.team_id = $1 AND d.distinct_id = ANY($2)
        "#,
        team_id as i32,
        distinct_ids
    )
    .fetch_all(&mut **tx)
    .await?
    .into_iter()
    .map(|r| {
        (
            r.distinct_id.clone(),
            DistinctIdRow {
                distinct_id: r.distinct_id,
                person_id: r.person_id,
                person_uuid: r.person_uuid,
                version: r.version,
                is_deleted: r.is_deleted,
                person_is_deleted: r.person_is_deleted,
            },
        )
    })
    .collect())
}
