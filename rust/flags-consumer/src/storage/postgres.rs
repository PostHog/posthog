use std::sync::LazyLock;

use chrono::{DateTime, Utc};
use sqlx::postgres::PgPool;
use uuid::Uuid;

use crate::metric_consts;
use crate::storage::types::{
    DistinctIdAssignmentData, DistinctIdDeletionData, PersonDeletionData, PersonUpdateData,
};

static LABELS_PERSON_UPSERT: LazyLock<[(String, String); 1]> =
    LazyLock::new(|| [("operation".to_string(), "person_upsert".to_string())]);
static LABELS_PERSON_DELETE: LazyLock<[(String, String); 1]> =
    LazyLock::new(|| [("operation".to_string(), "person_delete".to_string())]);
static LABELS_DID_ASSIGN: LazyLock<[(String, String); 1]> =
    LazyLock::new(|| [("operation".to_string(), "did_assign".to_string())]);
static LABELS_DID_DELETE: LazyLock<[(String, String); 1]> =
    LazyLock::new(|| [("operation".to_string(), "did_delete".to_string())]);
static LABELS_HEARTBEAT: LazyLock<[(String, String); 1]> =
    LazyLock::new(|| [("operation".to_string(), "heartbeat".to_string())]);

/// PostgreSQL handle for the dedicated `flags_read_store` database.
pub struct PostgresStorage {
    pub pool: PgPool,
}

impl PostgresStorage {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Startup connectivity check.
    pub async fn ping(&self) -> Result<(), sqlx::Error> {
        sqlx::query_scalar::<_, i32>("SELECT 1")
            .fetch_one(&self.pool)
            .await
            .map(|_| ())
    }

    /// Batch-upsert person properties via UNNEST.
    /// Version guard: only newer versions overwrite existing rows.
    pub async fn batch_upsert_persons(
        &self,
        updates: &[PersonUpdateData],
    ) -> Result<u64, sqlx::Error> {
        if updates.is_empty() {
            return Ok(0);
        }

        let _timer = common_metrics::timing_guard(
            metric_consts::DB_QUERY_DURATION_MS,
            &*LABELS_PERSON_UPSERT,
        );

        let team_ids: Vec<i32> = updates.iter().map(|u| u.team_id).collect();
        let person_uuids: Vec<Uuid> = updates.iter().map(|u| u.person_uuid).collect();
        let properties: Vec<serde_json::Value> =
            updates.iter().map(|u| u.properties.clone()).collect();
        let versions: Vec<i64> = updates.iter().map(|u| u.version).collect();

        let result = sqlx::query(
            r#"
            INSERT INTO flags_person_lookup (team_id, person_uuid, properties, person_version)
                SELECT * FROM UNNEST($1::int[], $2::uuid[], $3::jsonb[], $4::bigint[])
            ON CONFLICT (team_id, person_uuid) DO UPDATE SET
                properties = EXCLUDED.properties,
                person_version = EXCLUDED.person_version,
                deleted_at = NULL
            WHERE flags_person_lookup.person_version < EXCLUDED.person_version
            "#,
        )
        .bind(&team_ids)
        .bind(&person_uuids)
        .bind(&properties)
        .bind(&versions)
        .execute(&self.pool)
        .await?;

        Ok(result.rows_affected())
    }

    /// Soft-delete: keep the row so the upsert's version guard can still
    /// reject stale `PersonUpdate` messages arriving after the delete.
    /// The incoming version includes a +100 bump from the producer for deletions.
    /// `distinct_ids` is cleared so the GIN index can't surface tombstoned rows.
    pub async fn batch_delete_persons(
        &self,
        deletions: &[PersonDeletionData],
    ) -> Result<u64, sqlx::Error> {
        if deletions.is_empty() {
            return Ok(0);
        }

        let _timer = common_metrics::timing_guard(
            metric_consts::DB_QUERY_DURATION_MS,
            &*LABELS_PERSON_DELETE,
        );

        let team_ids: Vec<i32> = deletions.iter().map(|d| d.team_id).collect();
        let person_uuids: Vec<Uuid> = deletions.iter().map(|d| d.person_uuid).collect();
        let versions: Vec<i64> = deletions.iter().map(|d| d.version).collect();

        let result = sqlx::query(
            r#"
            INSERT INTO flags_person_lookup
                (team_id, person_uuid, distinct_ids, properties, person_version, deleted_at)
                SELECT team_id, person_uuid, ARRAY[]::text[], '{}'::jsonb, version, NOW()
                FROM UNNEST($1::int[], $2::uuid[], $3::bigint[])
                    AS t(team_id, person_uuid, version)
            ON CONFLICT (team_id, person_uuid) DO UPDATE SET
                distinct_ids = ARRAY[]::text[],
                properties = '{}'::jsonb,
                person_version = EXCLUDED.person_version,
                deleted_at = NOW()
            WHERE flags_person_lookup.person_version < EXCLUDED.person_version
            "#,
        )
        .bind(&team_ids)
        .bind(&person_uuids)
        .bind(&versions)
        .execute(&self.pool)
        .await?;

        Ok(result.rows_affected())
    }

