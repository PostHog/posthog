use std::collections::HashMap;

use async_trait::async_trait;
use sqlx::FromRow;
use uuid::Uuid;

use super::{PostgresStorage, DB_QUERY_DURATION};
use crate::storage::error::StorageResult;
use crate::storage::traits::PersonLookup;
use crate::storage::types::Person;

#[derive(Debug, Clone, FromRow)]
struct PersonRow {
    id: i64,
    uuid: Uuid,
    team_id: i32,
    properties: serde_json::Value,
    properties_last_updated_at: Option<serde_json::Value>,
    properties_last_operation: Option<serde_json::Value>,
    created_at: chrono::DateTime<chrono::Utc>,
    version: Option<i64>,
    is_identified: bool,
    is_user_id: Option<i32>,
}

impl From<PersonRow> for Person {
    fn from(row: PersonRow) -> Self {
        Person {
            id: row.id,
            uuid: row.uuid,
            team_id: row.team_id.into(),
            properties: row.properties,
            properties_last_updated_at: row.properties_last_updated_at,
            properties_last_operation: row.properties_last_operation,
            created_at: row.created_at,
            version: row.version,
            is_identified: row.is_identified,
            is_user_id: row.is_user_id.map(|v| v != 0),
        }
    }
}

#[derive(Debug, Clone, FromRow)]
struct PersonWithDistinctIdRow {
    id: i64,
    uuid: Uuid,
    team_id: i32,
    properties: serde_json::Value,
    properties_last_updated_at: Option<serde_json::Value>,
    properties_last_operation: Option<serde_json::Value>,
    created_at: chrono::DateTime<chrono::Utc>,
    version: Option<i64>,
    is_identified: bool,
    is_user_id: Option<i32>,
    distinct_id: String,
}

