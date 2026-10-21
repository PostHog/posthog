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
    RaiseOutcome, RaiseResult, RestoreOutcome, RestoreResult, RestoredPerson,
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
        // A lifecycle saga holds no row lock between its steps and later writes an absolute version,
        // so a raise must take the person's mark, or the saga would lower the version it raised.
        let (mark_op_id, claimed_ids) =
            claim_lifecycle_marks(&mut tx, team_id, &uuids, MarkKind::Restore).await?;
        let locked = lock_claimed_persons(&mut tx, team_id, &claimed_ids).await?;

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
        if let Some(op_id) = mark_op_id {
            release_lifecycle_marks(&mut tx, team_id, op_id, MarkKind::Restore).await?;
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

        let restored_ids =
            insert_restored_distinct_ids(&mut tx, team_id, &absent, &inserted).await?;
        // A person listed with distinct ids, none of which could be inserted, would be live with nothing
        // pointing at it; it was inserted in this transaction, so removing it undoes the insert.
        let unreachable: Vec<i64> = absent
            .iter()
            .filter(|p| !p.distinct_ids.is_empty() && !restored_ids.contains_key(&p.uuid))
            .filter_map(|p| inserted.get(&p.uuid).copied())
            .collect();
        if !unreachable.is_empty() {
            sqlx::query!(
                "DELETE FROM posthog_person WHERE team_id = $1 AND id = ANY($2::bigint[])",
                team_id as i32,
                &unreachable
            )
            .execute(&mut *tx)
            .await?;
        }

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
                    let ids = restored_ids.get(&p.uuid).cloned().unwrap_or_default();
                    let outcome = if p.distinct_ids.is_empty() || !ids.is_empty() {
                        RestoreOutcome::Inserted
                    } else {
                        RestoreOutcome::NoDistinctId
                    };
                    return Ok(RestoreResult {
                        uuid: p.uuid,
                        outcome,
                        person_id: if outcome == RestoreOutcome::Inserted {
                            *id
                        } else {
                            0
                        },
                        version: if outcome == RestoreOutcome::Inserted {
                            p.version
                        } else {
                            0
                        },
                        restored_distinct_ids: ids,
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
                    restored_distinct_ids: Vec::new(),
                })
            })
            .collect()
    }
}

/// Insert the requested distinct ids of each person this call inserted, where no row exists for them.
/// Returns the inserted ids by person uuid.
async fn insert_restored_distinct_ids(
    tx: &mut Transaction<'static, Postgres>,
    team_id: i64,
    persons: &[&RestoredPerson],
    inserted: &HashMap<Uuid, i64>,
) -> StorageResult<HashMap<Uuid, Vec<String>>> {
    let mut rows: Vec<(&str, i64, i64, Uuid)> = persons
        .iter()
        .filter_map(|p| inserted.get(&p.uuid).map(|id| (p, *id)))
        .flat_map(|(p, id)| {
            p.distinct_ids
                .iter()
                .map(move |(distinct_id, version)| (distinct_id.as_str(), id, *version, p.uuid))
        })
        .collect();
    if rows.is_empty() {
        return Ok(HashMap::new());
    }
    // Insert in distinct id order, so two calls racing on the same ids cannot deadlock.
    rows.sort_unstable_by(|a, b| a.0.cmp(b.0));
    let done: HashSet<String> = sqlx::query_scalar!(
        r#"
        INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version, is_deleted)
        SELECT f.distinct_id, f.person_id, $1, f.version, false
        FROM UNNEST($2::text[], $3::bigint[], $4::bigint[]) AS f(distinct_id, person_id, version)
        ON CONFLICT (team_id, distinct_id) DO NOTHING
        RETURNING distinct_id as "distinct_id!"
        "#,
        team_id as i32,
        &rows.iter().map(|r| r.0.to_string()).collect::<Vec<_>>(),
        &rows.iter().map(|r| r.1).collect::<Vec<_>>(),
        &rows.iter().map(|r| r.2).collect::<Vec<_>>()
    )
    .fetch_all(&mut **tx)
    .await?
    .into_iter()
    .collect();
    let mut by_person: HashMap<Uuid, Vec<String>> = HashMap::new();
    for (distinct_id, _, _, uuid) in rows {
        if done.contains(distinct_id) {
            by_person
                .entry(uuid)
                .or_default()
                .push(distinct_id.to_string());
        }
    }
    Ok(by_person)
}

/// Lock the claimed persons in id order, keyed by uuid. Locking by id, not uuid, leaves out a person
/// created under a requested uuid after the claim, which holds no mark; it is reported missing.
async fn lock_claimed_persons(
    tx: &mut Transaction<'_, Postgres>,
    team_id: i64,
    claimed_ids: &[i64],
) -> StorageResult<HashMap<Uuid, LockedPerson>> {
    if claimed_ids.is_empty() {
        return Ok(HashMap::new());
    }
    let rows = sqlx::query!(
        r#"
        SELECT id::bigint as "id!", uuid as "uuid!",
               COALESCE(version, 0)::bigint as "version!", is_deleted as "is_deleted!"
        FROM posthog_person
        WHERE team_id = $1 AND id = ANY($2)
        ORDER BY id FOR UPDATE
        "#,
        team_id as i32,
        claimed_ids
    )
    .fetch_all(&mut **tx)
    .await?;
    Ok(rows
        .into_iter()
        .map(|row| {
            (
                row.uuid,
                LockedPerson {
                    id: row.id,
                    version: row.version,
                    is_deleted: row.is_deleted,
                },
            )
        })
        .collect())
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
    // Ingestion waits on these rows with no lock timeout of its own, so no statement may hold
    // them longer than this. It stays under the router's 5 s deadline and above lock_timeout.
    sqlx::query("SET LOCAL statement_timeout = '4s'")
        .execute(&mut *tx)
        .await?;
    Ok(tx)
}
