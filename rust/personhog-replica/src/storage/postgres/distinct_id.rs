use async_trait::async_trait;
use futures::stream::{self, StreamExt, TryStreamExt};

use personhog_common::grpc::current_client_name;

use super::{
    ConsistencyLevel, PostgresStorage, DB_BULK_CHUNKS, DB_QUERY_DURATION, DB_ROWS_RETURNED,
};
use crate::storage::error::{StorageError, StorageResult};
use crate::storage::traits::DistinctIdLookup;
use crate::storage::types::{DistinctIdMapping, DistinctIdWithVersion};

#[async_trait]
impl DistinctIdLookup for PostgresStorage {
    async fn get_distinct_ids_for_person(
        &self,
        team_id: i64,
        person_id: i64,
        consistency: ConsistencyLevel,
        limit: Option<i64>,
    ) -> StorageResult<Vec<DistinctIdWithVersion>> {
        let client = current_client_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_distinct_ids_for_person".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let rows = match limit {
            Some(l) => {
                sqlx::query_as!(
                    DistinctIdWithVersion,
                    r#"
                    SELECT distinct_id, version
                    FROM posthog_persondistinctid
                    WHERE team_id = $1 AND person_id = $2
                    LIMIT $3
                    "#,
                    team_id as i32,
                    person_id,
                    l
                )
                .fetch_all(&mut *conn)
                .await?
            }
            _ => {
                sqlx::query_as!(
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
                .await?
            }
        };

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "get_distinct_ids_for_person".to_string(),
                ),
                ("client".to_string(), client.to_string()),
            ],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_distinct_ids_for_persons(
        &self,
        team_id: i64,
        person_ids: &[i64],
        consistency: ConsistencyLevel,
        limit_per_person: Option<i64>,
    ) -> StorageResult<Vec<DistinctIdMapping>> {
        if person_ids.is_empty() {
            return Ok(Vec::new());
        }

        let client = current_client_name();
        let pool_label = PostgresStorage::bulk_pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_distinct_ids_for_persons".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.bulk_pool_for_consistency(consistency).clone();
        let chunks: Vec<Vec<i64>> = person_ids
            .chunks(self.bulk_chunk_size)
            .map(|c| c.to_vec())
            .collect();
        common_metrics::histogram(
            DB_BULK_CHUNKS,
            &[(
                "operation".to_string(),
                "get_distinct_ids_for_persons".to_string(),
            )],
            chunks.len() as f64,
        );
        let results: Vec<Vec<DistinctIdMapping>> = stream::iter(chunks.into_iter().map(|chunk| {
            let pool = pool.clone();
            async move {
                let mut conn = PostgresStorage::acquire_timed(&pool, pool_label).await?;
                let rows = match limit_per_person {
                    Some(l) => {
                        sqlx::query_as!(
                            DistinctIdMapping,
                            r#"
                                SELECT l.person_id, l.distinct_id, l.version
                                FROM UNNEST($2::bigint[]) AS pid(id)
                                CROSS JOIN LATERAL (
                                    SELECT person_id, distinct_id, version
                                    FROM posthog_persondistinctid
                                    WHERE team_id = $1 AND person_id = pid.id
                                    LIMIT $3
                                ) l
                                "#,
                            team_id as i32,
                            &chunk,
                            l
                        )
                        .fetch_all(&mut *conn)
                        .await?
                    }
                    _ => {
                        sqlx::query_as!(
                            DistinctIdMapping,
                            r#"
                                SELECT person_id, distinct_id, version
                                FROM posthog_persondistinctid
                                WHERE team_id = $1 AND person_id = ANY($2)
                                "#,
                            team_id as i32,
                            &chunk
                        )
                        .fetch_all(&mut *conn)
                        .await?
                    }
                };
                Ok::<_, StorageError>(rows)
            }
        }))
        .buffer_unordered(self.bulk_max_concurrent_chunks)
        .try_collect()
        .await?;

        let rows: Vec<DistinctIdMapping> = results.into_iter().flatten().collect();
        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "get_distinct_ids_for_persons".to_string(),
                ),
                ("client".to_string(), client.to_string()),
            ],
            rows.len() as f64,
        );

        Ok(rows)
    }
}
