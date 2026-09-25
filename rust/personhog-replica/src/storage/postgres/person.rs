use std::collections::{HashMap, HashSet};

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use futures::stream::{self, StreamExt, TryStreamExt};
use sqlx::postgres::PgPool;
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

use personhog_common::grpc::{current_client_name, current_method_name};

use super::{PostgresStorage, DB_BULK_CHUNKS, DB_QUERY_DURATION, DB_ROWS_RETURNED};
use crate::storage::error::{StorageError, StorageResult};
use crate::storage::traits::PersonLookup;
use crate::storage::types::{
    DeletePersonsMode, DeletePersonsOutcome, Person, PersonTombstoneQueueEntry, SplitResult,
    TombstonedDeleteOutcome, TombstonedDistinctId, TombstonedPerson,
};

/// Version offset for split person/PDI rows — mirrors the Django convention.
const SPLIT_VERSION_OFFSET: i64 = 101;

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
        let method = current_method_name();
        let labels = [
            ("operation".to_string(), "get_person_by_id".to_string()),
            ("pool".to_string(), POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let row = sqlx::query_as!(
            Person,
            r#"
            SELECT id, uuid, team_id::bigint as "team_id!", properties::text as "properties?",
                   properties_last_updated_at::text as "properties_last_updated_at?",
                   properties_last_operation::text as "properties_last_operation?",
                   created_at, version, is_identified,
                   CASE WHEN is_user_id IS NULL THEN NULL ELSE (is_user_id != 0) END as is_user_id,
                   last_seen_at
            FROM posthog_person
            WHERE team_id = $1 AND id = $2 AND is_deleted = false
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
        let method = current_method_name();
        let labels = [
            ("operation".to_string(), "get_person_by_uuid".to_string()),
            ("pool".to_string(), POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let row = sqlx::query_as!(
            Person,
            r#"
            SELECT id, uuid, team_id::bigint as "team_id!", properties::text as "properties?",
                   properties_last_updated_at::text as "properties_last_updated_at?",
                   properties_last_operation::text as "properties_last_operation?",
                   created_at, version, is_identified,
                   CASE WHEN is_user_id IS NULL THEN NULL ELSE (is_user_id != 0) END as is_user_id,
                   last_seen_at
            FROM posthog_person
            WHERE team_id = $1 AND uuid = $2 AND is_deleted = false
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
        include_properties: bool,
    ) -> StorageResult<Vec<Person>> {
        if person_ids.is_empty() {
            return Ok(Vec::new());
        }

        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            ("operation".to_string(), "get_persons_by_ids".to_string()),
            ("pool".to_string(), BULK_POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.bulk_replica_pool.clone();
        let chunks: Vec<Vec<i64>> = person_ids
            .chunks(self.bulk_chunk_size)
            .map(|c| c.to_vec())
            .collect();
        common_metrics::histogram(
            DB_BULK_CHUNKS,
            &[("operation".to_string(), "get_persons_by_ids".to_string())],
            chunks.len() as f64,
        );
        let results: Vec<Vec<Person>> = stream::iter(chunks.into_iter().map(|chunk| {
            let pool = pool.clone();
            async move {
                let mut conn =
                    PostgresStorage::acquire_timed(&pool, BULK_POOL_LABEL).await?;
                let rows = sqlx::query_as!(
                    Person,
                    r#"
                    SELECT id, uuid, team_id::bigint as "team_id!",
                           CASE WHEN $3::boolean THEN properties::text ELSE NULL END as "properties?",
                           CASE WHEN $3::boolean THEN properties_last_updated_at::text ELSE NULL END as "properties_last_updated_at?",
                           CASE WHEN $3::boolean THEN properties_last_operation::text ELSE NULL END as "properties_last_operation?",
                           created_at, version, is_identified,
                           CASE WHEN is_user_id IS NULL THEN NULL ELSE (is_user_id != 0) END as is_user_id,
                           last_seen_at
                    FROM posthog_person
                    WHERE team_id = $1 AND id = ANY($2) AND is_deleted = false
                    "#,
                    team_id as i32,
                    &chunk,
                    include_properties
                )
                .fetch_all(&mut *conn)
                .await?;
                Ok::<_, StorageError>(rows)
            }
        }))
        .buffer_unordered(self.bulk_max_concurrent_chunks)
        .try_collect()
        .await?;

        let rows: Vec<Person> = results.into_iter().flatten().collect();
        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                ("operation".to_string(), "get_persons_by_ids".to_string()),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), method.to_string()),
            ],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_persons_by_uuids(
        &self,
        team_id: i64,
        uuids: &[Uuid],
        include_properties: bool,
    ) -> StorageResult<Vec<Person>> {
        if uuids.is_empty() {
            return Ok(Vec::new());
        }

        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            ("operation".to_string(), "get_persons_by_uuids".to_string()),
            ("pool".to_string(), BULK_POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.bulk_replica_pool.clone();
        let chunks: Vec<Vec<Uuid>> = uuids
            .chunks(self.bulk_chunk_size)
            .map(|c| c.to_vec())
            .collect();
        common_metrics::histogram(
            DB_BULK_CHUNKS,
            &[("operation".to_string(), "get_persons_by_uuids".to_string())],
            chunks.len() as f64,
        );
        let results: Vec<Vec<Person>> = stream::iter(chunks.into_iter().map(|chunk| {
            let pool = pool.clone();
            async move {
                let mut conn =
                    PostgresStorage::acquire_timed(&pool, BULK_POOL_LABEL).await?;
                let rows = sqlx::query_as!(
                    Person,
                    r#"
                    SELECT id, uuid, team_id::bigint as "team_id!",
                           CASE WHEN $3::boolean THEN properties::text ELSE NULL END as "properties?",
                           CASE WHEN $3::boolean THEN properties_last_updated_at::text ELSE NULL END as "properties_last_updated_at?",
                           CASE WHEN $3::boolean THEN properties_last_operation::text ELSE NULL END as "properties_last_operation?",
                           created_at, version, is_identified,
                           CASE WHEN is_user_id IS NULL THEN NULL ELSE (is_user_id != 0) END as is_user_id,
                           last_seen_at
                    FROM posthog_person
                    WHERE team_id = $1 AND uuid = ANY($2) AND is_deleted = false
                    "#,
                    team_id as i32,
                    &chunk,
                    include_properties
                )
                .fetch_all(&mut *conn)
                .await?;
                Ok::<_, StorageError>(rows)
            }
        }))
        .buffer_unordered(self.bulk_max_concurrent_chunks)
        .try_collect()
        .await?;

        let rows: Vec<Person> = results.into_iter().flatten().collect();
        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                ("operation".to_string(), "get_persons_by_uuids".to_string()),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), method.to_string()),
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
        let method = current_method_name();
        let labels = [
            (
                "operation".to_string(),
                "get_person_by_distinct_id".to_string(),
            ),
            ("pool".to_string(), POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let row = sqlx::query_as!(
            Person,
            r#"
            SELECT p.id, p.uuid, p.team_id::bigint as "team_id!", p.properties::text as "properties?",
                   p.properties_last_updated_at::text as "properties_last_updated_at?",
                   p.properties_last_operation::text as "properties_last_operation?",
                   p.created_at, p.version, p.is_identified,
                   CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END as is_user_id,
                   p.last_seen_at
            FROM posthog_person p
            INNER JOIN posthog_persondistinctid d ON p.id = d.person_id AND p.team_id = d.team_id
            WHERE p.team_id = $1 AND d.distinct_id = $2
              AND p.is_deleted = false AND d.is_deleted = false
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
        include_properties: bool,
    ) -> StorageResult<Vec<(String, Option<Person>)>> {
        if distinct_ids.is_empty() {
            return Ok(Vec::new());
        }

        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            (
                "operation".to_string(),
                "get_persons_by_distinct_ids_in_team".to_string(),
            ),
            ("pool".to_string(), BULK_POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.bulk_replica_pool.clone();
        // Drive from the supplied distinct IDs via UNNEST and probe the
        // (team_id, distinct_id) index, rather than `d.distinct_id = ANY($2)`
        // with the team predicate parked on `posthog_person`. The latter lets
        // the planner start from every person in the team and hash-join, which
        // is catastrophic for large teams. Deduplicate the input first so
        // UNNEST emits one row per distinct ID; the response below still
        // mirrors the caller's original list, repeats included.
        let mut seen: HashSet<&str> = HashSet::with_capacity(distinct_ids.len());
        let unique_ids: Vec<&str> = distinct_ids
            .iter()
            .map(|d| d.as_str())
            .filter(|&d| seen.insert(d))
            .collect();
        let chunks: Vec<Vec<String>> = unique_ids
            .chunks(self.bulk_chunk_size)
            .map(|c| c.iter().map(|&s| s.to_string()).collect())
            .collect();
        common_metrics::histogram(
            DB_BULK_CHUNKS,
            &[(
                "operation".to_string(),
                "get_persons_by_distinct_ids_in_team".to_string(),
            )],
            chunks.len() as f64,
        );
        let chunk_results: Vec<Vec<(String, Person)>> =
            stream::iter(chunks.into_iter().map(|chunk| {
                let pool = pool.clone();
                async move {
                    let mut conn =
                        PostgresStorage::acquire_timed(&pool, BULK_POOL_LABEL).await?;
                    let rows = sqlx::query!(
                        r#"
                        SELECT p.id, p.uuid as "uuid!", p.team_id::bigint as "team_id!",
                               CASE WHEN $3::boolean THEN p.properties::text ELSE NULL END as "properties?",
                               CASE WHEN $3::boolean THEN p.properties_last_updated_at::text ELSE NULL END as "properties_last_updated_at?",
                               CASE WHEN $3::boolean THEN p.properties_last_operation::text ELSE NULL END as "properties_last_operation?",
                               p.created_at as "created_at!", p.version, p.is_identified as "is_identified!",
                               CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END as is_user_id,
                               p.last_seen_at,
                               d.distinct_id as "distinct_id!"
                        FROM UNNEST($2::text[]) AS batch(distinct_id)
                        INNER JOIN posthog_persondistinctid d
                            ON d.team_id = $1 AND d.distinct_id = batch.distinct_id
                            AND d.is_deleted = false
                        INNER JOIN posthog_person p
                            ON p.id = d.person_id AND p.team_id = d.team_id
                            AND p.is_deleted = false
                        "#,
                        team_id as i32,
                        &chunk,
                        include_properties
                    )
                    .fetch_all(&mut *conn)
                    .await?;
                    Ok::<_, StorageError>(
                        rows.into_iter()
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
                            .collect(),
                    )
                }
            }))
            .buffer_unordered(self.bulk_max_concurrent_chunks)
            .try_collect()
            .await?;

        let mut found: HashMap<String, Person> = chunk_results.into_iter().flatten().collect();

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "get_persons_by_distinct_ids_in_team".to_string(),
                ),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), method.to_string()),
            ],
            found.len() as f64,
        );

        Ok(distinct_ids
            .iter()
            .map(|did| (did.clone(), found.remove(did)))
            .collect())
    }

    async fn delete_persons(
        &self,
        team_id: i64,
        uuids: &[Uuid],
        mode: DeletePersonsMode,
    ) -> StorageResult<DeletePersonsOutcome> {
        if uuids.is_empty() {
            return Ok(DeletePersonsOutcome::default());
        }

        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            ("operation".to_string(), "delete_persons".to_string()),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        if mode == DeletePersonsMode::Tombstone {
            return tombstone_persons_by_uuids(self, team_id, uuids, &client).await;
        }

        // Resolve UUIDs to integer IDs in one query, then chunk and delete
        // by ID. This avoids scanning the UUID index per-chunk.
        let mut person_ids: Vec<i64> = sqlx::query_scalar!(
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
            return Ok(DeletePersonsOutcome::default());
        }
        person_ids.sort_unstable();

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
        let results: Vec<i64> =
            stream::iter(
                chunks.into_iter().map(|chunk| {
                    let pool = pool.clone();
                    let client = client.clone();
                    // Per-person delete: also clear cohort memberships (no DB cascade).
                    async move {
                        delete_persons_by_ids_chunk(&pool, team_id, &chunk, &client, true).await
                    }
                }),
            )
            .buffer_unordered(self.bulk_max_concurrent_chunks)
            .try_collect()
            .await?;

        Ok(DeletePersonsOutcome {
            deleted: results.iter().sum(),
            tombstones: None,
        })
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
        let method = current_method_name();
        let labels = [
            (
                "operation".to_string(),
                "delete_persons_batch_for_team".to_string(),
            ),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        sqlx::query!(
            "DELETE FROM person_tombstone_publish_queue WHERE team_id = $1",
            team_id as i32
        )
        .execute(&self.bulk_primary_pool)
        .await?;

        // Team teardown always removes the rows, tombstoned ones included: nothing
        // sweeps a deleted team's tombstones into the cleanup queue.
        let mut person_ids: Vec<i64> = sqlx::query_scalar!(
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
        person_ids.sort_unstable();

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
        let results: Vec<i64> =
            stream::iter(
                chunks.into_iter().map(|chunk| {
                    let pool = pool.clone();
                    let client = client.clone();
                    // Team teardown clears cohortpeople separately, by cohort, before this runs.
                    async move {
                        delete_persons_by_ids_chunk(&pool, team_id, &chunk, &client, false).await
                    }
                }),
            )
            .buffer_unordered(self.bulk_max_concurrent_chunks)
            .try_collect()
            .await?;

        Ok(results.iter().sum())
    }

    async fn get_person_tombstones(
        &self,
        team_id: i64,
        uuids: &[Uuid],
    ) -> StorageResult<Vec<TombstonedPerson>> {
        if uuids.is_empty() {
            return Ok(Vec::new());
        }
        let labels = [
            ("operation".to_string(), "get_person_tombstones".to_string()),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), current_client_name().to_string()),
            ("method".to_string(), current_method_name().to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;
        let mut tx = sqlx::Connection::begin(&mut *conn).await?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            .execute(&mut *tx)
            .await?;
        let rows = sqlx::query!(
            r#"
            SELECT id::bigint as "id!", uuid as "uuid!",
                   COALESCE(version, 0)::bigint as "version!"
            FROM posthog_person
            WHERE team_id = $1 AND uuid = ANY($2) AND is_deleted = true
            "#,
            team_id as i32,
            uuids
        )
        .fetch_all(&mut *tx)
        .await?;
        let persons = rows
            .into_iter()
            .map(|row| (row.id, row.uuid, row.version))
            .collect();
        let mut tombstones = with_tombstoned_distinct_ids(&mut tx, team_id, persons).await?;
        tx.commit().await?;
        tombstones.sort_by(|a, b| a.uuid.cmp(&b.uuid));
        common_metrics::histogram(DB_ROWS_RETURNED, &labels, tombstones.len() as f64);
        Ok(tombstones)
    }

    async fn ack_person_tombstones(
        &self,
        team_id: i64,
        acked: &[(Uuid, i64)],
    ) -> StorageResult<i64> {
        if acked.is_empty() {
            return Ok(0);
        }
        let labels = [
            ("operation".to_string(), "ack_person_tombstones".to_string()),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), current_client_name().to_string()),
            ("method".to_string(), current_method_name().to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let uuids: Vec<Uuid> = acked.iter().map(|(uuid, _)| *uuid).collect();
        let versions: Vec<i64> = acked.iter().map(|(_, version)| *version).collect();
        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;
        let result = sqlx::query!(
            r#"
            DELETE FROM person_tombstone_publish_queue q
            USING UNNEST($2::uuid[], $3::bigint[]) AS a(person_uuid, person_version)
            WHERE q.team_id = $1
              AND q.person_uuid = a.person_uuid
              AND q.person_version <= a.person_version
            "#,
            team_id as i32,
            &uuids,
            &versions
        )
        .execute(&mut *conn)
        .await?;
        Ok(result.rows_affected() as i64)
    }

    async fn list_person_tombstone_queue(
        &self,
        after: (i64, Uuid),
        team_id: Option<i64>,
        limit: i64,
    ) -> StorageResult<Vec<PersonTombstoneQueueEntry>> {
        let labels = [
            (
                "operation".to_string(),
                "list_person_tombstone_queue".to_string(),
            ),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), current_client_name().to_string()),
            ("method".to_string(), current_method_name().to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;
        let rows = sqlx::query!(
            r#"
            SELECT team_id::bigint as "team_id!", person_uuid as "person_uuid!",
                   person_version as "person_version!",
                   (EXTRACT(EPOCH FROM tombstoned_at) * 1000)::bigint as "tombstoned_at_ms!"
            FROM person_tombstone_publish_queue
            WHERE (team_id, person_uuid) > ($1::int, $2::uuid)
              AND ($3::int IS NULL OR team_id = $3)
            ORDER BY team_id, person_uuid
            LIMIT $4
            "#,
            after.0 as i32,
            after.1,
            team_id.map(|t| t as i32),
            limit
        )
        .fetch_all(&mut *conn)
        .await?;
        common_metrics::histogram(DB_ROWS_RETURNED, &labels, rows.len() as f64);
        Ok(rows
            .into_iter()
            .map(|row| PersonTombstoneQueueEntry {
                team_id: row.team_id,
                person_uuid: row.person_uuid,
                person_version: row.person_version,
                tombstoned_at_ms: row.tombstoned_at_ms,
            })
            .collect())
    }

    async fn delete_tombstoned_persons(
        &self,
        team_id: i64,
        uuids: &[Uuid],
        max_rows: i64,
    ) -> StorageResult<TombstonedDeleteOutcome> {
        if uuids.is_empty() {
            return Ok(TombstonedDeleteOutcome::default());
        }

        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            (
                "operation".to_string(),
                "delete_tombstoned_persons".to_string(),
            ),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        // One outcome per uuid: a duplicate must not be counted or reported twice.
        let mut seen = HashSet::with_capacity(uuids.len());
        let unique: Vec<Uuid> = uuids.iter().copied().filter(|u| seen.insert(*u)).collect();

        // The caller picks the row budget; the server caps it so no call outlives its deadline.
        let budget = max_rows.clamp(1, self.tombstoned_delete_max_rows as i64);

        let mut tx = self.bulk_primary_pool.begin().await?;
        // A held row means a revival or merge in flight: fail fast and let the caller retry. Kept
        // under the router's 5 s backend deadline so the caller sees an error, not a timeout.
        sqlx::query("SET LOCAL lock_timeout = '2s'")
            .execute(&mut *tx)
            .await?;

        // Resolved without locks. The delete re-checks the tombstone under its row lock, so a
        // person revived in between drops out and reads as neither deleted nor live.
        let candidates: Vec<(i64, Uuid)> = sqlx::query!(
            r#"
            SELECT id::bigint AS "id!", uuid AS "uuid!"
            FROM posthog_person
            WHERE team_id = $1 AND uuid = ANY($2) AND is_deleted
            ORDER BY id
            "#,
            team_id as i32,
            unique.as_slice()
        )
        .fetch_all(&mut *tx)
        .await?
        .into_iter()
        .map(|row| (row.id, row.uuid))
        .collect();

        let skipped_live: i64 = sqlx::query_scalar!(
            r#"
            SELECT count(*) AS "count!"
            FROM posthog_person
            WHERE team_id = $1 AND uuid = ANY($2) AND is_deleted = false
            "#,
            team_id as i32,
            unique.as_slice()
        )
        .fetch_one(&mut *tx)
        .await?;

        let mut outcome = TombstonedDeleteOutcome {
            skipped_live,
            ..TombstonedDeleteOutcome::default()
        };
        if candidates.is_empty() {
            tx.commit().await?;
            record_tombstoned_delete_rows(&outcome, &client, &method);
            return Ok(outcome);
        }

        // Each probe reads at most `remaining + 1` index entries per table per person, so its
        // cost is bounded by the budget however many rows a person owns.
        let mut admission = Admission::new(budget, self.bulk_chunk_size);
        for batch in candidates.chunks(PROBE_BATCH_PERSONS) {
            if !admission.wants_more() {
                admission.defer(batch.iter().map(|(_, uuid)| *uuid));
                continue;
            }
            let ids: Vec<i64> = batch.iter().map(|(id, _)| *id).collect();
            let counts =
                probe_dependent_rows(&mut *tx, team_id, &ids, admission.probe_limit()).await?;
            for (id, uuid) in batch {
                admission.offer(*id, *uuid, counts.get(id).copied().unwrap_or_default());
            }
        }
        let Admission {
            remaining,
            admitted,
            trim,
            mut pending,
            ..
        } = admission;

        // Lock only the persons that are still tombstoned, in id order. READ COMMITTED re-checks
        // is_deleted on the row version that wins the lock, so a person revived a moment ago
        // drops out here. Live writers touch live persons, never locked here, and the identity
        // saga locks persons before distinct ids in this same order.
        let mut lock_ids: Vec<i64> = admitted.iter().map(|(id, _)| *id).collect();
        lock_ids.extend(trim.map(|(id, _)| id));
        let locked: HashSet<i64> = sqlx::query_scalar!(
            r#"
            SELECT id::bigint AS "id!"
            FROM posthog_person
            WHERE team_id = $1 AND id = ANY($2) AND is_deleted
            ORDER BY id
            FOR UPDATE
            "#,
            team_id as i32,
            lock_ids.as_slice()
        )
        .fetch_all(&mut *tx)
        .await?
        .into_iter()
        .collect();

        let admitted: Vec<(i64, Uuid)> = admitted
            .into_iter()
            .filter(|(id, _)| locked.contains(id))
            .collect();
        let admitted_ids: Vec<i64> = admitted.iter().map(|(id, _)| *id).collect();

        // Lock the distinct ids too and read their state under the lock. A live mapping means
        // ingestion can still reach the person, so it must stay.
        let mut live_owners: HashSet<i64> = HashSet::new();
        if !admitted_ids.is_empty() {
            live_owners = sqlx::query!(
                r#"
                SELECT person_id AS "person_id!", is_deleted AS "is_deleted!"
                FROM posthog_persondistinctid
                WHERE team_id = $1 AND person_id = ANY($2)
                ORDER BY id
                FOR UPDATE
                "#,
                team_id as i32,
                admitted_ids.as_slice()
            )
            .fetch_all(&mut *tx)
            .await?
            .into_iter()
            .filter(|row| !row.is_deleted)
            .map(|row| row.person_id)
            .collect();
        }

        let (blocked, victims): (Vec<(i64, Uuid)>, Vec<(i64, Uuid)>) = admitted
            .into_iter()
            .partition(|(id, _)| live_owners.contains(id));
        outcome.blocked_uuids = blocked.into_iter().map(|(_, uuid)| uuid).collect();
        let victim_ids: Vec<i64> = victims.iter().map(|(id, _)| *id).collect();

        // The hash key override FK cascades in production but not in every environment built
        // from the sqlx migrations, so remove the overrides here instead of relying on the cascade.
        if !victim_ids.is_empty() {
            let overrides = sqlx::query!(
                "DELETE FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 AND person_id = ANY($2)",
                team_id as i32,
                victim_ids.as_slice()
            )
            .execute(&mut *tx)
            .await?;
            outcome.rows_deleted += overrides.rows_affected() as i64;
        }
        let rows =
            delete_persons_by_ids_in_tx(&mut tx, team_id, &victim_ids, &client, true).await?;
        outcome.deleted = rows.persons;
        outcome.rows_deleted += rows.dependents();

        // The first person that did not fit gives up as many rows as the leftover allows and
        // stays pending, unless it turned out to be live again or to own a live distinct id.
        if let Some((id, uuid)) = trim {
            let still_pending = if !locked.contains(&id) {
                false
            } else {
                match trim_locked_person(&mut tx, team_id, id, remaining).await? {
                    Some(rows) => {
                        outcome.rows_deleted += rows;
                        true
                    }
                    None => {
                        outcome.blocked_uuids.push(uuid);
                        false
                    }
                }
            };
            if !still_pending {
                pending.retain(|u| *u != uuid);
            }
        }
        outcome.pending_uuids = pending;

        tx.commit().await?;

        record_tombstoned_delete_rows(&outcome, &client, &method);

        Ok(outcome)
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
        include_properties: bool,
    ) -> StorageResult<Vec<((i64, String), Option<Person>)>> {
        if team_distinct_ids.is_empty() {
            return Ok(Vec::new());
        }

        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            (
                "operation".to_string(),
                "get_persons_by_distinct_ids_cross_team".to_string(),
            ),
            ("pool".to_string(), BULK_POOL_LABEL.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn =
            PostgresStorage::acquire_timed(&self.bulk_replica_pool, BULK_POOL_LABEL).await?;

        let team_ids: Vec<i32> = team_distinct_ids.iter().map(|(t, _)| *t as i32).collect();
        let distinct_ids: Vec<String> = team_distinct_ids.iter().map(|(_, d)| d.clone()).collect();

        let rows = sqlx::query!(
            r#"
            SELECT p.id, p.uuid as "uuid!", p.team_id::bigint as "team_id!",
                   CASE WHEN $3::boolean THEN p.properties::text ELSE NULL END as "properties?",
                   CASE WHEN $3::boolean THEN p.properties_last_updated_at::text ELSE NULL END as "properties_last_updated_at?",
                   CASE WHEN $3::boolean THEN p.properties_last_operation::text ELSE NULL END as "properties_last_operation?",
                   p.created_at as "created_at!", p.version, p.is_identified as "is_identified!",
                   CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END as is_user_id,
                   p.last_seen_at,
                   d.distinct_id as "distinct_id!"
            FROM posthog_person p
            INNER JOIN posthog_persondistinctid d ON d.person_id = p.id AND d.team_id = p.team_id
            INNER JOIN UNNEST($1::integer[], $2::text[]) AS batch(team_id, distinct_id)
                ON d.team_id = batch.team_id AND d.distinct_id = batch.distinct_id
            WHERE p.is_deleted = false AND d.is_deleted = false
            "#,
            &team_ids,
            &distinct_ids,
            include_properties
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
                ("method".to_string(), method.to_string()),
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

    async fn split_person(
        &self,
        team_id: i64,
        person_id: i64,
        distinct_ids_to_split: &[String],
    ) -> StorageResult<Vec<SplitResult>> {
        if distinct_ids_to_split.is_empty() {
            return Ok(vec![]);
        }

        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            ("operation".to_string(), "split_person".to_string()),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        // All-or-nothing transaction on the bulk primary pool. The statement count
        // is constant (not per-distinct_id), so the lock window stays short; the
        // service-layer cap bounds the number of rows locked.
        let mut tx = self.bulk_primary_pool.begin().await?;

        // No FOR UPDATE on the source person: deletes lock PDI rows before person
        // rows, so locking the person first here would invert that order and risk
        // deadlock. The PDI locks below are what guard the reassignment.
        let person_version: i64 = sqlx::query_scalar!(
            r#"
            SELECT COALESCE(version, 0)::bigint as "version!"
            FROM posthog_person
            WHERE team_id = $1 AND id = $2
            "#,
            team_id as i32,
            person_id
        )
        .fetch_optional(&mut *tx)
        .await?
        .ok_or_else(|| {
            StorageError::NotFound(format!("person_id={person_id} (team_id={team_id})"))
        })?;

        // Lock the PDI rows and validate ownership under the lock: any requested
        // distinct_id that didn't lock either doesn't exist or belongs to another
        // person, and the whole request is rejected.
        let locked_pdis = sqlx::query!(
            r#"
            SELECT distinct_id as "distinct_id!", COALESCE(version, 0)::bigint as "version!"
            FROM posthog_persondistinctid
            WHERE team_id = $1 AND person_id = $2 AND distinct_id = ANY($3) AND is_deleted = false
            FOR UPDATE
            "#,
            team_id as i32,
            person_id,
            distinct_ids_to_split
        )
        .fetch_all(&mut *tx)
        .await?;

        if locked_pdis.len() != distinct_ids_to_split.len() {
            let owned_set: HashSet<&str> = locked_pdis
                .iter()
                .map(|pdi| pdi.distinct_id.as_str())
                .collect();
            let unknown: Vec<&str> = distinct_ids_to_split
                .iter()
                .filter(|did| !owned_set.contains(did.as_str()))
                .map(|s| s.as_str())
                .collect();
            return Err(StorageError::NotFound(format!(
                "distinct_ids {unknown:?} do not belong to person_id={person_id} (team_id={team_id})"
            )));
        }

        let new_person_version = person_version + SPLIT_VERSION_OFFSET;
        // Build all arrays in request order so the response order matches the
        // input order (part of the RPC contract).
        let pdi_version_by_did: HashMap<&str, i64> = locked_pdis
            .iter()
            .map(|pdi| (pdi.distinct_id.as_str(), pdi.version))
            .collect();
        let dids: Vec<String> = distinct_ids_to_split.to_vec();
        let new_uuids: Vec<Uuid> = dids
            .iter()
            .map(|did| personhog_common::persons::person_uuid(team_id, did))
            .collect();
        let pdi_versions: Vec<i64> = dids
            .iter()
            .map(|did| pdi_version_by_did[did.as_str()] + SPLIT_VERSION_OFFSET)
            .collect();

        // Find persons that already exist for these UUIDs: an idempotent
        // re-split, or a tombstone left by a merge or delete of the person
        // that once owned the distinct id. No ON CONFLICT — the partitioned
        // table has a unique index, not a unique constraint, so ON CONFLICT
        // inference doesn't work.
        let existing_persons = sqlx::query!(
            r#"
            SELECT id::bigint as "id!", uuid as "uuid!", created_at as "created_at!"
            FROM posthog_person
            WHERE team_id = $1 AND uuid = ANY($2)
            FOR UPDATE
            "#,
            team_id as i32,
            &new_uuids
        )
        .fetch_all(&mut *tx)
        .await?;

        let mut person_by_uuid: HashMap<Uuid, (i64, DateTime<Utc>)> = existing_persons
            .into_iter()
            .map(|r| (r.uuid, (r.id, r.created_at)))
            .collect();
        let mut version_by_uuid: HashMap<Uuid, i64> = HashMap::new();

        let existing_uuids: HashSet<Uuid> = person_by_uuid.keys().copied().collect();

        let uuids_to_insert: Vec<Uuid> = new_uuids
            .iter()
            .filter(|u| !existing_uuids.contains(u))
            .copied()
            .collect();

        if !uuids_to_insert.is_empty() {
            let inserted = sqlx::query!(
                r#"
                INSERT INTO posthog_person (uuid, team_id, properties, created_at, version, is_identified)
                SELECT u.uuid, $2, '{}'::jsonb, NOW(), $3, false
                FROM unnest($1::uuid[]) AS u(uuid)
                RETURNING id::bigint as "id!", uuid as "uuid!", created_at as "created_at!"
                "#,
                &uuids_to_insert,
                team_id as i32,
                new_person_version
            )
            .fetch_all(&mut *tx)
            .await?;
            for r in inserted {
                person_by_uuid.insert(r.uuid, (r.id, r.created_at));
                version_by_uuid.insert(r.uuid, new_person_version);
            }
        }

        let uuids_to_update: Vec<Uuid> = existing_uuids.into_iter().collect();

        if !uuids_to_update.is_empty() {
            // A tombstoned row comes back to life here, one above its own
            // version so it outranks its ClickHouse tombstone; the split
            // offset applies when that is higher. A live row never moves
            // down, or ClickHouse would ignore the next update from ingestion.
            let updated = sqlx::query!(
                r#"
                UPDATE posthog_person
                SET is_deleted = false,
                    version = GREATEST(
                        COALESCE(version, 0) + CASE WHEN is_deleted THEN 1 ELSE 0 END,
                        $3
                    )
                WHERE team_id = $1 AND uuid = ANY($2)
                RETURNING uuid as "uuid!", version as "version!"
                "#,
                team_id as i32,
                &uuids_to_update,
                new_person_version
            )
            .fetch_all(&mut *tx)
            .await?;
            for r in updated {
                version_by_uuid.insert(r.uuid, r.version);
            }
        }

        let new_person_rows: Vec<(i64, DateTime<Utc>)> = new_uuids
            .iter()
            .map(|u| {
                person_by_uuid.get(u).copied().ok_or_else(|| {
                    StorageError::Query(format!("person insert did not return a row for uuid {u}"))
                })
            })
            .collect::<StorageResult<_>>()?;
        let new_person_ids: Vec<i64> = new_person_rows.iter().map(|(id, _)| *id).collect();

        // Reassign all PDIs to their new persons in one statement.
        let update_result = sqlx::query!(
            r#"
            UPDATE posthog_persondistinctid AS pdi
            SET person_id = m.new_person_id, version = m.new_version
            FROM unnest($2::text[], $3::bigint[], $4::bigint[]) AS m(distinct_id, new_person_id, new_version)
            WHERE pdi.team_id = $1 AND pdi.distinct_id = m.distinct_id
            "#,
            team_id as i32,
            &dids,
            &new_person_ids,
            &pdi_versions
        )
        .execute(&mut *tx)
        .await?;

        if update_result.rows_affected() != dids.len() as u64 {
            return Err(StorageError::Query(format!(
                "expected to reassign {} PDIs but updated {} (team_id={team_id}, person_id={person_id})",
                dids.len(),
                update_result.rows_affected()
            )));
        }

        tx.commit().await?;

        let results: Vec<SplitResult> = dids
            .into_iter()
            .zip(new_uuids)
            .zip(pdi_versions)
            .zip(new_person_rows)
            .map(
                |(((distinct_id, new_person_uuid), pdi_version), (_, new_person_created_at))| {
                    Ok(SplitResult {
                        distinct_id,
                        new_person_uuid,
                        new_person_version: version_by_uuid
                            .get(&new_person_uuid)
                            .copied()
                            .ok_or_else(|| {
                                StorageError::Query(format!(
                                    "version not populated for uuid {new_person_uuid}"
                                ))
                            })?,
                        pdi_version,
                        new_person_created_at,
                    })
                },
            )
            .collect::<StorageResult<Vec<_>>>()?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                ("operation".to_string(), "split_person".to_string()),
                ("pool".to_string(), "bulk_primary".to_string()),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), method.to_string()),
            ],
            results.len() as f64,
        );

        Ok(results)
    }

    async fn set_person_distinct_id_version_floor(
        &self,
        team_id: i64,
        distinct_id: &str,
        min_version: i64,
    ) -> StorageResult<Option<Person>> {
        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            (
                "operation".to_string(),
                "set_person_distinct_id_version_floor".to_string(),
            ),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        // Resolve the distinct_id's person and guardedly bump its version in one
        // round-trip. The `target` CTE returns the person whenever the distinct_id
        // exists, while the `UPDATE` only fires when the stored version is below
        // min_version — so an already-higher version is left intact but the person is
        // still returned. No matching distinct_id yields no person.
        let row = sqlx::query_as!(
            Person,
            r#"
            WITH target AS (
                SELECT person_id FROM posthog_persondistinctid
                WHERE team_id = $1 AND distinct_id = $2
            ),
            updated AS (
                UPDATE posthog_persondistinctid
                SET version = $3
                WHERE team_id = $1 AND distinct_id = $2 AND version < $3
                RETURNING person_id
            )
            SELECT p.id, p.uuid, p.team_id::bigint as "team_id!", p.properties::text as "properties?",
                   p.properties_last_updated_at::text as "properties_last_updated_at?",
                   p.properties_last_operation::text as "properties_last_operation?",
                   p.created_at, p.version, p.is_identified,
                   CASE WHEN p.is_user_id IS NULL THEN NULL ELSE (p.is_user_id != 0) END as is_user_id,
                   p.last_seen_at
            FROM posthog_person p
            INNER JOIN target t ON p.id = t.person_id AND p.team_id = $1
            "#,
            team_id as i32,
            distinct_id,
            min_version
        )
        .fetch_optional(&mut *conn)
        .await?;

        Ok(row)
    }

    async fn set_person_version_floor(
        &self,
        team_id: i64,
        person_id: i64,
        min_version: i64,
    ) -> StorageResult<bool> {
        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            (
                "operation".to_string(),
                "set_person_version_floor".to_string(),
            ),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        // Guarded bump: never lowers an existing version.
        let result = sqlx::query!(
            r#"
            UPDATE posthog_person
            SET version = $3
            WHERE team_id = $1 AND id = $2 AND version < $3
            "#,
            team_id as i32,
            person_id,
            min_version
        )
        .execute(&mut *conn)
        .await?;

        Ok(result.rows_affected() > 0)
    }
}

/// Tombstone the requested persons in one transaction, so the caller gets
/// exactly the versions committed, or none. Persons already tombstoned are
/// reported with the versions they hold, so a retry can republish them.
async fn tombstone_persons_by_uuids(
    storage: &PostgresStorage,
    team_id: i64,
    uuids: &[Uuid],
    client: &str,
) -> StorageResult<DeletePersonsOutcome> {
    let mut tx = storage.bulk_primary_pool.begin().await?;
    // A held row means a merge or revival in flight: fail fast and let the
    // caller retry, as the tombstone drain does, instead of queueing behind it.
    sqlx::query("SET LOCAL lock_timeout = '2s'")
        .execute(&mut *tx)
        .await?;

    // Lock every requested person up front, in id order, the order the
    // ingestion writer and the tombstone drain take their locks in.
    let rows = sqlx::query!(
        r#"
        SELECT id::bigint as "id!", uuid as "uuid!",
               COALESCE(version, 0)::bigint as "version!", is_deleted as "is_deleted!"
        FROM posthog_person
        WHERE team_id = $1 AND uuid = ANY($2)
        ORDER BY id FOR UPDATE
        "#,
        team_id as i32,
        uuids
    )
    .fetch_all(&mut *tx)
    .await?;
    let mut tombstones: Vec<TombstonedPerson> = Vec::with_capacity(rows.len());
    let mut already: Vec<(i64, Uuid, i64)> = Vec::new();
    let mut live: Vec<i64> = Vec::new();
    for row in rows {
        if row.is_deleted {
            already.push((row.id, row.uuid, row.version));
        } else {
            live.push(row.id);
        }
    }

    let chunks: Vec<Vec<i64>> = live
        .chunks(storage.bulk_chunk_size)
        .map(|c| c.to_vec())
        .collect();
    common_metrics::histogram(
        DB_BULK_CHUNKS,
        &[("operation".to_string(), "tombstone_persons".to_string())],
        chunks.len() as f64,
    );
    for chunk in &chunks {
        // Per-person delete: also clear cohort memberships (no DB cascade).
        tombstones
            .extend(tombstone_persons_by_ids_in_tx(&mut tx, team_id, chunk, client, true).await?);
    }
    let deleted = tombstones.len() as i64;

    if !tombstones.is_empty() {
        let queued_uuids: Vec<Uuid> = tombstones.iter().map(|t| t.uuid).collect();
        let queued_versions: Vec<i64> = tombstones.iter().map(|t| t.version).collect();
        sqlx::query!(
            r#"
            INSERT INTO person_tombstone_publish_queue (team_id, person_uuid, person_version)
            SELECT $1, t.person_uuid, t.person_version
            FROM UNNEST($2::uuid[], $3::bigint[]) AS t(person_uuid, person_version)
            ON CONFLICT (team_id, person_uuid) DO UPDATE
            SET person_version = EXCLUDED.person_version,
                tombstoned_at = now(),
                attempts = 0,
                last_attempt_at = NULL,
                last_error = NULL,
                given_up_at = NULL
            WHERE EXCLUDED.person_version > person_tombstone_publish_queue.person_version
            "#,
            team_id as i32,
            &queued_uuids,
            &queued_versions
        )
        .execute(&mut *tx)
        .await?;
    }

    tombstones.extend(with_tombstoned_distinct_ids(&mut tx, team_id, already).await?);

    tx.commit().await?;
    tombstones.sort_by(|a, b| a.uuid.cmp(&b.uuid));
    Ok(DeletePersonsOutcome {
        deleted,
        tombstones: Some(tombstones),
    })
}

/// Tombstone one chunk of persons inside the caller's transaction: their
/// rows get `is_deleted = true` and version + 1, properties scrubbed. The rows
/// stay so a later create on the same key revives above this version.
async fn tombstone_persons_by_ids_in_tx(
    tx: &mut Transaction<'_, Postgres>,
    team_id: i64,
    person_ids: &[i64],
    client: &str,
    delete_cohortpeople: bool,
) -> StorageResult<Vec<TombstonedPerson>> {
    if person_ids.is_empty() {
        return Ok(Vec::new());
    }
    let chunk_labels = [
        (
            "operation".to_string(),
            "tombstone_persons_chunk".to_string(),
        ),
        ("pool".to_string(), "bulk_primary".to_string()),
        ("client".to_string(), client.to_string()),
        ("method".to_string(), current_method_name().to_string()),
    ];
    let _chunk_timer = common_metrics::timing_guard(DB_QUERY_DURATION, &chunk_labels);

    // Take the distinct-id row locks up front, in id order. The multi-row
    // updates below lock in whatever order the plan visits rows, and the
    // ingestion writer updates overlapping rows in sorted batches; sorted
    // acquisition on both sides rules out a deadlock cycle.
    sqlx::query!(
        r#"
        SELECT id FROM posthog_persondistinctid
        WHERE team_id = $1 AND person_id = ANY($2)
        ORDER BY id FOR UPDATE
        "#,
        team_id as i32,
        person_ids
    )
    .fetch_all(&mut **tx)
    .await?;

    let tombstoned_dids = sqlx::query!(
        r#"
        UPDATE posthog_persondistinctid
        SET is_deleted = true, version = COALESCE(version, 0) + 1
        WHERE team_id = $1 AND person_id = ANY($2) AND is_deleted = false
        RETURNING person_id as "person_id!", distinct_id as "distinct_id!", version as "version!"
        "#,
        team_id as i32,
        person_ids
    )
    .fetch_all(&mut **tx)
    .await?;

    common_metrics::histogram(
        DB_ROWS_RETURNED,
        &[
            (
                "operation".to_string(),
                "tombstone_distinct_ids".to_string(),
            ),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), current_method_name().to_string()),
        ],
        tombstoned_dids.len() as f64,
    );

    if delete_cohortpeople {
        sqlx::query!(
            r#"
            DELETE FROM posthog_cohortpeople
            WHERE person_id = ANY($1)
            "#,
            person_ids
        )
        .execute(&mut **tx)
        .await?;
    }

    // The person row stays, so the FK cascade never fires; remove the overrides here.
    sqlx::query!(
        r#"
        DELETE FROM posthog_featureflaghashkeyoverride
        WHERE team_id = $1 AND person_id = ANY($2)
        "#,
        team_id as i32,
        person_ids
    )
    .execute(&mut **tx)
    .await?;

    let tombstoned_persons = sqlx::query!(
        r#"
        UPDATE posthog_person
        SET is_deleted = true,
            version = COALESCE(version, 0) + 1,
            properties = '{}'::jsonb,
            properties_last_updated_at = '{}'::jsonb,
            properties_last_operation = '{}'::jsonb
        WHERE team_id = $1 AND id = ANY($2) AND is_deleted = false
        RETURNING id as "id!", uuid as "uuid!", version as "version!"
        "#,
        team_id as i32,
        person_ids
    )
    .fetch_all(&mut **tx)
    .await?;

    common_metrics::histogram(
        DB_ROWS_RETURNED,
        &[
            ("operation".to_string(), "tombstone_persons".to_string()),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), current_method_name().to_string()),
        ],
        tombstoned_persons.len() as f64,
    );

    Ok(build_tombstones(
        tombstoned_persons
            .into_iter()
            .map(|row| (row.id, row.uuid, row.version))
            .collect(),
        tombstoned_dids
            .into_iter()
            .map(|row| (row.person_id, row.distinct_id, row.version))
            .collect(),
    ))
}

