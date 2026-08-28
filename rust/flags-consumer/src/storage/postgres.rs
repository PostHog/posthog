use std::sync::LazyLock;

use chrono::{DateTime, Utc};
use sqlx::postgres::PgPool;
use uuid::Uuid;

use crate::metric_consts;
use crate::storage::types::{
    DistinctIdAssignmentData, DistinctIdDeletionData, PersonDeletionData, PersonLookupData,
    PersonUpdateData,
};

static LABELS_PERSON_UPSERT: LazyLock<[(String, String); 1]> =
    LazyLock::new(|| [("operation".to_string(), "person_upsert".to_string())]);
static LABELS_PERSON_DELETE: LazyLock<[(String, String); 1]> =
    LazyLock::new(|| [("operation".to_string(), "person_delete".to_string())]);
static LABELS_DID_ASSIGN: LazyLock<[(String, String); 1]> =
    LazyLock::new(|| [("operation".to_string(), "did_assign".to_string())]);
static LABELS_DID_DELETE: LazyLock<[(String, String); 1]> =
    LazyLock::new(|| [("operation".to_string(), "did_delete".to_string())]);
static LABELS_PERSON_LOOKUP: LazyLock<[(String, String); 1]> =
    LazyLock::new(|| [("operation".to_string(), "person_lookup".to_string())]);
static LABELS_HEARTBEAT: LazyLock<[(String, String); 1]> =
    LazyLock::new(|| [("operation".to_string(), "heartbeat".to_string())]);

pub(crate) const PERSON_UPSERT_SQL: &str = r#"
    INSERT INTO flags_person (team_id, person_uuid, properties, person_version)
        SELECT * FROM UNNEST($1::int[], $2::uuid[], $3::jsonb[], $4::bigint[])
    ON CONFLICT (team_id, person_uuid) DO UPDATE SET
        properties = EXCLUDED.properties,
        person_version = EXCLUDED.person_version,
        deleted_at = NULL
    WHERE flags_person.person_version < EXCLUDED.person_version
"#;

pub(crate) const PERSON_DELETE_SQL: &str = r#"
    INSERT INTO flags_person
        (team_id, person_uuid, properties, person_version, deleted_at)
        SELECT team_id, person_uuid, '{}'::jsonb, version, NOW()
        FROM UNNEST($1::int[], $2::uuid[], $3::bigint[])
            AS t(team_id, person_uuid, version)
    ON CONFLICT (team_id, person_uuid) DO UPDATE SET
        properties = '{}'::jsonb,
        person_version = EXCLUDED.person_version,
        deleted_at = NOW()
    WHERE flags_person.person_version < EXCLUDED.person_version
       OR (
            flags_person.person_version = EXCLUDED.person_version
            AND flags_person.deleted_at IS NULL
       )
"#;

pub(crate) const DISTINCT_ID_UPSERT_SQL: &str = r#"
    INSERT INTO flags_distinct_id_map (team_id, distinct_id, person_uuid, version)
        SELECT * FROM UNNEST($1::int[], $2::text[], $3::uuid[], $4::bigint[])
    ON CONFLICT (team_id, distinct_id) DO UPDATE SET
        person_uuid = EXCLUDED.person_uuid,
        version = EXCLUDED.version,
        deleted_at = NULL
    WHERE flags_distinct_id_map.version < EXCLUDED.version
       OR (
            flags_distinct_id_map.deleted_at IS NOT NULL
            AND flags_distinct_id_map.person_uuid <> EXCLUDED.person_uuid
            -- Deletions carry the producer's owner version plus 100. Compare
            -- cross-owner assignments with that underlying owner version.
            AND flags_distinct_id_map.version::numeric < EXCLUDED.version::numeric + 100
       )
"#;

pub(crate) const DISTINCT_ID_DELETE_SQL: &str = r#"
    INSERT INTO flags_distinct_id_map
        (team_id, distinct_id, person_uuid, version, deleted_at)
        SELECT team_id, distinct_id, person_uuid, version, NOW()
        FROM UNNEST($1::int[], $2::text[], $3::uuid[], $4::bigint[])
            AS t(team_id, distinct_id, person_uuid, version)
    ON CONFLICT (team_id, distinct_id) DO UPDATE SET
        person_uuid = EXCLUDED.person_uuid,
        version = GREATEST(flags_distinct_id_map.version, EXCLUDED.version),
        deleted_at = NOW()
    WHERE flags_distinct_id_map.person_uuid = EXCLUDED.person_uuid
      AND (
            flags_distinct_id_map.version < EXCLUDED.version
            OR (
                flags_distinct_id_map.version = EXCLUDED.version
                AND flags_distinct_id_map.deleted_at IS NULL
            )
      )
