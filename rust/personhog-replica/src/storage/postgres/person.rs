use std::collections::HashMap;

use async_trait::async_trait;
use uuid::Uuid;

use super::{PostgresStorage, DB_QUERY_DURATION, DB_ROWS_RETURNED};
use crate::storage::error::StorageResult;
use crate::storage::traits::PersonLookup;
use crate::storage::types::Person;

const POOL_LABEL: &str = "replica";

#[async_trait]
impl PersonLookup for PostgresStorage {
    async fn get_person_by_id(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> StorageResult<Option<Person>> {
        let labels = [
            ("operation".to_string(), "get_person_by_id".to_string()),
            ("pool".to_string(), POOL_LABEL.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let row = sqlx::query_as!(
            Person,
            r#"
            SELECT id, uuid, team_id::bigint as "team_id!", properties,
                   properties_last_updated_at, properties_last_operation,
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
        let labels = [
            ("operation".to_string(), "get_person_by_uuid".to_string()),
            ("pool".to_string(), POOL_LABEL.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let row = sqlx::query_as!(
            Person,
            r#"
            SELECT id, uuid, team_id::bigint as "team_id!", properties,
                   properties_last_updated_at, properties_last_operation,
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

        let labels = [
            ("operation".to_string(), "get_persons_by_ids".to_string()),
            ("pool".to_string(), POOL_LABEL.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let rows = sqlx::query_as!(
            Person,
            r#"
            SELECT id, uuid, team_id::bigint as "team_id!", properties,
                   properties_last_updated_at, properties_last_operation,
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
            &[("operation".to_string(), "get_persons_by_ids".to_string())],
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

        let labels = [
            ("operation".to_string(), "get_persons_by_uuids".to_string()),
            ("pool".to_string(), POOL_LABEL.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let rows = sqlx::query_as!(
            Person,
            r#"
            SELECT id, uuid, team_id::bigint as "team_id!", properties,
                   properties_last_updated_at, properties_last_operation,
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
            &[("operation".to_string(), "get_persons_by_uuids".to_string())],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_person_by_distinct_id(
        &self,
        team_id: i64,
        distinct_id: &str,
    ) -> StorageResult<Option<Person>> {
        let labels = [
            (
                "operation".to_string(),
                "get_person_by_distinct_id".to_string(),
            ),
            ("pool".to_string(), POOL_LABEL.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let row = sqlx::query_as!(
            Person,
            r#"
            SELECT p.id, p.uuid, p.team_id::bigint as "team_id!", p.properties,
                   p.properties_last_updated_at, p.properties_last_operation,
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

        let labels = [
            (
                "operation".to_string(),
                "get_persons_by_distinct_ids_in_team".to_string(),
            ),
            ("pool".to_string(), POOL_LABEL.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        // Use query!() since we need distinct_id alongside Person fields
        let rows = sqlx::query!(
            r#"
            SELECT p.id, p.uuid as "uuid!", p.team_id::bigint as "team_id!",
                   p.properties as "properties!",
                   p.properties_last_updated_at, p.properties_last_operation,
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
            &[(
                "operation".to_string(),
                "get_persons_by_distinct_ids_in_team".to_string(),
            )],
            rows.len() as f64,
        );

        let found: HashMap<String, Person> = rows
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
            .map(|did| (did.clone(), found.get(did).cloned()))
            .collect())
    }

    async fn get_persons_by_distinct_ids_cross_team(
        &self,
        team_distinct_ids: &[(i64, String)],
    ) -> StorageResult<Vec<((i64, String), Option<Person>)>> {
        if team_distinct_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [
            (
                "operation".to_string(),
                "get_persons_by_distinct_ids_cross_team".to_string(),
            ),
            ("pool".to_string(), POOL_LABEL.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.replica_pool, POOL_LABEL).await?;

        let team_ids: Vec<i32> = team_distinct_ids.iter().map(|(t, _)| *t as i32).collect();
        let distinct_ids: Vec<String> = team_distinct_ids.iter().map(|(_, d)| d.clone()).collect();

        // Use query!() since we need distinct_id alongside Person fields
        let rows = sqlx::query!(
            r#"
            SELECT p.id, p.uuid as "uuid!", p.team_id::bigint as "team_id!",
                   p.properties as "properties!",
                   p.properties_last_updated_at, p.properties_last_operation,
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
            &[(
                "operation".to_string(),
                "get_persons_by_distinct_ids_cross_team".to_string(),
            )],
            rows.len() as f64,
        );

        let found: HashMap<(i64, String), Person> = rows
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
                (key.clone(), found.get(&key).cloned())
            })
            .collect())
    }
}