async fn with_tombstoned_distinct_ids(
    conn: &mut sqlx::PgConnection,
    team_id: i64,
    persons: Vec<(i64, Uuid, i64)>,
) -> StorageResult<Vec<TombstonedPerson>> {
    if persons.is_empty() {
        return Ok(Vec::new());
    }
    let person_ids: Vec<i64> = persons.iter().map(|(id, _, _)| *id).collect();
    let dids = sqlx::query!(
        r#"
        SELECT person_id as "person_id!", distinct_id as "distinct_id!",
               COALESCE(version, 0)::bigint as "version!"
        FROM posthog_persondistinctid
        WHERE team_id = $1 AND person_id = ANY($2) AND is_deleted = true
        "#,
        team_id as i32,
        &person_ids
    )
    .fetch_all(&mut *conn)
    .await?;
    Ok(build_tombstones(
        persons,
        dids.into_iter()
            .map(|row| (row.person_id, row.distinct_id, row.version))
            .collect(),
    ))
}

/// Distinct ids are sorted by name so a retry reports the same list as the original call.
fn build_tombstones(
    persons: Vec<(i64, Uuid, i64)>,
    dids: Vec<(i64, String, i64)>,
) -> Vec<TombstonedPerson> {
    let mut by_person: HashMap<i64, Vec<TombstonedDistinctId>> = HashMap::new();
    for (person_id, distinct_id, version) in dids {
        by_person
            .entry(person_id)
            .or_default()
            .push(TombstonedDistinctId {
                distinct_id,
                version,
            });
    }
    persons
        .into_iter()
        .map(|(id, uuid, version)| {
            let mut distinct_ids = by_person.remove(&id).unwrap_or_default();
            distinct_ids.sort_by(|a, b| a.distinct_id.cmp(&b.distinct_id));
            TombstonedPerson {
                uuid,
                version,
                distinct_ids,
            }
        })
        .collect()
}