"#;

pub(crate) const CANONICAL_READ_SQL: &str = r#"
    SELECT p.person_uuid, p.properties
    FROM flags_distinct_id_map m
    JOIN flags_person p
      ON p.team_id = m.team_id AND p.person_uuid = m.person_uuid
    WHERE m.team_id = $1
      AND m.distinct_id = $2
      AND m.deleted_at IS NULL
      AND p.deleted_at IS NULL
"#;

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
        let properties: Vec<&serde_json::Value> = updates.iter().map(|u| &u.properties).collect();
        let versions: Vec<i64> = updates.iter().map(|u| u.version).collect();

        let result = sqlx::query(PERSON_UPSERT_SQL)
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

        let result = sqlx::query(PERSON_DELETE_SQL)
            .bind(&team_ids)
            .bind(&person_uuids)
            .bind(&versions)
            .execute(&self.pool)
            .await?;

        Ok(result.rows_affected())
    }

    /// Batch-assign distinct IDs via their primary key.
    pub async fn batch_upsert_distinct_ids(
        &self,
        assignments: &[DistinctIdAssignmentData],
    ) -> Result<u64, sqlx::Error> {
        if assignments.is_empty() {
            return Ok(0);
        }

        let _timer =
            common_metrics::timing_guard(metric_consts::DB_QUERY_DURATION_MS, &*LABELS_DID_ASSIGN);

        let team_ids: Vec<i32> = assignments.iter().map(|a| a.team_id).collect();
        let distinct_ids: Vec<&str> = assignments.iter().map(|a| &*a.distinct_id).collect();
        let person_uuids: Vec<Uuid> = assignments.iter().map(|a| a.person_uuid).collect();
        let versions: Vec<i64> = assignments.iter().map(|a| a.version).collect();

        let result = sqlx::query(DISTINCT_ID_UPSERT_SQL)
            .bind(&team_ids)
            .bind(&distinct_ids)
            .bind(&person_uuids)
            .bind(&versions)
            .execute(&self.pool)
            .await?;

        Ok(result.rows_affected())
    }

    /// Tombstone distinct IDs so stale assignments cannot resurrect them.
    /// The incoming version includes a +100 bump from the producer for deletions.
    pub async fn batch_delete_distinct_ids(
        &self,
        deletions: &[DistinctIdDeletionData],
    ) -> Result<u64, sqlx::Error> {
        if deletions.is_empty() {
            return Ok(0);
        }

        let _timer =
            common_metrics::timing_guard(metric_consts::DB_QUERY_DURATION_MS, &*LABELS_DID_DELETE);

        let team_ids: Vec<i32> = deletions.iter().map(|d| d.team_id).collect();
        let distinct_ids: Vec<&str> = deletions.iter().map(|d| &*d.distinct_id).collect();
        let person_uuids: Vec<Uuid> = deletions.iter().map(|d| d.person_uuid).collect();
        let versions: Vec<i64> = deletions.iter().map(|d| d.version).collect();

        let result = sqlx::query(DISTINCT_ID_DELETE_SQL)
            .bind(&team_ids)
            .bind(&distinct_ids)
            .bind(&person_uuids)
            .bind(&versions)
            .execute(&self.pool)
            .await?;

        Ok(result.rows_affected())
    }

    /// Resolve a live distinct ID and person in one round trip.
    pub async fn get_person_by_distinct_id(
        &self,
        team_id: i32,
        distinct_id: &str,
    ) -> Result<Option<PersonLookupData>, sqlx::Error> {
        let _timer = common_metrics::timing_guard(
            metric_consts::DB_QUERY_DURATION_MS,
            &*LABELS_PERSON_LOOKUP,
        );

        let row: Option<(Uuid, serde_json::Value)> = sqlx::query_as(CANONICAL_READ_SQL)
            .bind(team_id)
            .bind(distinct_id)
            .fetch_optional(&self.pool)
            .await?;

        Ok(row.map(|(person_uuid, properties)| PersonLookupData {
            person_uuid,
            properties,
        }))
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