#[async_trait]
impl PersonLookup for PostgresStorage {
    async fn get_person_by_id(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> StorageResult<Option<Person>> {
        let labels = [("operation".to_string(), "get_person_by_id".to_string())];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let row = sqlx::query_as::<_, PersonRow>(
            r#"
            SELECT id, uuid, team_id, properties, properties_last_updated_at,
                   properties_last_operation, created_at, version, is_identified, is_user_id
            FROM posthog_person
            WHERE team_id = $1 AND id = $2
            "#,
        )
        .bind(team_id)
        .bind(person_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(row.map(Person::from))
    }

    async fn get_person_by_uuid(&self, team_id: i64, uuid: Uuid) -> StorageResult<Option<Person>> {
        let labels = [("operation".to_string(), "get_person_by_uuid".to_string())];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let row = sqlx::query_as::<_, PersonRow>(
            r#"
            SELECT id, uuid, team_id, properties, properties_last_updated_at,
                   properties_last_operation, created_at, version, is_identified, is_user_id
            FROM posthog_person
            WHERE team_id = $1 AND uuid = $2
            "#,
        )
        .bind(team_id)
        .bind(uuid)
        .fetch_optional(&self.pool)
        .await?;

        Ok(row.map(Person::from))
    }

    async fn get_persons_by_ids(
        &self,
        team_id: i64,
        person_ids: &[i64],
    ) -> StorageResult<Vec<Person>> {
        if person_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [("operation".to_string(), "get_persons_by_ids".to_string())];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, PersonRow>(
            r#"
            SELECT id, uuid, team_id, properties, properties_last_updated_at,
                   properties_last_operation, created_at, version, is_identified, is_user_id
            FROM posthog_person
            WHERE team_id = $1 AND id = ANY($2)
            "#,
        )
        .bind(team_id)
        .bind(person_ids)
        .fetch_all(&self.pool)
        .await?;

        Ok(rows.into_iter().map(Person::from).collect())
    }

    async fn get_persons_by_uuids(
        &self,
        team_id: i64,
        uuids: &[Uuid],
    ) -> StorageResult<Vec<Person>> {
        if uuids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [("operation".to_string(), "get_persons_by_uuids".to_string())];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, PersonRow>(
            r#"
            SELECT id, uuid, team_id, properties, properties_last_updated_at,
                   properties_last_operation, created_at, version, is_identified, is_user_id
            FROM posthog_person
            WHERE team_id = $1 AND uuid = ANY($2)
            "#,
        )
        .bind(team_id)
        .bind(uuids)
        .fetch_all(&self.pool)
        .await?;

        Ok(rows.into_iter().map(Person::from).collect())
    }

    async fn get_person_by_distinct_id(
        &self,
        team_id: i64,
        distinct_id: &str,
    ) -> StorageResult<Option<Person>> {
        let labels = [(
            "operation".to_string(),
            "get_person_by_distinct_id".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let row = sqlx::query_as::<_, PersonRow>(
            r#"
            SELECT p.id, p.uuid, p.team_id, p.properties, p.properties_last_updated_at,
                   p.properties_last_operation, p.created_at, p.version, p.is_identified, p.is_user_id
            FROM posthog_person p
            INNER JOIN posthog_persondistinctid d ON p.id = d.person_id AND p.team_id = d.team_id
            WHERE p.team_id = $1 AND d.distinct_id = $2
            LIMIT 1
            "#,
        )
        .bind(team_id)
        .bind(distinct_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(row.map(Person::from))
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<(String, Option<Person>)>> {
        if distinct_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "get_persons_by_distinct_ids_in_team".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, PersonWithDistinctIdRow>(
            r#"
            SELECT p.id, p.uuid, p.team_id, p.properties, p.properties_last_updated_at,
                   p.properties_last_operation, p.created_at, p.version, p.is_identified, p.is_user_id,
                   d.distinct_id
            FROM posthog_person p
            INNER JOIN posthog_persondistinctid d ON p.id = d.person_id AND p.team_id = d.team_id
            WHERE p.team_id = $1 AND d.distinct_id = ANY($2)
            "#,
        )
        .bind(team_id)
        .bind(distinct_ids)
        .fetch_all(&self.pool)
        .await?;

        let found: HashMap<String, Person> = rows
            .into_iter()
            .map(|row| {
                let distinct_id = row.distinct_id.clone();
                let person = Person {
                    id: row.id,
                    uuid: row.uuid,
                    team_id: row.team_id.into(),
                    properties: row.properties,
                    properties_last_updated_at: row.properties_last_updated_at,
                    properties_last_operation: row.properties_last_operation,
                    created_at: row.created_at,
                    version: row.version,
                    is_identified: row.is_identified,
                    is_user_id: row.is_user_id.map(|v| v != 0),
                };
                (distinct_id, person)
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

        let labels = [(
            "operation".to_string(),
            "get_persons_by_distinct_ids_cross_team".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        // Use UNNEST to batch the cross-team lookup
        let team_ids: Vec<i32> = team_distinct_ids.iter().map(|(t, _)| *t as i32).collect();
        let distinct_ids: Vec<&str> = team_distinct_ids.iter().map(|(_, d)| d.as_str()).collect();

        let rows = sqlx::query_as::<_, PersonWithDistinctIdRow>(
            r#"
            SELECT p.id, p.uuid, p.team_id, p.properties, p.properties_last_updated_at,
                   p.properties_last_operation, p.created_at, p.version, p.is_identified, p.is_user_id,
                   d.distinct_id
            FROM posthog_person p
            INNER JOIN posthog_persondistinctid d ON d.person_id = p.id AND d.team_id = p.team_id
            INNER JOIN UNNEST($1::integer[], $2::text[]) AS batch(team_id, distinct_id)
                ON d.team_id = batch.team_id AND d.distinct_id = batch.distinct_id
            "#,
        )
        .bind(&team_ids)
        .bind(&distinct_ids)
        .fetch_all(&self.pool)
        .await?;

        let found: HashMap<(i64, String), Person> = rows
            .into_iter()
            .map(|row| {
                let key = (row.team_id as i64, row.distinct_id.clone());
                let person = Person {
                    id: row.id,
                    uuid: row.uuid,
                    team_id: row.team_id.into(),
                    properties: row.properties,
                    properties_last_updated_at: row.properties_last_updated_at,
                    properties_last_operation: row.properties_last_operation,
                    created_at: row.created_at,
                    version: row.version,
                    is_identified: row.is_identified,
                    is_user_id: row.is_user_id.map(|v| v != 0),
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