async fn delete_persons_by_ids_chunk(
    pool: &PgPool,
    team_id: i64,
    person_ids: &[i64],
    client: &str,
    delete_cohortpeople: bool,
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
        ("method".to_string(), current_method_name().to_string()),
    ];
    let _chunk_timer = common_metrics::timing_guard(DB_QUERY_DURATION, &chunk_labels);

    let mut tx = pool.begin().await?;
    let rows =
        delete_persons_by_ids_in_tx(&mut tx, team_id, person_ids, client, delete_cohortpeople)
            .await?;
    tx.commit().await?;

    Ok(rows.persons)
}

/// Rows removed by one `delete_persons_by_ids_in_tx` call.
#[derive(Debug, Clone, Copy, Default)]
struct PersonRowsDeleted {
    persons: i64,
    distinct_ids: i64,
    cohort_memberships: i64,
}

impl PersonRowsDeleted {
    fn dependents(self) -> i64 {
        self.distinct_ids + self.cohort_memberships
    }
}

/// The delete statements every person delete path shares, run inside the caller's
/// transaction so a tombstone check can hold its row locks across them.
async fn delete_persons_by_ids_in_tx(
    tx: &mut Transaction<'_, Postgres>,
    team_id: i64,
    person_ids: &[i64],
    client: &str,
    delete_cohortpeople: bool,
) -> StorageResult<PersonRowsDeleted> {
    if person_ids.is_empty() {
        return Ok(PersonRowsDeleted::default());
    }
    let mut rows = PersonRowsDeleted::default();

    // Lock persons before their distinct ids, the order ingestion and the
    // tombstone paths take, so a concurrent tombstone cannot deadlock with us.
    sqlx::query!(
        r#"
        SELECT id FROM posthog_person
        WHERE team_id = $1 AND id = ANY($2)
        ORDER BY id FOR UPDATE
        "#,
        team_id as i32,
        person_ids
    )
    .fetch_all(&mut **tx)
    .await?;

    // Delete distinct_id rows first — FK is NO ACTION.
    let did_result = sqlx::query!(
        r#"
        DELETE FROM posthog_persondistinctid
        WHERE team_id = $1 AND person_id = ANY($2)
        "#,
        team_id as i32,
        person_ids
    )
    .execute(&mut **tx)
    .await?;
    rows.distinct_ids = did_result.rows_affected() as i64;

    common_metrics::histogram(
        DB_ROWS_RETURNED,
        &[
            (
                "operation".to_string(),
                "delete_distinct_ids_batch_for_team".to_string(),
            ),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), current_method_name().to_string()),
        ],
        did_result.rows_affected() as f64,
    );

    // Cohort memberships have no FK to posthog_person (the constraint was dropped
    // during person-table partitioning), so they don't cascade — delete them
    // explicitly for these persons. Gated because the team-teardown path already
    // clears cohortpeople up front by cohort; only the per-person delete paths
    // need this here.
    if delete_cohortpeople {
        let cohort_result = sqlx::query!(
            r#"
            DELETE FROM posthog_cohortpeople
            WHERE person_id = ANY($1)
            "#,
            person_ids
        )
        .execute(&mut **tx)
        .await?;
        rows.cohort_memberships = cohort_result.rows_affected() as i64;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "delete_cohortpeople_for_persons".to_string(),
                ),
                ("pool".to_string(), "bulk_primary".to_string()),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), current_method_name().to_string()),
            ],
            cohort_result.rows_affected() as f64,
        );
    }

    // Delete person rows (hash key overrides cascade at DB level).
    let result = sqlx::query!(
        r#"
        DELETE FROM posthog_person
        WHERE team_id = $1 AND id = ANY($2)
        "#,
        team_id as i32,
        person_ids
    )
    .execute(&mut **tx)
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
            ("method".to_string(), current_method_name().to_string()),
        ],
        result.rows_affected() as f64,
    );
    rows.persons = result.rows_affected() as i64;

    Ok(rows)
}

