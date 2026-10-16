use async_trait::async_trait;
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

use super::person::{
    bulk_primary_labels, claim_lifecycle_marks, lock_persons_by_uuids, release_lifecycle_marks,
    MarkKind,
};
use super::{PostgresStorage, DB_QUERY_DURATION};
use crate::storage::error::StorageResult;
use crate::storage::traits::PersonRepair;
use crate::storage::types::{RaiseOutcome, RaiseResult};

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
        let (mark_op_id, _) =
            claim_lifecycle_marks(&mut tx, team_id, &uuids, MarkKind::Restore).await?;
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
