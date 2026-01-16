use std::collections::HashMap;
use std::sync::Arc;

use async_trait::async_trait;
use sqlx::{postgres::PgPool, FromRow};
use uuid::Uuid;

use super::{
    CohortMembership, DistinctIdMapping, DistinctIdWithVersion, Group, GroupIdentifier, GroupKey,
    GroupTypeMapping, HashKeyOverride, Person, PersonIdWithOverrideKeys, PersonIdWithOverrides,
    PersonStorage, StorageError, StorageResult,
};

const DB_QUERY_DURATION: &str = "personhog_replica_db_query_duration_ms";

/// Postgres implementation of PersonStorage
pub struct PostgresStorage {
    pool: Arc<PgPool>,
}

impl PostgresStorage {
    pub fn new(pool: Arc<PgPool>) -> Self {
        Self { pool }
    }
}

// ============================================================
// Internal row types for sqlx mapping
// ============================================================

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

#[derive(Debug, Clone, FromRow)]
struct GroupRow {
    id: i32,
    team_id: i32,
    group_type_index: i32,
    group_key: String,
    group_properties: serde_json::Value,
    created_at: chrono::DateTime<chrono::Utc>,
    properties_last_updated_at: Option<serde_json::Value>,
    properties_last_operation: Option<serde_json::Value>,
    version: i64,
}

impl From<GroupRow> for Group {
    fn from(row: GroupRow) -> Self {
        Group {
            id: row.id.into(),
            team_id: row.team_id.into(),
            group_type_index: row.group_type_index,
            group_key: row.group_key,
            group_properties: row.group_properties,
            created_at: row.created_at,
            properties_last_updated_at: row.properties_last_updated_at,
            properties_last_operation: row.properties_last_operation,
            version: row.version,
        }
    }
}

#[derive(Debug, Clone, FromRow)]
struct GroupTypeMappingRow {
    id: i32,
    team_id: i32,
    project_id: i64,
    group_type: String,
    group_type_index: i32,
    name_singular: Option<String>,
    name_plural: Option<String>,
    default_columns: Option<serde_json::Value>,
    detail_dashboard_id: Option<i64>,
    created_at: Option<chrono::DateTime<chrono::Utc>>,
}

impl From<GroupTypeMappingRow> for GroupTypeMapping {
    fn from(row: GroupTypeMappingRow) -> Self {
        GroupTypeMapping {
            id: row.id.into(),
            team_id: row.team_id.into(),
            project_id: row.project_id,
            group_type: row.group_type,
            group_type_index: row.group_type_index,
            name_singular: row.name_singular,
            name_plural: row.name_plural,
            default_columns: row.default_columns,
            detail_dashboard_id: row.detail_dashboard_id,
            created_at: row.created_at,
        }
    }
}

#[derive(Debug, Clone, FromRow)]
struct DistinctIdRow {
    person_id: i64,
    distinct_id: String,
}

#[derive(Debug, Clone, FromRow)]
struct DistinctIdWithVersionRow {
    distinct_id: String,
    version: Option<i64>,
}

#[derive(Debug, Clone, FromRow)]
struct PersonIdAndHashKeyOverrideRow {
    person_id: i64,
    distinct_id: String,
    feature_flag_key: Option<String>,
    hash_key: Option<String>,
}

#[derive(Debug, Clone, FromRow)]
struct PersonIdWithOverrideKeyRow {
    person_id: i64,
    feature_flag_key: Option<String>,
}

impl From<sqlx::Error> for StorageError {
    fn from(err: sqlx::Error) -> Self {
        match &err {
            sqlx::Error::PoolTimedOut | sqlx::Error::PoolClosed => StorageError::PoolExhausted,

            sqlx::Error::Io(_) | sqlx::Error::Tls(_) => StorageError::Connection(err.to_string()),

            _ => StorageError::Query(err.to_string()),
        }
    }
}