/// Persons probed per statement while admitting a request.
const PROBE_BATCH_PERSONS: usize = 25;

/// Dependent rows of one tombstoned person, each count read with a `LIMIT`, so a probe never
/// costs more than that many index entries per table however many rows the person owns.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct DependentRowCounts {
    distinct_ids: i64,
    hash_key_overrides: i64,
    cohort_memberships: i64,
}

impl DependentRowCounts {
    fn total(self) -> i64 {
        self.distinct_ids + self.hash_key_overrides + self.cohort_memberships
    }
}

/// Called by every exit that runs the resolve query. That query decides the counts, so the early
/// return for a call with no tombstoned candidate would otherwise hide live persons here.
fn record_tombstoned_delete_rows(outcome: &TombstonedDeleteOutcome, client: &str, method: &str) {
    for (operation, value) in [
        ("delete_tombstoned_persons_deleted", outcome.deleted),
        (
            "delete_tombstoned_persons_skipped_live",
            outcome.skipped_live,
        ),
        (
            "delete_tombstoned_persons_blocked",
            outcome.blocked_uuids.len() as i64,
        ),
        (
            "delete_tombstoned_persons_pending",
            outcome.pending_uuids.len() as i64,
        ),
        (
            "delete_tombstoned_persons_rows_deleted",
            outcome.rows_deleted,
        ),
    ] {
        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                ("operation".to_string(), operation.to_string()),
                ("pool".to_string(), "bulk_primary".to_string()),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), method.to_string()),
            ],
            value as f64,
        );
    }
}