    /// Assign a distinct_id to a person within a transaction.
    /// Removes it from any previous owner first (handles person merges).
    pub async fn upsert_distinct_id(
        &self,
        assignment: &DistinctIdAssignmentData,
    ) -> Result<(), sqlx::Error> {
        let _timer =
            common_metrics::timing_guard(metric_consts::DB_QUERY_DURATION_MS, &*LABELS_DID_ASSIGN);

        let mut tx = self.pool.begin().await?;

        sqlx::query(
            r#"
            UPDATE flags_person_lookup
            SET distinct_ids = array_remove(distinct_ids, $1)
            WHERE team_id = $2
              AND distinct_ids @> ARRAY[$1]::text[]
              AND person_uuid != $3
            "#,
        )
        .bind(&*assignment.distinct_id)
        .bind(assignment.team_id)
        .bind(assignment.person_uuid)
        .execute(&mut *tx)
        .await?;

        sqlx::query(
            r#"
            INSERT INTO flags_person_lookup (team_id, person_uuid, distinct_ids, distinct_id_version)
            VALUES ($1, $2, ARRAY[$3]::text[], $4)
            ON CONFLICT (team_id, person_uuid) DO UPDATE SET
                distinct_ids = CASE
                    WHEN $3 = ANY(flags_person_lookup.distinct_ids)
                        THEN flags_person_lookup.distinct_ids
                    ELSE flags_person_lookup.distinct_ids || $3
                END,
                distinct_id_version = GREATEST(flags_person_lookup.distinct_id_version, $4)
            WHERE flags_person_lookup.deleted_at IS NULL
              AND (flags_person_lookup.distinct_id_version < $4
                   OR NOT ($3 = ANY(flags_person_lookup.distinct_ids)))
            "#,
        )
        .bind(assignment.team_id)
        .bind(assignment.person_uuid)
        .bind(&*assignment.distinct_id)
        .bind(assignment.version)
        .execute(&mut *tx)
        .await?;

        tx.commit().await?;
        Ok(())
    }

    /// Remove a distinct_id from its owner's array.
    pub async fn delete_distinct_id(
        &self,
        deletion: &DistinctIdDeletionData,
    ) -> Result<(), sqlx::Error> {
        let _timer =
            common_metrics::timing_guard(metric_consts::DB_QUERY_DURATION_MS, &*LABELS_DID_DELETE);

        sqlx::query(
            r#"
            UPDATE flags_person_lookup
            SET distinct_ids = array_remove(distinct_ids, $1),
                distinct_id_version = GREATEST(distinct_id_version, $3)
            WHERE team_id = $2
              AND person_uuid = $4
              AND $1 = ANY(distinct_ids)
            "#,
        )
        .bind(&*deletion.distinct_id)
        .bind(deletion.team_id)
        .bind(deletion.version)
        .bind(deletion.person_uuid)
        .execute(&self.pool)
        .await?;

        Ok(())
    }

    /// Write a heartbeat record for lag monitoring.
    pub async fn write_heartbeat(
        &self,
        source: &str,
        partition: i32,
        offset: i64,
        event_ts: Option<DateTime<Utc>>,
    ) -> Result<(), sqlx::Error> {
        let _timer =
            common_metrics::timing_guard(metric_consts::DB_QUERY_DURATION_MS, &*LABELS_HEARTBEAT);

        sqlx::query(
            r#"
            INSERT INTO flags_read_store_heartbeat (source, partition, last_offset, last_event_ts, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (source, partition) DO UPDATE SET
                last_offset = GREATEST(flags_read_store_heartbeat.last_offset, EXCLUDED.last_offset),
                last_event_ts = EXCLUDED.last_event_ts,
                updated_at = NOW()
            "#,
        )
        .bind(source)
        .bind(partition)
        .bind(offset)
        .bind(event_ts)
        .execute(&self.pool)
        .await?;

        metrics::counter!(metric_consts::HEARTBEAT_WRITES).increment(1);
        Ok(())
    }
}
