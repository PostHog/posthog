use chrono::{DateTime, Utc};
use sqlx::postgres::PgPool;
use uuid::Uuid;

use crate::metric_consts;

/// Data needed for a person property upsert.
pub struct PersonUpdateData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub properties: serde_json::Value,
    pub version: i64,
}

/// Data needed for a person deletion.
pub struct PersonDeletionData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub version: i64,
}

/// Data needed for a distinct-ID assignment (add to new owner, remove from old).
pub struct DistinctIdAssignmentData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub distinct_id: Box<str>,
    pub version: i64,
}

/// Data needed for a distinct-ID deletion (remove from owner).
pub struct DistinctIdDeletionData {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub distinct_id: Box<str>,
    pub version: i64,
}

/// Storage handle for the dedicated `flags_read_store` PostgreSQL database.
pub struct PostgresStorage {
    pub pool: PgPool,
}

impl PostgresStorage {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Connectivity check used at startup to fail fast if the dedicated store
    /// is unreachable or misconfigured.
    pub async fn ping(&self) -> Result<(), sqlx::Error> {
        sqlx::query_scalar::<_, i32>("SELECT 1")
            .fetch_one(&self.pool)
            .await
            .map(|_| ())
    }

    // ── Person property upserts (batch via UNNEST) ────────────────────────

    /// Batch-upsert person properties using UNNEST for efficiency.
    ///
    /// The version guard (`WHERE person_version < EXCLUDED.person_version`)
    /// ensures idempotent, order-independent writes: only newer versions win.
    pub async fn batch_upsert_persons(
        &self,
        updates: &[PersonUpdateData],
    ) -> Result<u64, sqlx::Error> {
        if updates.is_empty() {
            return Ok(0);
        }

        let labels = [("operation".to_string(), "person_upsert".to_string())];
        let _timer = common_metrics::timing_guard(metric_consts::DB_QUERY_DURATION_MS, &labels);

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
                person_version = EXCLUDED.person_version
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

    // ── Person deletions (batch via UNNEST) ───────────────────────────────

    /// Batch-delete persons whose stored version is older than the incoming
    /// deletion version (which includes the +100 bump from the producer).
    pub async fn batch_delete_persons(
        &self,
        deletions: &[PersonDeletionData],
    ) -> Result<u64, sqlx::Error> {
        if deletions.is_empty() {
            return Ok(0);
        }

        let labels = [("operation".to_string(), "person_delete".to_string())];
        let _timer = common_metrics::timing_guard(metric_consts::DB_QUERY_DURATION_MS, &labels);

        let team_ids: Vec<i32> = deletions.iter().map(|d| d.team_id).collect();
        let person_uuids: Vec<Uuid> = deletions.iter().map(|d| d.person_uuid).collect();
        let versions: Vec<i64> = deletions.iter().map(|d| d.version).collect();

        let result = sqlx::query(
            r#"
            DELETE FROM flags_person_lookup f
            USING (
                SELECT *
                FROM UNNEST($1::int[], $2::uuid[], $3::bigint[])
                    AS t(team_id, person_uuid, version)
            ) AS incoming
            WHERE f.team_id = incoming.team_id
              AND f.person_uuid = incoming.person_uuid
              AND f.person_version < incoming.version
            "#,
        )
        .bind(&team_ids)
        .bind(&person_uuids)
        .bind(&versions)
        .execute(&self.pool)
        .await?;

        Ok(result.rows_affected())
    }

    // ── Distinct-ID assignment (transactional two-phase) ──────────────────

    /// Assign a distinct_id to a person, atomically removing it from any
    /// previous owner within the same team.
    ///
    /// This handles person merges: when distinct_id X is reassigned from
    /// person A to person B, we must remove X from A's array and add it to
    /// B's array in a single transaction to avoid a window where the
    /// distinct_id is missing from both.
    pub async fn upsert_distinct_id(
        &self,
        assignment: &DistinctIdAssignmentData,
    ) -> Result<(), sqlx::Error> {
        let labels = [("operation".to_string(), "did_assign".to_string())];
        let _timer = common_metrics::timing_guard(metric_consts::DB_QUERY_DURATION_MS, &labels);

        let mut tx = self.pool.begin().await?;

        // Step 1: Remove the distinct_id from any current owner that isn't the
        // target person. This handles merge reassignment.
        sqlx::query(
            r#"
            UPDATE flags_person_lookup
            SET distinct_ids = array_remove(distinct_ids, $1)
            WHERE team_id = $2
              AND $1 = ANY(distinct_ids)
              AND person_uuid != $3
            "#,
        )
        .bind(&*assignment.distinct_id)
        .bind(assignment.team_id)
        .bind(assignment.person_uuid)
        .execute(&mut *tx)
        .await?;

        // Step 2: Add the distinct_id to the target person. Creates the row
        // if it doesn't exist. The version guard prevents stale assignments
        // from overwriting newer state.
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
            WHERE flags_person_lookup.distinct_id_version < $4
               OR NOT ($3 = ANY(flags_person_lookup.distinct_ids))
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

    // ── Distinct-ID deletion ──────────────────────────────────────────────

    /// Remove a distinct_id from its owner's array.
    pub async fn delete_distinct_id(
        &self,
        deletion: &DistinctIdDeletionData,
    ) -> Result<(), sqlx::Error> {
        let labels = [("operation".to_string(), "did_delete".to_string())];
        let _timer = common_metrics::timing_guard(metric_consts::DB_QUERY_DURATION_MS, &labels);

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

    // ── Heartbeat ─────────────────────────────────────────────────────────

    /// Write a heartbeat record for lag monitoring. Uses `GREATEST` on
    /// `last_offset` to ensure monotonic advancement even if heartbeats
    /// arrive out of order.
    pub async fn write_heartbeat(
        &self,
        source: &str,
        partition: i32,
        offset: i64,
        event_ts: Option<DateTime<Utc>>,
    ) -> Result<(), sqlx::Error> {
        let labels = [("operation".to_string(), "heartbeat".to_string())];
        let _timer = common_metrics::timing_guard(metric_consts::DB_QUERY_DURATION_MS, &labels);

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