async fn probe_dependent_rows<'e, E>(
    executor: E,
    team_id: i64,
    person_ids: &[i64],
    limit: i64,
) -> StorageResult<HashMap<i64, DependentRowCounts>>
where
    E: sqlx::Executor<'e, Database = Postgres>,
{
    let rows = sqlx::query!(
        r#"
        SELECT p.id AS "id!",
            (SELECT count(*) FROM (SELECT 1 FROM posthog_persondistinctid
                WHERE team_id = $1 AND person_id = p.id LIMIT $3) t) AS "distinct_ids!",
            (SELECT count(*) FROM (SELECT 1 FROM posthog_featureflaghashkeyoverride
                WHERE team_id = $1 AND person_id = p.id LIMIT $3) t) AS "hash_key_overrides!",
            (SELECT count(*) FROM (SELECT 1 FROM posthog_cohortpeople
                WHERE person_id = p.id LIMIT $3) t) AS "cohort_memberships!"
        FROM unnest($2::bigint[]) AS p(id)
        "#,
        team_id as i32,
        person_ids,
        limit
    )
    .fetch_all(executor)
    .await?;
    Ok(rows
        .into_iter()
        .map(|row| {
            (
                row.id,
                DependentRowCounts {
                    distinct_ids: row.distinct_ids,
                    hash_key_overrides: row.hash_key_overrides,
                    cohort_memberships: row.cohort_memberships,
                },
            )
        })
        .collect())
}

