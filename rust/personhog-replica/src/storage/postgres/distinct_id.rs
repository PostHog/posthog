use async_trait::async_trait;

use super::{ConsistencyLevel, PostgresStorage, DB_QUERY_DURATION, DB_ROWS_RETURNED};
use crate::storage::error::StorageResult;
use crate::storage::traits::DistinctIdLookup;
use crate::storage::types::{DistinctIdMapping, DistinctIdWithVersion};

#[async_trait]
impl DistinctIdLookup for PostgresStorage {
    async fn get_distinct_ids_for_person(
        &self,
        team_id: i64,
        person_id: i64,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<DistinctIdWithVersion>> {
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_distinct_ids_for_person".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let rows = sqlx::query_as!(
            DistinctIdWithVersion,
            r#"
            SELECT distinct_id, version
            FROM posthog_persondistinctid
            WHERE team_id = $1 AND person_id = $2
            "#,
            team_id as i32,
            person_id
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[(
                "operation".to_string(),
                "get_distinct_ids_for_person".to_string(),
            )],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_distinct_ids_for_persons(
        &self,
        team_id: i64,
        person_ids: &[i64],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<DistinctIdMapping>> {
        if person_ids.is_empty() {
            return Ok(Vec::new());
        }

        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_distinct_ids_for_persons".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let rows = sqlx::query_as!(
            DistinctIdMapping,
            r#"
            SELECT person_id, distinct_id
            FROM posthog_persondistinctid
            WHERE team_id = $1 AND person_id = ANY($2)
            "#,
            team_id as i32,
            person_ids
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[(
                "operation".to_string(),
                "get_distinct_ids_for_persons".to_string(),
            )],
            rows.len() as f64,
        );

        Ok(rows)
    }
}
