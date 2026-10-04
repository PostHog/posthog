use async_trait::async_trait;
use futures::stream::{self, StreamExt, TryStreamExt};

use personhog_common::grpc::{current_client_name, current_method_name};

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
        cursor_id: Option<i64>,
    ) -> StorageResult<Vec<DistinctIdWithVersion>> {
        let client = current_client_name();
        let method = current_method_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_distinct_ids_for_person".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        // When only a limit is provided (no cursor), identified (non-anonymous)
        // distinct_ids must survive the LIMIT, so consumers that read the first id
        // get the user-defined one. The regex mirrors ANONYMOUS_REGEX in
        // posthog/utils.py (keep in sync). The identified branch runs first and stops
        // at the limit, so a person with an early identified id does not read all
        // capped rows. The anonymous branch runs only to fill the rest.
        let rows = match (cursor_id, limit) {
            // No composite index on (person_id, id) — cursor branches scan all rows for the
            // person per page instead of seeking. Fine for bulk-delete; add the index if needed.
            (Some(cursor), Some(l)) => {
                sqlx::query_as!(
                    DistinctIdWithVersion,
                    r#"
                    SELECT distinct_id, version, id
                    FROM posthog_persondistinctid
                    WHERE team_id = $1 AND person_id = $2 AND is_deleted = false
                          AND id > $3
                    ORDER BY id ASC
                    LIMIT $4
                    "#,
                    team_id as i32,
                    person_id,
                    cursor,
                    l
                )
                .fetch_all(&mut *conn)
                .await?
            }
            (Some(cursor), None) => {
                sqlx::query_as!(
                    DistinctIdWithVersion,
                    r#"
                    SELECT distinct_id, version, id
                    FROM posthog_persondistinctid
                    WHERE team_id = $1 AND person_id = $2 AND is_deleted = false
                          AND id > $3
                    ORDER BY id ASC
                    "#,
                    team_id as i32,
                    person_id,
                    cursor
                )
                .fetch_all(&mut *conn)
                .await?
            }
            (None, Some(l)) => {
                sqlx::query_as!(
                    DistinctIdWithVersion,
                    r#"
                    SELECT picked.distinct_id AS "distinct_id!", picked.version AS "version?", picked.id AS "id!"
                    FROM (
                        (
                            SELECT capped.distinct_id, capped.version, capped.id, false AS anonymous
                            FROM (
                                SELECT distinct_id, version, id
                                FROM posthog_persondistinctid
                                WHERE team_id = $1 AND person_id = $2 AND is_deleted = false
                                LIMIT 2500
                            ) capped
                            WHERE capped.distinct_id !~ '^([a-z0-9]+-){4}[a-z0-9]+$'
                            LIMIT $3
                        )
                        UNION ALL
                        (
                            SELECT capped.distinct_id, capped.version, capped.id, true AS anonymous
                            FROM (
                                SELECT distinct_id, version, id
                                FROM posthog_persondistinctid
                                WHERE team_id = $1 AND person_id = $2 AND is_deleted = false
                                LIMIT 2500
                            ) capped
                            WHERE capped.distinct_id ~ '^([a-z0-9]+-){4}[a-z0-9]+$'
                            LIMIT $3
                        )
                        LIMIT $3
                    ) picked
                    ORDER BY picked.anonymous, picked.id
                    "#,
                    team_id as i32,
                    person_id,
                    l
                )
                .fetch_all(&mut *conn)
                .await?
            }
            (None, None) => {
                sqlx::query_as!(
                    DistinctIdWithVersion,
                    r#"
                    SELECT distinct_id, version, id
                    FROM posthog_persondistinctid
                    WHERE team_id = $1 AND person_id = $2 AND is_deleted = false
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
                ("method".to_string(), method.to_string()),
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
        let method = current_method_name();
        let pool_label = PostgresStorage::bulk_pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_distinct_ids_for_persons".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
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
                // Same ordering contract as get_distinct_ids_for_person: identified ids
                // survive the per-person LIMIT (regex mirrors ANONYMOUS_REGEX in
                // posthog/utils.py), with the scan capped for pathological persons and
                // each branch stopping at the limit.
                let rows = match limit_per_person {
                    Some(l) => {
                        sqlx::query_as!(
                            DistinctIdMapping,
                            r#"
                                SELECT l.person_id AS "person_id!", l.distinct_id AS "distinct_id!", l.version AS "version?"
                                FROM UNNEST($2::bigint[]) AS pid(id)
                                CROSS JOIN LATERAL (
                                    SELECT picked.person_id, picked.distinct_id, picked.version
                                    FROM (
                                        (
                                            SELECT capped.person_id, capped.distinct_id, capped.version, capped.id, false AS anonymous
                                            FROM (
                                                SELECT person_id, distinct_id, version, id
                                                FROM posthog_persondistinctid
                                                WHERE team_id = $1 AND person_id = pid.id AND is_deleted = false
                                                LIMIT 2500
                                            ) capped
                                            WHERE capped.distinct_id !~ '^([a-z0-9]+-){4}[a-z0-9]+$'
                                            LIMIT $3
                                        )
                                        UNION ALL
                                        (
                                            SELECT capped.person_id, capped.distinct_id, capped.version, capped.id, true AS anonymous
                                            FROM (
                                                SELECT person_id, distinct_id, version, id
                                                FROM posthog_persondistinctid
                                                WHERE team_id = $1 AND person_id = pid.id AND is_deleted = false
                                                LIMIT 2500
                                            ) capped
                                            WHERE capped.distinct_id ~ '^([a-z0-9]+-){4}[a-z0-9]+$'
                                            LIMIT $3
                                        )
                                        LIMIT $3
                                    ) picked
                                    ORDER BY picked.anonymous, picked.id
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
                                WHERE team_id = $1 AND person_id = ANY($2) AND is_deleted = false
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
                ("method".to_string(), method.to_string()),
            ],
            rows.len() as f64,
        );

        Ok(rows)
    }
}