/// Decides, in id order, which candidates one call deletes whole. A person whose dependent rows
/// fit the leftover budget is admitted, up to `max_persons`; the first that does not fit is kept
/// for the trim step; every other candidate is pending. Small persons never wait behind a big one.
#[derive(Debug)]
struct Admission {
    remaining: i64,
    max_persons: usize,
    admitted: Vec<(i64, Uuid)>,
    trim: Option<(i64, Uuid)>,
    pending: Vec<Uuid>,
}

impl Admission {
    fn new(budget: i64, max_persons: usize) -> Self {
        Self {
            remaining: budget,
            max_persons,
            admitted: Vec::new(),
            trim: None,
            pending: Vec::new(),
        }
    }

    fn wants_more(&self) -> bool {
        self.admitted.len() < self.max_persons
    }

    /// One more than the leftover, so a count at the limit reads as "does not fit".
    fn probe_limit(&self) -> i64 {
        self.remaining + 1
    }

    fn offer(&mut self, id: i64, uuid: Uuid, counts: DependentRowCounts) {
        let total = counts.total();
        if self.wants_more() && total <= self.remaining {
            self.remaining -= total;
            self.admitted.push((id, uuid));
            return;
        }
        if self.trim.is_none() && total > self.remaining {
            self.trim = Some((id, uuid));
        }
        self.pending.push(uuid);
    }

