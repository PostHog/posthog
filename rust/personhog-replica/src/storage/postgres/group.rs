use async_trait::async_trait;
use sqlx::FromRow;

use super::{PostgresStorage, DB_QUERY_DURATION};
use crate::storage::error::StorageResult;
use crate::storage::traits::GroupStorage;
use crate::storage::types::{Group, GroupIdentifier, GroupKey, GroupTypeMapping};

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

#[async_trait]
impl GroupStorage for PostgresStorage {
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
        .fetch_optional(&self.pool)
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
        .fetch_all(&self.pool)
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
        .fetch_all(&self.pool)
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
        .fetch_all(&self.pool)
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
        .fetch_all(&self.pool)
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
        .fetch_all(&self.pool)
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
        .fetch_all(&self.pool)
        .await?;

        Ok(rows.into_iter().map(GroupTypeMapping::from).collect())
    }
}