#[async_trait]
impl PersonStorage for PostgresStorage {
    // ============================================================
    // Person lookups by ID/UUID
    // ============================================================

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
        .fetch_optional(&*self.pool)
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
        .fetch_optional(&*self.pool)
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
        .fetch_all(&*self.pool)
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
        .fetch_all(&*self.pool)
        .await?;

        Ok(rows.into_iter().map(Person::from).collect())
    }

    // ============================================================
    // Person lookups by Distinct ID
    // ============================================================

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
        .fetch_optional(&*self.pool)
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
        .fetch_all(&*self.pool)
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
        .fetch_all(&*self.pool)
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

    // ============================================================
    // Distinct ID operations
    // ============================================================

    async fn get_distinct_ids_for_person(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> StorageResult<Vec<DistinctIdWithVersion>> {
        let labels = [(
            "operation".to_string(),
            "get_distinct_ids_for_person".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, DistinctIdWithVersionRow>(
            r#"
            SELECT distinct_id, version
            FROM posthog_persondistinctid
            WHERE team_id = $1 AND person_id = $2
            "#,
        )
        .bind(team_id)
        .bind(person_id)
        .fetch_all(&*self.pool)
        .await?;

        Ok(rows
            .into_iter()
            .map(|r| DistinctIdWithVersion {
                distinct_id: r.distinct_id,
                version: r.version,
            })
            .collect())
    }

    async fn get_distinct_ids_for_persons(
        &self,
        team_id: i64,
        person_ids: &[i64],
    ) -> StorageResult<Vec<DistinctIdMapping>> {
        if person_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "get_distinct_ids_for_persons".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, DistinctIdRow>(
            r#"
            SELECT person_id, distinct_id
            FROM posthog_persondistinctid
            WHERE team_id = $1 AND person_id = ANY($2)
            "#,
        )
        .bind(team_id)
        .bind(person_ids)
        .fetch_all(&*self.pool)
        .await?;

        Ok(rows
            .into_iter()
            .map(|r| DistinctIdMapping {
                person_id: r.person_id,
                distinct_id: r.distinct_id,
            })
            .collect())
    }

    // ============================================================
    // Feature Flag support
    // ============================================================

    async fn get_person_ids_and_hash_key_overrides(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<PersonIdWithOverrides>> {
        if distinct_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "get_person_ids_and_hash_key_overrides".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, PersonIdAndHashKeyOverrideRow>(
            r#"
            SELECT ppd.person_id, ppd.distinct_id, fhko.feature_flag_key, fhko.hash_key
            FROM posthog_persondistinctid ppd
            LEFT JOIN posthog_featureflaghashkeyoverride fhko
                ON fhko.person_id = ppd.person_id AND fhko.team_id = ppd.team_id
            WHERE ppd.team_id = $1 AND ppd.distinct_id = ANY($2)
            "#,
        )
        .bind(team_id)
        .bind(distinct_ids)
        .fetch_all(&*self.pool)
        .await?;

        // Group by (person_id, distinct_id) and collect overrides
        let mut result_map: HashMap<(i64, String), Vec<HashKeyOverride>> = HashMap::new();
        for row in rows {
            let key = (row.person_id, row.distinct_id.clone());
            if let (Some(flag_key), Some(hash_key)) = (row.feature_flag_key, row.hash_key) {
                result_map.entry(key).or_default().push(HashKeyOverride {
                    feature_flag_key: flag_key,
                    hash_key,
                });
            } else {
                // Ensure the key exists even if there are no overrides
                result_map.entry(key).or_default();
            }
        }

        Ok(result_map
            .into_iter()
            .map(
                |((person_id, distinct_id), overrides)| PersonIdWithOverrides {
                    person_id,
                    distinct_id,
                    overrides,
                },
            )
            .collect())
    }

    async fn get_existing_person_ids_with_override_keys(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<PersonIdWithOverrideKeys>> {
        if distinct_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "get_existing_person_ids_with_override_keys".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, PersonIdWithOverrideKeyRow>(
            r#"
            SELECT DISTINCT p.person_id, existing.feature_flag_key
            FROM posthog_persondistinctid p
            LEFT JOIN posthog_featureflaghashkeyoverride existing
                ON existing.person_id = p.person_id AND existing.team_id = p.team_id
            WHERE p.team_id = $1 AND p.distinct_id = ANY($2)
                AND EXISTS (SELECT 1 FROM posthog_person WHERE id = p.person_id AND team_id = p.team_id)
            "#,
        )
        .bind(team_id)
        .bind(distinct_ids)
        .fetch_all(&*self.pool)
        .await?;

        let mut result_map: HashMap<i64, Vec<String>> = HashMap::new();
        for row in rows {
            if let Some(flag_key) = row.feature_flag_key {
                result_map.entry(row.person_id).or_default().push(flag_key);
            } else {
                result_map.entry(row.person_id).or_default();
            }
        }

        Ok(result_map
            .into_iter()
            .map(
                |(person_id, existing_feature_flag_keys)| PersonIdWithOverrideKeys {
                    person_id,
                    existing_feature_flag_keys,
                },
            )
            .collect())
    }

    // ============================================================
    // Cohort operations
    // ============================================================

    async fn check_cohort_membership(
        &self,
        person_id: i64,
        cohort_ids: &[i64],
    ) -> StorageResult<Vec<CohortMembership>> {
        if cohort_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "check_cohort_membership".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let cohort_ids_i32: Vec<i32> = cohort_ids.iter().map(|&id| id as i32).collect();

        let member_ids: Vec<i32> = sqlx::query_scalar(
            r#"
            SELECT cohort_id
            FROM posthog_cohortpeople
            WHERE person_id = $1 AND cohort_id = ANY($2)
            "#,
        )
        .bind(person_id)
        .bind(&cohort_ids_i32)
        .fetch_all(&*self.pool)
        .await?;

        let member_set: std::collections::HashSet<i64> =
            member_ids.into_iter().map(|id| id as i64).collect();

        Ok(cohort_ids
            .iter()
            .map(|&cohort_id| CohortMembership {
                cohort_id,
                is_member: member_set.contains(&cohort_id),
            })
            .collect())
    }

    // ============================================================
    // Group operations
    // ============================================================

    async fn get_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
    ) -> StorageResult<Option<Group>> {
        let labels = [("operation".to_string(), "get_group".to_string())];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let row = sqlx::query_as::<_, GroupRow>(
            r#"
            SELECT id, team_id, group_type_index, group_key, group_properties,
                   created_at, properties_last_updated_at, properties_last_operation, version
            FROM posthog_group
            WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3
            "#,
        )
        .bind(team_id)
        .bind(group_type_index)
        .bind(group_key)
        .fetch_optional(&*self.pool)
        .await?;

        Ok(row.map(Group::from))
    }

    async fn get_groups(
        &self,
        team_id: i64,
        identifiers: &[GroupIdentifier],
    ) -> StorageResult<Vec<Group>> {
        if identifiers.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [("operation".to_string(), "get_groups".to_string())];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let group_type_indexes: Vec<i32> = identifiers.iter().map(|i| i.group_type_index).collect();
        let group_keys: Vec<&str> = identifiers.iter().map(|i| i.group_key.as_str()).collect();

        let rows = sqlx::query_as::<_, GroupRow>(
            r#"
            SELECT g.id, g.team_id, g.group_type_index, g.group_key, g.group_properties,
                   g.created_at, g.properties_last_updated_at, g.properties_last_operation, g.version
            FROM posthog_group g
            INNER JOIN UNNEST($2::integer[], $3::text[]) AS t(group_type_index, group_key)
                ON g.group_type_index = t.group_type_index AND g.group_key = t.group_key
            WHERE g.team_id = $1
            "#,
        )
        .bind(team_id)
        .bind(&group_type_indexes)
        .bind(&group_keys)
        .fetch_all(&*self.pool)
        .await?;

        Ok(rows.into_iter().map(Group::from).collect())
    }

    async fn get_groups_batch(&self, keys: &[GroupKey]) -> StorageResult<Vec<(GroupKey, Group)>> {
        if keys.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [("operation".to_string(), "get_groups_batch".to_string())];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let team_ids: Vec<i32> = keys.iter().map(|k| k.team_id as i32).collect();
        let group_type_indexes: Vec<i32> = keys.iter().map(|k| k.group_type_index).collect();
        let group_keys: Vec<&str> = keys.iter().map(|k| k.group_key.as_str()).collect();

        let rows = sqlx::query_as::<_, GroupRow>(
            r#"
            SELECT g.id, g.team_id, g.group_type_index, g.group_key, g.group_properties,
                   g.created_at, g.properties_last_updated_at, g.properties_last_operation, g.version
            FROM posthog_group g
            INNER JOIN UNNEST($1::integer[], $2::integer[], $3::text[]) AS t(team_id, group_type_index, group_key)
                ON g.team_id = t.team_id AND g.group_type_index = t.group_type_index AND g.group_key = t.group_key
            "#,
        )
        .bind(&team_ids)
        .bind(&group_type_indexes)
        .bind(&group_keys)
        .fetch_all(&*self.pool)
        .await?;

        Ok(rows
            .into_iter()
            .map(|row| {
                let key = GroupKey {
                    team_id: row.team_id as i64,
                    group_type_index: row.group_type_index,
                    group_key: row.group_key.clone(),
                };
                (key, Group::from(row))
            })
            .collect())
    }

    // ============================================================
    // Group Type Mappings
    // ============================================================

    async fn get_group_type_mappings_by_team_id(
        &self,
        team_id: i64,
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        let labels = [(
            "operation".to_string(),
            "get_group_type_mappings_by_team_id".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, GroupTypeMappingRow>(
            r#"
            SELECT id, team_id, project_id, group_type, group_type_index,
                   name_singular, name_plural, default_columns, detail_dashboard_id, created_at
            FROM posthog_grouptypemapping
            WHERE team_id = $1
            "#,
        )
        .bind(team_id)
        .fetch_all(&*self.pool)
        .await?;

        Ok(rows.into_iter().map(GroupTypeMapping::from).collect())
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        team_ids: &[i64],
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        if team_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "get_group_type_mappings_by_team_ids".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, GroupTypeMappingRow>(
            r#"
            SELECT id, team_id, project_id, group_type, group_type_index,
                   name_singular, name_plural, default_columns, detail_dashboard_id, created_at
            FROM posthog_grouptypemapping
            WHERE team_id = ANY($1)
            "#,
        )
        .bind(team_ids)
        .fetch_all(&*self.pool)
        .await?;

        Ok(rows.into_iter().map(GroupTypeMapping::from).collect())
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        project_id: i64,
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        let labels = [(
            "operation".to_string(),
            "get_group_type_mappings_by_project_id".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, GroupTypeMappingRow>(
            r#"
            SELECT id, team_id, project_id, group_type, group_type_index,
                   name_singular, name_plural, default_columns, detail_dashboard_id, created_at
            FROM posthog_grouptypemapping
            WHERE project_id = $1
            "#,
        )
        .bind(project_id)
        .fetch_all(&*self.pool)
        .await?;

        Ok(rows.into_iter().map(GroupTypeMapping::from).collect())
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        project_ids: &[i64],
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        if project_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "get_group_type_mappings_by_project_ids".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, GroupTypeMappingRow>(
            r#"
            SELECT id, team_id, project_id, group_type, group_type_index,
                   name_singular, name_plural, default_columns, detail_dashboard_id, created_at
            FROM posthog_grouptypemapping
            WHERE project_id = ANY($1)
            "#,
        )
        .bind(project_ids)
        .fetch_all(&*self.pool)
        .await?;

        Ok(rows.into_iter().map(GroupTypeMapping::from).collect())
    }
}