    fn defer(&mut self, uuids: impl IntoIterator<Item = Uuid>) {
        self.pending.extend(uuids);
    }
}

/// Deletes up to `budget` dependent rows of a person the caller holds locked: distinct ids
/// first, then hash key overrides, then cohort memberships. Returns the rows deleted, or `None`
/// when a live distinct id was found, in which case nothing of this person is deleted.
async fn trim_locked_person(
    tx: &mut Transaction<'_, Postgres>,
    team_id: i64,
    person_id: i64,
    budget: i64,
) -> StorageResult<Option<i64>> {
    // No is_deleted filter: the scan then visits at most `budget` index entries, and a live
    // mapping among them means ingestion can still reach the person.
    let mappings = sqlx::query!(
        r#"
        SELECT id::bigint AS "id!", is_deleted AS "is_deleted!"
        FROM posthog_persondistinctid
        WHERE team_id = $1 AND person_id = $2
        LIMIT $3
        FOR UPDATE
        "#,
        team_id as i32,
        person_id,
        budget
    )
    .fetch_all(&mut **tx)
    .await?;
    if mappings.iter().any(|row| !row.is_deleted) {
        return Ok(None);
    }

    let mut remaining = budget;
    let mut deleted = 0i64;
    if !mappings.is_empty() {
        let ids: Vec<i64> = mappings.iter().map(|row| row.id).collect();
        let n = sqlx::query!(
            "DELETE FROM posthog_persondistinctid WHERE team_id = $1 AND id = ANY($2)",
            team_id as i32,
            ids.as_slice()
        )
        .execute(&mut **tx)
        .await?
        .rows_affected() as i64;
        deleted += n;
        remaining -= n;
    }

    if remaining > 0 {
        let ids: Vec<i64> = sqlx::query_scalar!(
            r#"
            SELECT id::bigint AS "id!"
            FROM posthog_featureflaghashkeyoverride
            WHERE team_id = $1 AND person_id = $2
            LIMIT $3
            "#,
            team_id as i32,
            person_id,
            remaining
        )
        .fetch_all(&mut **tx)
        .await?;
        if !ids.is_empty() {
            let n = sqlx::query!(
                "DELETE FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 AND id = ANY($2::bigint[])",
                team_id as i32,
                ids.as_slice()
            )
            .execute(&mut **tx)
            .await?
            .rows_affected() as i64;
            deleted += n;
            remaining -= n;
        }
    }

    if remaining > 0 {
        let ids: Vec<i64> = sqlx::query_scalar!(
            r#"
            SELECT id::bigint AS "id!"
            FROM posthog_cohortpeople
            WHERE person_id = $1
            LIMIT $2
            "#,
            person_id,
            remaining
        )
        .fetch_all(&mut **tx)
        .await?;
        if !ids.is_empty() {
            deleted += sqlx::query!(
                "DELETE FROM posthog_cohortpeople WHERE id = ANY($1)",
                ids.as_slice()
            )
            .execute(&mut **tx)
            .await?
            .rows_affected() as i64;
        }
    }

    Ok(Some(deleted))
}

