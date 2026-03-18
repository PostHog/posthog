use async_trait::async_trait;

use super::{ConsistencyLevel, PostgresStorage, DB_QUERY_DURATION, DB_ROWS_RETURNED};
use crate::storage::error::StorageResult;
use crate::storage::traits::GroupStorage;
use crate::storage::types::{Group, GroupIdentifier, GroupKey, GroupTypeMapping};

#[async_trait]
impl GroupStorage for PostgresStorage {
    async fn get_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Option<Group>> {
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            ("operation".to_string(), "get_group".to_string()),
            ("pool".to_string(), pool_label.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let row = sqlx::query_as!(
            Group,
            r#"
            SELECT id::bigint as "id!", team_id::bigint as "team_id!",
                   group_type_index, group_key, group_properties,
                   created_at,
                   properties_last_updated_at as "properties_last_updated_at?: serde_json::Value",
                   properties_last_operation as "properties_last_operation?: serde_json::Value",
                   version
            FROM posthog_group
            WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3
            "#,
            team_id as i32,
            group_type_index,
            group_key
        )
        .fetch_optional(&mut *conn)
        .await?;

        Ok(row)
    }

    async fn get_groups(
        &self,
        team_id: i64,
        identifiers: &[GroupIdentifier],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<Group>> {
        if identifiers.is_empty() {
            return Ok(Vec::new());
        }

        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            ("operation".to_string(), "get_groups".to_string()),
            ("pool".to_string(), pool_label.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let group_type_indexes: Vec<i32> = identifiers.iter().map(|i| i.group_type_index).collect();
        let group_keys: Vec<String> = identifiers.iter().map(|i| i.group_key.clone()).collect();

        let rows = sqlx::query_as!(
            Group,
            r#"
            SELECT g.id::bigint as "id!", g.team_id::bigint as "team_id!",
                   g.group_type_index, g.group_key, g.group_properties,
                   g.created_at,
                   g.properties_last_updated_at as "properties_last_updated_at?: serde_json::Value",
                   g.properties_last_operation as "properties_last_operation?: serde_json::Value",
                   g.version
            FROM posthog_group g
            INNER JOIN UNNEST($2::integer[], $3::text[]) AS t(group_type_index, group_key)
                ON g.group_type_index = t.group_type_index AND g.group_key = t.group_key
            WHERE g.team_id = $1
            "#,
            team_id as i32,
            &group_type_indexes,
            &group_keys
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[("operation".to_string(), "get_groups".to_string())],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_groups_batch(
        &self,
        keys: &[GroupKey],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<(GroupKey, Group)>> {
        if keys.is_empty() {
            return Ok(Vec::new());
        }

        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            ("operation".to_string(), "get_groups_batch".to_string()),
            ("pool".to_string(), pool_label.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let team_ids: Vec<i32> = keys.iter().map(|k| k.team_id as i32).collect();
        let group_type_indexes: Vec<i32> = keys.iter().map(|k| k.group_type_index).collect();
        let group_keys: Vec<String> = keys.iter().map(|k| k.group_key.clone()).collect();

        let groups = sqlx::query_as!(
            Group,
            r#"
            SELECT g.id::bigint as "id!", g.team_id::bigint as "team_id!",
                   g.group_type_index, g.group_key, g.group_properties,
                   g.created_at,
                   g.properties_last_updated_at as "properties_last_updated_at?: serde_json::Value",
                   g.properties_last_operation as "properties_last_operation?: serde_json::Value",
                   g.version
            FROM posthog_group g
            INNER JOIN UNNEST($1::integer[], $2::integer[], $3::text[]) AS t(team_id, group_type_index, group_key)
                ON g.team_id = t.team_id AND g.group_type_index = t.group_type_index AND g.group_key = t.group_key
            "#,
            &team_ids,
            &group_type_indexes,
            &group_keys
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[("operation".to_string(), "get_groups_batch".to_string())],
            groups.len() as f64,
        );

        Ok(groups
            .into_iter()
            .map(|g| {
                let key = GroupKey {
                    team_id: g.team_id,
                    group_type_index: g.group_type_index,
                    group_key: g.group_key.clone(),
                };
                (key, g)
            })
            .collect())
    }

    async fn get_group_type_mappings_by_team_id(
        &self,
        team_id: i64,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_group_type_mappings_by_team_id".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let rows = sqlx::query_as!(
            GroupTypeMapping,
            r#"
            SELECT id::bigint as "id!", team_id::bigint as "team_id!",
                   project_id as "project_id!",
                   group_type, group_type_index,
                   name_singular, name_plural, default_columns,
                   detail_dashboard_id::bigint, created_at
            FROM posthog_grouptypemapping
            WHERE team_id = $1
            "#,
            team_id as i32
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[(
                "operation".to_string(),
                "get_group_type_mappings_by_team_id".to_string(),
            )],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        team_ids: &[i64],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        if team_ids.is_empty() {
            return Ok(Vec::new());
        }

        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_group_type_mappings_by_team_ids".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let team_ids_i32: Vec<i32> = team_ids.iter().map(|&id| id as i32).collect();

        let rows = sqlx::query_as!(
            GroupTypeMapping,
            r#"
            SELECT id::bigint as "id!", team_id::bigint as "team_id!",
                   project_id as "project_id!",
                   group_type, group_type_index,
                   name_singular, name_plural, default_columns,
                   detail_dashboard_id::bigint, created_at
            FROM posthog_grouptypemapping
            WHERE team_id = ANY($1)
            "#,
            &team_ids_i32
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[(
                "operation".to_string(),
                "get_group_type_mappings_by_team_ids".to_string(),
            )],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        project_id: i64,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_group_type_mappings_by_project_id".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let rows = sqlx::query_as!(
            GroupTypeMapping,
            r#"
            SELECT id::bigint as "id!", team_id::bigint as "team_id!",
                   project_id as "project_id!",
                   group_type, group_type_index,
                   name_singular, name_plural, default_columns,
                   detail_dashboard_id::bigint, created_at
            FROM posthog_grouptypemapping
            WHERE project_id = $1
            "#,
            project_id
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[(
                "operation".to_string(),
                "get_group_type_mappings_by_project_id".to_string(),
            )],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        project_ids: &[i64],
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        if project_ids.is_empty() {
            return Ok(Vec::new());
        }

        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_group_type_mappings_by_project_ids".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let rows = sqlx::query_as!(
            GroupTypeMapping,
            r#"
            SELECT id::bigint as "id!", team_id::bigint as "team_id!",
                   project_id as "project_id!",
                   group_type, group_type_index,
                   name_singular, name_plural, default_columns,
                   detail_dashboard_id::bigint, created_at
            FROM posthog_grouptypemapping
            WHERE project_id = ANY($1)
            "#,
            project_ids
        )
        .fetch_all(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[(
                "operation".to_string(),
                "get_group_type_mappings_by_project_ids".to_string(),
            )],
            rows.len() as f64,
        );

        Ok(rows)
    }
}
