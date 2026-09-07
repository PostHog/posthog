use std::collections::HashSet;

use async_trait::async_trait;
use sqlx::Acquire;

use personhog_common::grpc::{current_client_name, current_method_name};

use super::{
    ConsistencyLevel, PostgresStorage, DB_BULK_CHUNKS, DB_QUERY_DURATION, DB_ROWS_RETURNED,
};
use crate::storage::error::StorageResult;
use crate::storage::traits::CohortStorage;
use crate::storage::types::CohortMembership;

/// Insert one chunk on a connection whose transaction already holds the cohort's advisory lock.
async fn insert_cohort_members_chunk(
    conn: &mut sqlx::PgConnection,
    cohort_id: i64,
    person_ids: &[i64],
    version: Option<i32>,
) -> StorageResult<i64> {
    let result = sqlx::query!(
        r#"
        INSERT INTO posthog_cohortpeople (person_id, cohort_id, version)
        SELECT DISTINCT pid, $1::bigint, $3::integer
        FROM UNNEST($2::bigint[]) AS t(pid)
        WHERE NOT EXISTS (
            SELECT 1 FROM posthog_cohortpeople cp
            WHERE cp.person_id = pid AND cp.cohort_id = $1::bigint
        )
        ON CONFLICT DO NOTHING
        "#,
        cohort_id,
        person_ids,
        version,
    )
    .execute(&mut *conn)
    .await?;
    Ok(result.rows_affected() as i64)
}

#[async_trait]
impl CohortStorage for PostgresStorage {
    async fn check_cohort_membership(
        &self,
        person_id: i64,
        cohort_ids: &[i64],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<CohortMembership>> {
        if cohort_ids.is_empty() {
            return Ok(Vec::new());
        }

        let client = current_client_name();
        let method = current_method_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "check_cohort_membership".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        // cohort_id::bigint + the bigint[] bind keep this region-agnostic: prod-us widened
        // cohort_id to bigint (out-of-band), while prod-eu and the tracked schema have it as
        // integer. sqlx decodes i64 from the cast either way, so one binary works on both.
        let member_ids: Vec<i64> = sqlx::query_scalar!(
            r#"
            SELECT cohort_id::bigint AS "cohort_id!"
            FROM posthog_cohortpeople
            WHERE person_id = $1 AND cohort_id = ANY($2::bigint[])
            "#,
            person_id,
            cohort_ids
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "check_cohort_membership".to_string(),
                ),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), method.to_string()),
            ],
            member_ids.len() as f64,
        );

        let member_set: HashSet<i64> = member_ids.into_iter().collect();

        Ok(cohort_ids
            .iter()
            .map(|&cohort_id| CohortMembership {
                cohort_id,
                is_member: member_set.contains(&cohort_id),
            })
            .collect())
    }

    async fn count_cohort_members(
        &self,
        cohort_ids: &[i64],
        consistency: ConsistencyLevel,
    ) -> StorageResult<i64> {
        if cohort_ids.is_empty() {
            return Ok(0);
        }

        let client = current_client_name();
        let method = current_method_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            ("operation".to_string(), "count_cohort_members".to_string()),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let count: i64 = sqlx::query_scalar!(
            r#"
            SELECT COUNT(*) as "count!"
            FROM posthog_cohortpeople
            WHERE cohort_id = ANY($1::bigint[])
            "#,
            cohort_ids
        )
        .fetch_one(&mut *conn)
        .await?;

        Ok(count)
    }

    async fn delete_cohort_member(&self, cohort_id: i64, person_id: i64) -> StorageResult<bool> {
        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            ("operation".to_string(), "delete_cohort_member".to_string()),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        let result = sqlx::query!(
            r#"
            DELETE FROM posthog_cohortpeople
            WHERE cohort_id = $1::bigint AND person_id = $2
            "#,
            cohort_id,
            person_id,
        )
        .execute(&mut *conn)
        .await?;

        Ok(result.rows_affected() > 0)
    }

    async fn delete_cohort_members_bulk(
        &self,
        cohort_ids: &[i64],
        batch_size: i32,
    ) -> StorageResult<i64> {
        if cohort_ids.is_empty() {
            return Ok(0);
        }

        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            (
                "operation".to_string(),
                "delete_cohort_members_bulk".to_string(),
            ),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn =
            PostgresStorage::acquire_timed(&self.bulk_primary_pool, "bulk_primary").await?;

        let result = sqlx::query!(
            r#"
            DELETE FROM posthog_cohortpeople
            WHERE id IN (
                SELECT id FROM posthog_cohortpeople
                WHERE cohort_id = ANY($1::bigint[])
                LIMIT $2
            )
            "#,
            cohort_ids,
            batch_size as i64,
        )
        .execute(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "delete_cohort_members_bulk".to_string(),
                ),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), method.to_string()),
            ],
            result.rows_affected() as f64,
        );

        Ok(result.rows_affected() as i64)
    }

    async fn insert_cohort_members(
        &self,
        cohort_id: i64,
        person_ids: &[i64],
        version: Option<i32>,
    ) -> StorageResult<i64> {
        if person_ids.is_empty() {
            return Ok(0);
        }

        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            ("operation".to_string(), "insert_cohort_members".to_string()),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let chunks: Vec<&[i64]> = person_ids.chunks(self.bulk_chunk_size).collect();
        common_metrics::histogram(
            DB_BULK_CHUNKS,
            &[("operation".to_string(), "insert_cohort_members".to_string())],
            chunks.len() as f64,
        );

        // The membership pair has no unique constraint, so the existence check runs under a
        // per-cohort advisory lock: an overlapping insert for the same cohort waits, then sees
        // the committed rows and skips them. Chunks of one call would only queue on that lock,
        // so they share one connection and one transaction instead of each holding a bulk
        // connection while they wait.
        let mut conn =
            PostgresStorage::acquire_timed(&self.bulk_primary_pool, "bulk_primary").await?;
        let mut tx = conn.begin().await?;
        // A separate statement, so the insert takes its snapshot after the lock is granted.
        sqlx::query("SELECT pg_advisory_xact_lock($1)")
            .bind(cohort_id)
            .execute(&mut *tx)
            .await?;
        let mut inserted: i64 = 0;
        for chunk in chunks {
            inserted += insert_cohort_members_chunk(&mut tx, cohort_id, chunk, version).await?;
        }
        tx.commit().await?;
        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                ("operation".to_string(), "insert_cohort_members".to_string()),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), method.to_string()),
            ],
            inserted as f64,
        );

        Ok(inserted)
    }

    async fn list_cohort_member_ids(
        &self,
        cohort_id: i64,
        cursor: i64,
        limit: i32,
        consistency: ConsistencyLevel,
    ) -> StorageResult<(Vec<i64>, Option<i64>)> {
        let client = current_client_name();
        let method = current_method_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "list_cohort_member_ids".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let fetch_limit = (limit as i64) + 1;

        let rows: Vec<i64> = sqlx::query_scalar!(
            r#"
            SELECT person_id
            FROM posthog_cohortpeople
            WHERE cohort_id = $1::bigint AND person_id > $2
            ORDER BY person_id ASC
            LIMIT $3
            "#,
            cohort_id,
            cursor,
            fetch_limit,
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "list_cohort_member_ids".to_string(),
                ),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), method.to_string()),
            ],
            rows.len() as f64,
        );

        if rows.len() as i64 > limit as i64 {
            let person_ids = rows[..limit as usize].to_vec();
            let next_cursor = Some(*person_ids.last().unwrap());
            Ok((person_ids, next_cursor))
        } else {
            Ok((rows, None))
        }
    }
}