#[cfg(test)]
mod tests {
    use super::{Admission, DependentRowCounts};
    use uuid::Uuid;

    fn counts(
        distinct_ids: i64,
        hash_key_overrides: i64,
        cohort_memberships: i64,
    ) -> DependentRowCounts {
        DependentRowCounts {
            distinct_ids,
            hash_key_overrides,
            cohort_memberships,
        }
    }

    fn offer_all(admission: &mut Admission, persons: &[(i64, DependentRowCounts)]) -> Vec<Uuid> {
        let uuids: Vec<Uuid> = persons.iter().map(|_| Uuid::new_v4()).collect();
        for ((id, c), uuid) in persons.iter().zip(&uuids) {
            admission.offer(*id, *uuid, *c);
        }
        uuids
    }

    #[test]
    fn admits_what_fits_and_keeps_the_first_misfit_for_the_trim() {
        let mut admission = Admission::new(6, 100);
        let persons = [
            (1, counts(2, 1, 0)), // fits, 3 left
            (2, counts(4, 0, 0)), // misfit: the trim candidate
            (3, counts(0, 0, 3)), // fits exactly, 0 left
            (4, counts(5, 0, 0)), // misfit, but the trim slot is taken
            (5, counts(0, 0, 0)), // still fits with nothing left
        ];
        let uuids = offer_all(&mut admission, &persons);

        assert_eq!(
            admission.admitted,
            vec![(1, uuids[0]), (3, uuids[2]), (5, uuids[4])]
        );
        assert_eq!(admission.trim, Some((2, uuids[1])));
        assert_eq!(admission.pending, vec![uuids[1], uuids[3]]);
        assert_eq!(admission.remaining, 0);
        assert_eq!(admission.probe_limit(), 1);
    }

    #[test]
    fn the_person_cap_defers_the_rest_without_choosing_a_trim() {
        let mut admission = Admission::new(10, 2);
        let persons = [
            (1, counts(0, 0, 0)),
            (2, counts(1, 0, 0)),
            (3, counts(0, 0, 0)),
        ];
        let uuids = offer_all(&mut admission, &persons);
        assert!(!admission.wants_more());
        let deferred = Uuid::new_v4();
        admission.defer([deferred]);

        assert_eq!(admission.admitted, vec![(1, uuids[0]), (2, uuids[1])]);
        assert_eq!(admission.trim, None);
        assert_eq!(admission.pending, vec![uuids[2], deferred]);
        assert_eq!(admission.remaining, 9);
    }

    #[test]
    fn a_misfit_over_the_cap_is_still_the_trim_candidate() {
        let mut admission = Admission::new(3, 1);
        let persons = [(1, counts(0, 0, 0)), (2, counts(4, 0, 0))];
        let uuids = offer_all(&mut admission, &persons);

        assert_eq!(admission.admitted, vec![(1, uuids[0])]);
        assert_eq!(admission.trim, Some((2, uuids[1])));
        assert_eq!(admission.pending, vec![uuids[1]]);
    }
}
