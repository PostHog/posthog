use std::collections::HashSet;

use async_trait::async_trait;

use personhog_common::grpc::current_client_name;

use super::{ConsistencyLevel, PostgresStorage, DB_QUERY_DURATION, DB_ROWS_RETURNED};
use crate::storage::error::StorageResult;
use crate::storage::traits::CohortStorage;
use crate::storage::types::CohortMembership;

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
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "check_cohort_membership".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let cohort_ids_i32: Vec<i32> = cohort_ids.iter().map(|&id| id as i32).collect();

        let member_ids: Vec<i32> = sqlx::query_scalar!(
            r#"
            SELECT cohort_id
            FROM posthog_cohortpeople
            WHERE person_id = $1 AND cohort_id = ANY($2)
            "#,
            person_id,
            &cohort_ids_i32
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
            ],
            member_ids.len() as f64,
        );

        let member_set: HashSet<i64> = member_ids.into_iter().map(|id| id as i64).collect();

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
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            ("operation".to_string(), "count_cohort_members".to_string()),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let cohort_ids_i32: Vec<i32> = cohort_ids.iter().map(|&id| id as i32).collect();

        let count: i64 = sqlx::query_scalar!(
            r#"
            SELECT COUNT(*) as "count!"
            FROM posthog_cohortpeople
            WHERE cohort_id = ANY($1)
            "#,
            &cohort_ids_i32
        )
        .fetch_one(&mut *conn)
        .await?;

        Ok(count)
    }

    async fn delete_cohort_member(&self, cohort_id: i64, person_id: i64) -> StorageResult<bool> {
        let client = current_client_name();
        let labels = [
            ("operation".to_string(), "delete_cohort_member".to_string()),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        let result = sqlx::query!(
            r#"
            DELETE FROM posthog_cohortpeople
            WHERE cohort_id = $1 AND person_id = $2
            "#,
            cohort_id as i32,
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
        let labels = [
            (
                "operation".to_string(),
                "delete_cohort_members_bulk".to_string(),
            ),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        let cohort_ids_i32: Vec<i32> = cohort_ids.iter().map(|&id| id as i32).collect();

        let result = sqlx::query!(
            r#"
            DELETE FROM posthog_cohortpeople
            WHERE id IN (
                SELECT id FROM posthog_cohortpeople
                WHERE cohort_id = ANY($1)
                LIMIT $2
            )
            "#,
            &cohort_ids_i32,
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
        let labels = [
            ("operation".to_string(), "insert_cohort_members".to_string()),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        let result = sqlx::query!(
            r#"
            INSERT INTO posthog_cohortpeople (person_id, cohort_id, version)
            SELECT pid, $1, $3
            FROM UNNEST($2::bigint[]) AS t(pid)
            ON CONFLICT DO NOTHING
            "#,
            cohort_id as i32,
            person_ids,
            version,
        )
        .execute(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                ("operation".to_string(), "insert_cohort_members".to_string()),
                ("client".to_string(), client.to_string()),
            ],
            result.rows_affected() as f64,
        );

        Ok(result.rows_affected() as i64)
    }

    async fn list_cohort_member_ids(
        &self,
        cohort_id: i64,
        cursor: i64,
        limit: i32,
        consistency: ConsistencyLevel,
    ) -> StorageResult<(Vec<i64>, Option<i64>)> {
        let client = current_client_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "list_cohort_member_ids".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let fetch_limit = (limit as i64) + 1;

        let rows: Vec<i64> = sqlx::query_scalar!(
            r#"
            SELECT person_id
            FROM posthog_cohortpeople
            WHERE cohort_id = $1 AND person_id > $2
            ORDER BY person_id ASC
            LIMIT $3
            "#,
            cohort_id as i32,
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
