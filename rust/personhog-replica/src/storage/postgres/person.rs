use std::collections::HashMap;

use async_trait::async_trait;
use futures::stream::{self, StreamExt, TryStreamExt};
use sqlx::postgres::PgPool;
use uuid::Uuid;

use personhog_common::grpc::current_client_name;

use super::{PostgresStorage, DB_BULK_CHUNKS, DB_QUERY_DURATION, DB_ROWS_RETURNED};
use crate::storage::error::StorageResult;
use crate::storage::traits::PersonLookup;
use crate::storage::types::Person;

const POOL_LABEL: &str = "replica";
const BULK_POOL_LABEL: &str = "bulk_replica";

#[async_trait]
impl PersonLookup for PostgresStorage {
    async fn get_person_by_id(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> StorageResult<Option<Person>> {
        let client = current_client_name();
        let labels = [
            ("operation".to_string(), "get_person_by_id".to_string()),
            ("pool".to_string(), POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let row = sqlx::query_as!(
            Person,
            r#"
            SELECT id, uuid, team_id::bigint as "team_id!", properties::text as "properties!",
                   properties_last_updated_at::text as "properties_last_updated_at?",
                   properties_last_operation::text as "properties_last_operation?",
                   created_at, version, is_identified,
                   CASE WHEN is_user_id IS NULL THEN NULL ELSE (is_user_id != 0) END as is_user_id,
                   last_seen_at
            FROM posthog_person
            WHERE team_id = $1 AND id = $2
            "#,
            team_id as i32,
            person_id
        )
        .fetch_optional(&mut *conn)
        .await?;

        Ok(row)
    }

    async fn get_person_by_uuid(&self, team_id: i64, uuid: Uuid) -> StorageResult<Option<Person>> {
        let client = current_client_name();
        let labels = [
            ("operation".to_string(), "get_person_by_uuid".to_string()),
            ("pool".to_string(), POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let row = sqlx::query_as!(
            Person,
            r#"
            SELECT id, uuid, team_id::bigint as "team_id!", properties::text as "properties!",
                   properties_last_updated_at::text as "properties_last_updated_at?",
                   properties_last_operation::text as "properties_last_operation?",
                   created_at, version, is_identified,
                   CASE WHEN is_user_id IS NULL THEN NULL ELSE (is_user_id != 0) END as is_user_id,
                   last_seen_at
            FROM posthog_person
            WHERE team_id = $1 AND uuid = $2
            "#,
            team_id as i32,
            uuid
        )
        .fetch_optional(&mut *conn)
        .await?;

        Ok(row)
    }

    async fn get_persons_by_ids(
        &self,
        team_id: i64,
        person_ids: &[i64],
    ) -> StorageResult<Vec<Person>> {
        if person_ids.is_empty() {
            return Ok(Vec::new());
        }

        let client = current_client_name();
        let labels = [
            ("operation".to_string(), "get_persons_by_ids".to_string()),
            ("pool".to_string(), BULK_POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn =
            PostgresStorage::acquire_timed(&self.bulk_replica_pool, BULK_POOL_LABEL).await?;

        let rows = sqlx::query_as!(
            Person,
            r#"
            SELECT id, uuid, team_id::bigint as "team_id!", properties::text as "properties!",
                   properties_last_updated_at::text as "properties_last_updated_at?",
                   properties_last_operation::text as "properties_last_operation?",
                   created_at, version, is_identified,
                   CASE WHEN is_user_id IS NULL THEN NULL ELSE (is_user_id != 0) END as is_user_id,
                   last_seen_at
            FROM posthog_person
            WHERE team_id = $1 AND id = ANY($2)
            "#,
            team_id as i32,
            person_ids
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                ("operation".to_string(), "get_persons_by_ids".to_string()),
                ("client".to_string(), client.to_string()),
            ],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_persons_by_uuids(
        &self,
        team_id: i64,
        uuids: &[Uuid],
    ) -> StorageResult<Vec<Person>> {
        if uuids.is_empty() {
            return Ok(Vec::new());
        }

        let client = current_client_name();
        let labels = [
            ("operation".to_string(), "get_persons_by_uuids".to_string()),
            ("pool".to_string(), BULK_POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn =
            PostgresStorage::acquire_timed(&self.bulk_replica_pool, BULK_POOL_LABEL).await?;

        let rows = sqlx::query_as!(
            Person,
            r#"
            SELECT id, uuid, team_id::bigint as "team_id!", properties::text as "properties!",
                   properties_last_updated_at::text as "properties_last_updated_at?",
                   properties_last_operation::text as "properties_last_operation?",
                   created_at, version, is_identified,
                   CASE WHEN is_user_id IS NULL THEN NULL ELSE (is_user_id != 0) END as is_user_id,
                   last_seen_at
            FROM posthog_person
            WHERE team_id = $1 AND uuid = ANY($2)
            "#,
            team_id as i32,
            uuids
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                ("operation".to_string(), "get_persons_by_uuids".to_string()),
                ("client".to_string(), client.to_string()),
            ],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_person_by_distinct_id(
        &self,
        team_id: i64,
        distinct_id: &str,
    ) -> StorageResult<Option<Person>> {
        let client = current_client_name();
        let labels = [
            (
                "operation".to_string(),
                "get_person_by_distinct_id".to_string(),
            ),
            ("pool".to_string(), POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let row = sqlx::query_as!(
            Person,
            r#"
            SELECT p.id, p.uuid, p.team_id::bigint as "team_id!", p.properties::text as "properties!",
                   p.properties_last_updated_at::text as "properties_last_updated_at?",
                   p.properties_last_operation::text as "properties_last_operation?",
                   p.created_at, p.version, p.is_identified,
                   CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END as is_user_id,
                   p.last_seen_at
            FROM posthog_person p
            INNER JOIN posthog_persondistinctid d ON p.id = d.person_id AND p.team_id = d.team_id
            WHERE p.team_id = $1 AND d.distinct_id = $2
            LIMIT 1
            "#,
            team_id as i32,
            distinct_id
        )
        .fetch_optional(&mut *conn)
        .await?;

        Ok(row)
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<(String, Option<Person>)>> {
        if distinct_ids.is_empty() {
            return Ok(Vec::new());
        }

        let client = current_client_name();
        let labels = [
            (
                "operation".to_string(),
                "get_persons_by_distinct_ids_in_team".to_string(),
            ),
            ("pool".to_string(), BULK_POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn =
            PostgresStorage::acquire_timed(&self.bulk_replica_pool, BULK_POOL_LABEL).await?;
        let rows = sqlx::query!(
            r#"
            SELECT p.id, p.uuid as "uuid!", p.team_id::bigint as "team_id!",
                   p.properties::text as "properties!",
                   p.properties_last_updated_at::text as "properties_last_updated_at?",
                   p.properties_last_operation::text as "properties_last_operation?",
                   p.created_at as "created_at!", p.version, p.is_identified as "is_identified!",
                   CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END as is_user_id,
                   p.last_seen_at,
                   d.distinct_id as "distinct_id!"
            FROM posthog_person p
            INNER JOIN posthog_persondistinctid d ON p.id = d.person_id AND p.team_id = d.team_id
            WHERE p.team_id = $1 AND d.distinct_id = ANY($2)
            "#,
            team_id as i32,
            distinct_ids
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "get_persons_by_distinct_ids_in_team".to_string(),
                ),
                ("client".to_string(), client.to_string()),
            ],
            rows.len() as f64,
        );

        let mut found: HashMap<String, Person> = rows
            .into_iter()
            .map(|row| {
                let person = Person {
                    id: row.id,
                    uuid: row.uuid,
                    team_id: row.team_id,
                    properties: row.properties,
                    properties_last_updated_at: row.properties_last_updated_at,
                    properties_last_operation: row.properties_last_operation,
                    created_at: row.created_at,
                    version: row.version,
                    is_identified: row.is_identified,
                    is_user_id: row.is_user_id,
                    last_seen_at: row.last_seen_at,
                };
                (row.distinct_id, person)
            })
            .collect();

        Ok(distinct_ids
            .iter()
            .map(|did| (did.clone(), found.remove(did)))
            .collect())
    }

    async fn delete_persons(&self, team_id: i64, uuids: &[Uuid]) -> StorageResult<i64> {
        if uuids.is_empty() {
            return Ok(0);
        }

        let client = current_client_name();
        let labels = [
            ("operation".to_string(), "delete_persons".to_string()),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        // Resolve UUIDs to integer IDs in one query, then chunk and delete
        // by ID. This avoids scanning the UUID index per-chunk.
        let person_ids: Vec<i64> = sqlx::query_scalar!(
            r#"
            SELECT id::bigint as "id!" FROM posthog_person
            WHERE team_id = $1 AND uuid = ANY($2)
            "#,
            team_id as i32,
            uuids
        )
        .fetch_all(&self.bulk_primary_pool)
        .await?;

        if person_ids.is_empty() {
            return Ok(0);
        }

        // Split into fixed-size chunks and delete concurrently. On the first
        // error, stop starting new chunks and return the error. Chunks that
        // already committed are durable; the caller retries the full UUID
        // list and already-deleted UUIDs are idempotent no-ops.
        let pool = self.bulk_primary_pool.clone();
        let chunks: Vec<Vec<i64>> = person_ids
            .chunks(self.bulk_chunk_size)
            .map(|c| c.to_vec())
            .collect();
        common_metrics::histogram(
            DB_BULK_CHUNKS,
            &[("operation".to_string(), "delete_persons".to_string())],
            chunks.len() as f64,
        );
        let results: Vec<i64> = stream::iter(chunks.into_iter().map(|chunk| {
            let pool = pool.clone();
            let client = client.clone();
            async move { delete_persons_by_ids_chunk(&pool, team_id, &chunk, &client).await }
        }))
        .buffer_unordered(self.bulk_max_concurrent_chunks)
        .try_collect()
        .await?;

        Ok(results.iter().sum())
    }

    async fn delete_persons_batch_for_team(
        &self,
        team_id: i64,
        batch_size: i64,
    ) -> StorageResult<i64> {
        if batch_size <= 0 {
            return Ok(0);
        }

        let client = current_client_name();
        let labels = [
            (
                "operation".to_string(),
                "delete_persons_batch_for_team".to_string(),
            ),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        // Select up to batch_size person IDs.
        let person_ids: Vec<i64> = sqlx::query_scalar!(
            r#"
            SELECT id::bigint as "id!" FROM posthog_person
            WHERE team_id = $1
            LIMIT $2
            "#,
            team_id as i32,
            batch_size
        )
        .fetch_all(&self.bulk_primary_pool)
        .await?;

        if person_ids.is_empty() {
            return Ok(0);
        }

        // Split into fixed-size chunks and delete concurrently.
        let pool = self.bulk_primary_pool.clone();
        let chunks: Vec<Vec<i64>> = person_ids
            .chunks(self.bulk_chunk_size)
            .map(|c| c.to_vec())
            .collect();
        common_metrics::histogram(
            DB_BULK_CHUNKS,
            &[(
                "operation".to_string(),
                "delete_persons_batch_for_team".to_string(),
            )],
            chunks.len() as f64,
        );
        let results: Vec<i64> = stream::iter(chunks.into_iter().map(|chunk| {
            let pool = pool.clone();
            let client = client.clone();
            async move { delete_persons_by_ids_chunk(&pool, team_id, &chunk, &client).await }
        }))
        .buffer_unordered(self.bulk_max_concurrent_chunks)
        .try_collect()
        .await?;

        Ok(results.iter().sum())
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
    ) -> StorageResult<Vec<((i64, String), Option<Person>)>> {
        if team_distinct_ids.is_empty() {
            return Ok(Vec::new());
        }

        let client = current_client_name();
        let labels = [
            (
                "operation".to_string(),
                "get_persons_by_distinct_ids_cross_team".to_string(),
            ),
            ("pool".to_string(), BULK_POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn =
            PostgresStorage::acquire_timed(&self.bulk_replica_pool, BULK_POOL_LABEL).await?;

        let team_ids: Vec<i32> = team_distinct_ids.iter().map(|(t, _)| *t as i32).collect();
        let distinct_ids: Vec<String> = team_distinct_ids.iter().map(|(_, d)| d.clone()).collect();

        // Use query!() since we need distinct_id alongside Person fields
        let rows = sqlx::query!(
            r#"
            SELECT p.id, p.uuid as "uuid!", p.team_id::bigint as "team_id!",
                   p.properties::text as "properties!",
                   p.properties_last_updated_at::text as "properties_last_updated_at?",
                   p.properties_last_operation::text as "properties_last_operation?",
                   p.created_at as "created_at!", p.version, p.is_identified as "is_identified!",
                   CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END as is_user_id,
                   p.last_seen_at,
                   d.distinct_id as "distinct_id!"
            FROM posthog_person p
            INNER JOIN posthog_persondistinctid d ON d.person_id = p.id AND d.team_id = p.team_id
            INNER JOIN UNNEST($1::integer[], $2::text[]) AS batch(team_id, distinct_id)
                ON d.team_id = batch.team_id AND d.distinct_id = batch.distinct_id
            "#,
            &team_ids,
            &distinct_ids
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "get_persons_by_distinct_ids_cross_team".to_string(),
                ),
                ("client".to_string(), client.to_string()),
            ],
            rows.len() as f64,
        );

        let mut found: HashMap<(i64, String), Person> = rows
            .into_iter()
            .map(|row| {
                let key = (row.team_id, row.distinct_id.clone());
                let person = Person {
                    id: row.id,
                    uuid: row.uuid,
                    team_id: row.team_id,
                    properties: row.properties,
                    properties_last_updated_at: row.properties_last_updated_at,
                    properties_last_operation: row.properties_last_operation,
                    created_at: row.created_at,
                    version: row.version,
                    is_identified: row.is_identified,
                    is_user_id: row.is_user_id,
                    last_seen_at: row.last_seen_at,
                };
                (key, person)
            })
            .collect();

        Ok(team_distinct_ids
            .iter()
            .map(|(team_id, did)| {
                let key = (*team_id, did.clone());
                (key.clone(), found.remove(&key))
            })
            .collect())
    }
}

/// Delete a chunk of persons by integer ID in a single transaction:
/// distinct_ids first (FK is NO ACTION), then persons (feature flag hash
/// key overrides cascade at the DB level).
async fn delete_persons_by_ids_chunk(
    pool: &PgPool,
    team_id: i64,
    person_ids: &[i64],
    client: &str,
) -> StorageResult<i64> {
    if person_ids.is_empty() {
        return Ok(0);
    }

    let chunk_labels = [
        (
            "operation".to_string(),
            "delete_persons_batch_for_team_chunk".to_string(),
        ),
        ("pool".to_string(), "bulk_primary".to_string()),
        ("client".to_string(), client.to_string()),
    ];
    let _chunk_timer = common_metrics::timing_guard(DB_QUERY_DURATION, &chunk_labels);

    let mut tx = pool.begin().await?;

    // Delete distinct_id rows first — FK is NO ACTION.
    let did_result = sqlx::query!(
        r#"
        DELETE FROM posthog_persondistinctid
        WHERE team_id = $1 AND person_id = ANY($2)
        "#,
        team_id as i32,
        person_ids
    )
    .execute(&mut *tx)
    .await?;

    common_metrics::histogram(
        DB_ROWS_RETURNED,
        &[
            (
                "operation".to_string(),
                "delete_distinct_ids_batch_for_team".to_string(),
            ),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
        ],
        did_result.rows_affected() as f64,
    );

    // Delete person rows (hash key overrides cascade at DB level).
    let result = sqlx::query!(
        r#"
        DELETE FROM posthog_person
        WHERE team_id = $1 AND id = ANY($2)
        "#,
        team_id as i32,
        person_ids
    )
    .execute(&mut *tx)
    .await?;

    common_metrics::histogram(
        DB_ROWS_RETURNED,
        &[
            (
                "operation".to_string(),
                "delete_persons_batch_for_team".to_string(),
            ),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
        ],
        result.rows_affected() as f64,
    );

    tx.commit().await?;

    Ok(result.rows_affected() as i64)
}
