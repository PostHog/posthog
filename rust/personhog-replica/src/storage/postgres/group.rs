use async_trait::async_trait;
use chrono::{DateTime, Utc};

use personhog_common::grpc::current_client_name;

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
        let client = current_client_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            ("operation".to_string(), "get_group".to_string()),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
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

        let client = current_client_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            ("operation".to_string(), "get_groups".to_string()),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
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
            &[
                ("operation".to_string(), "get_groups".to_string()),
                ("client".to_string(), client.to_string()),
            ],
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

        let client = current_client_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            ("operation".to_string(), "get_groups_batch".to_string()),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
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
            &[
                ("operation".to_string(), "get_groups_batch".to_string()),
                ("client".to_string(), client.to_string()),
            ],
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
        let client = current_client_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_group_type_mappings_by_team_id".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
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
            &[
                (
                    "operation".to_string(),
                    "get_group_type_mappings_by_team_id".to_string(),
                ),
                ("client".to_string(), client.to_string()),
            ],
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

        let client = current_client_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_group_type_mappings_by_team_ids".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
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
            &[
                (
                    "operation".to_string(),
                    "get_group_type_mappings_by_team_ids".to_string(),
                ),
                ("client".to_string(), client.to_string()),
            ],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        project_id: i64,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<GroupTypeMapping>> {
        let client = current_client_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_group_type_mappings_by_project_id".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
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
            &[
                (
                    "operation".to_string(),
                    "get_group_type_mappings_by_project_id".to_string(),
                ),
                ("client".to_string(), client.to_string()),
            ],
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

        let client = current_client_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_group_type_mappings_by_project_ids".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
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
            &[
                (
                    "operation".to_string(),
                    "get_group_type_mappings_by_project_ids".to_string(),
                ),
                ("client".to_string(), client.to_string()),
            ],
            rows.len() as f64,
        );

        Ok(rows)
    }

    async fn get_group_type_mapping_by_dashboard_id(
        &self,
        team_id: i64,
        dashboard_id: i64,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Option<GroupTypeMapping>> {
        let client = current_client_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_group_type_mapping_by_dashboard_id".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let pool = self.pool_for_consistency(consistency);
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        let row = sqlx::query_as!(
            GroupTypeMapping,
            r#"
            SELECT id::bigint as "id!", team_id::bigint as "team_id!",
                   project_id as "project_id!",
                   group_type, group_type_index,
                   name_singular, name_plural, default_columns,
                   detail_dashboard_id::bigint, created_at
            FROM posthog_grouptypemapping
            WHERE team_id = $1 AND detail_dashboard_id = $2
            ORDER BY id
            LIMIT 1
            "#,
            team_id as i32,
            dashboard_id as i32
        )
        .fetch_optional(&mut *conn)
        .await?;

        Ok(row)
    }

    // ============================================================
    // Group writes
    // ============================================================

    async fn create_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
        group_properties: &serde_json::Value,
        created_at: DateTime<Utc>,
    ) -> StorageResult<Group> {
        let client = current_client_name();
        let labels = [
            ("operation".to_string(), "create_group".to_string()),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        let row = sqlx::query_as!(
            Group,
            r#"
            INSERT INTO posthog_group (team_id, group_type_index, group_key, group_properties, created_at, properties_last_updated_at, properties_last_operation, version)
            VALUES ($1, $2, $3, $4, $5, '{}'::jsonb, '{}'::jsonb, 0)
            RETURNING id::bigint as "id!", team_id::bigint as "team_id!",
                      group_type_index, group_key, group_properties,
                      created_at,
                      properties_last_updated_at as "properties_last_updated_at?: serde_json::Value",
                      properties_last_operation as "properties_last_operation?: serde_json::Value",
                      version
            "#,
            team_id as i32,
            group_type_index,
            group_key,
            group_properties,
            created_at
        )
        .fetch_one(&mut *conn)
        .await?;

        Ok(row)
    }

    async fn update_group(
        &self,
        team_id: i64,
        group_type_index: i32,
        group_key: &str,
        update_mask: &[String],
        group_properties: Option<&serde_json::Value>,
        properties_last_updated_at: Option<&serde_json::Value>,
        properties_last_operation: Option<&serde_json::Value>,
        created_at: Option<chrono::DateTime<chrono::Utc>>,
    ) -> StorageResult<Option<Group>> {
        let client = current_client_name();
        let labels = [
            ("operation".to_string(), "update_group".to_string()),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        let mask_set: std::collections::HashSet<&str> =
            update_mask.iter().map(|s| s.as_str()).collect();

        let row = sqlx::query_as!(
            Group,
            r#"
            UPDATE posthog_group
            SET group_properties = CASE WHEN $4 THEN $5 ELSE group_properties END,
                properties_last_updated_at = CASE WHEN $6 THEN $7 ELSE properties_last_updated_at END,
                properties_last_operation = CASE WHEN $8 THEN $9 ELSE properties_last_operation END,
                created_at = CASE WHEN $10 THEN $11 ELSE created_at END,
                version = version + 1
            WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3
            RETURNING id::bigint as "id!", team_id::bigint as "team_id!",
                      group_type_index, group_key, group_properties,
                      created_at,
                      properties_last_updated_at as "properties_last_updated_at?: serde_json::Value",
                      properties_last_operation as "properties_last_operation?: serde_json::Value",
                      version
            "#,
            team_id as i32,
            group_type_index,
            group_key,
            mask_set.contains("group_properties"),
            group_properties,
            mask_set.contains("properties_last_updated_at"),
            properties_last_updated_at,
            mask_set.contains("properties_last_operation"),
            properties_last_operation,
            mask_set.contains("created_at"),
            created_at,
        )
        .fetch_optional(&mut *conn)
        .await?;

        Ok(row)
    }

    async fn delete_groups_batch_for_team(
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
                "delete_groups_batch_for_team".to_string(),
            ),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        let result = sqlx::query!(
            r#"
            DELETE FROM posthog_group
            WHERE id IN (
                SELECT id FROM posthog_group
                WHERE team_id = $1
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            "#,
            team_id as i32,
            batch_size
        )
        .execute(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "delete_groups_batch_for_team".to_string(),
                ),
                ("pool".to_string(), "primary".to_string()),
                ("client".to_string(), client.to_string()),
            ],
            result.rows_affected() as f64,
        );

        Ok(result.rows_affected() as i64)
    }

    // ============================================================
    // Group type mapping writes
    // ============================================================

    async fn update_group_type_mapping(
        &self,
        project_id: i64,
        group_type_index: i32,
        update_mask: &[String],
        name_singular: Option<&str>,
        name_plural: Option<&str>,
        detail_dashboard_id: Option<i64>,
        default_columns: Option<&[String]>,
    ) -> StorageResult<Option<GroupTypeMapping>> {
        let client = current_client_name();
        let labels = [
            (
                "operation".to_string(),
                "update_group_type_mapping".to_string(),
            ),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        if update_mask.is_empty() {
            return sqlx::query_as!(
                GroupTypeMapping,
                r#"
                SELECT id::bigint as "id!", team_id::bigint as "team_id!",
                       project_id as "project_id!",
                       group_type, group_type_index,
                       name_singular, name_plural, default_columns,
                       detail_dashboard_id::bigint, created_at
                FROM posthog_grouptypemapping
                WHERE project_id = $1 AND group_type_index = $2
                "#,
                project_id,
                group_type_index
            )
            .fetch_optional(&mut *conn)
            .await
            .map_err(Into::into);
        }

        let mask_set: std::collections::HashSet<&str> =
            update_mask.iter().map(|s| s.as_str()).collect();

        let row = sqlx::query_as!(
            GroupTypeMapping,
            r#"
            UPDATE posthog_grouptypemapping
            SET name_singular = CASE WHEN $3 THEN $4 ELSE name_singular END,
                name_plural = CASE WHEN $5 THEN $6 ELSE name_plural END,
                detail_dashboard_id = CASE WHEN $7 THEN $8 ELSE detail_dashboard_id END,
                default_columns = CASE WHEN $9 THEN $10 ELSE default_columns END
            WHERE project_id = $1 AND group_type_index = $2
            RETURNING id::bigint as "id!", team_id::bigint as "team_id!",
                      project_id as "project_id!",
                      group_type, group_type_index,
                      name_singular, name_plural, default_columns,
                      detail_dashboard_id::bigint, created_at
            "#,
            project_id,
            group_type_index,
            mask_set.contains("name_singular"),
            name_singular,
            mask_set.contains("name_plural"),
            name_plural,
            mask_set.contains("detail_dashboard_id"),
            detail_dashboard_id.map(|id| id as i32),
            mask_set.contains("default_columns"),
            default_columns,
        )
        .fetch_optional(&mut *conn)
        .await?;

        Ok(row)
    }

    async fn delete_group_type_mapping(
        &self,
        project_id: i64,
        group_type_index: i32,
    ) -> StorageResult<bool> {
        let client = current_client_name();
        let labels = [
            (
                "operation".to_string(),
                "delete_group_type_mapping".to_string(),
            ),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        let result = sqlx::query!(
            r#"
            DELETE FROM posthog_grouptypemapping
            WHERE project_id = $1 AND group_type_index = $2
            "#,
            project_id,
            group_type_index
        )
        .execute(&mut *conn)
        .await?;

        Ok(result.rows_affected() > 0)
    }

    async fn delete_group_type_mappings_batch_for_team(
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
                "delete_group_type_mappings_batch_for_team".to_string(),
            ),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;

        let result = sqlx::query!(
            r#"
            DELETE FROM posthog_grouptypemapping
            WHERE id IN (
                SELECT id FROM posthog_grouptypemapping
                WHERE team_id = $1
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            "#,
            team_id as i32,
            batch_size
        )
        .execute(&mut *conn)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "delete_group_type_mappings_batch_for_team".to_string(),
                ),
                ("pool".to_string(), "primary".to_string()),
                ("client".to_string(), client.to_string()),
            ],
            result.rows_affected() as f64,
        );

        Ok(result.rows_affected() as i64)
    }
}
