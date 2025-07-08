use std::sync::Arc;
use tracing;

use crate::api::errors::FlagError;
use crate::flags::flag_models::{
    FeatureFlag, FeatureFlagList, FeatureFlagRow, TEAM_FLAGS_CACHE_PREFIX,
};
use common_database::PostgresReader;
use common_redis::Client as RedisClient;

impl FeatureFlagList {
    pub fn new(flags: Vec<FeatureFlag>) -> Self {
        Self { flags }
    }

    /// Returns feature flags from redis given a project_id
    pub async fn from_redis(
        client: Arc<dyn RedisClient + Send + Sync>,
        project_id: i64,
    ) -> Result<FeatureFlagList, FlagError> {
        tracing::debug!(
            "Attempting to read flags from Redis at key '{}{}'",
            TEAM_FLAGS_CACHE_PREFIX,
            project_id
        );

        let serialized_flags = client
            .get(format!("{TEAM_FLAGS_CACHE_PREFIX}{}", project_id))
            .await?;

        let flags_list: Vec<FeatureFlag> =
            serde_json::from_str(&serialized_flags).map_err(|e| {
                tracing::error!(
                    "failed to parse data to flags list for project {}: {}",
                    project_id,
                    e
                );
                FlagError::RedisDataParsingError
            })?;

        tracing::debug!(
            "Successfully read {} flags from Redis at key '{}{}'",
            flags_list.len(),
            TEAM_FLAGS_CACHE_PREFIX,
            project_id
        );

        Ok(FeatureFlagList { flags: flags_list })
    }

    /// Returns feature flags from postgres given a project_id
    pub async fn from_pg(
        client: PostgresReader,
        project_id: i64,
    ) -> Result<FeatureFlagList, FlagError> {
        let mut conn = client.get_connection().await.map_err(|e| {
            tracing::error!(
                "Failed to get database connection for project {}: {}",
                project_id,
                e
            );
            FlagError::DatabaseUnavailable
        })?;

        let query = r#"
            SELECT f.id,
                  f.team_id,
                  f.name,
                  f.key,
                  f.filters,
                  f.deleted,
                  f.active,
                  f.ensure_experience_continuity,
                  f.version
              FROM posthog_featureflag AS f
              JOIN posthog_team AS t ON (f.team_id = t.id)
            WHERE t.project_id = $1
              AND f.deleted = false
              AND f.active = true
        "#;
        let flags_row = sqlx::query_as::<_, FeatureFlagRow>(query)
            .bind(project_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to fetch feature flags from database for project {}: {}",
                    project_id,
                    e
                );
                FlagError::Internal(format!("Database query error: {}", e))
            })?;

        let flags_list = flags_row
            .into_iter()
            .map(|row| {
                let filters = serde_json::from_value(row.filters).map_err(|e| {
                    tracing::error!(
                        "Failed to deserialize filters for flag {} in project {} (team {}): {}",
                        row.key,
                        project_id,
                        row.team_id,
                        e
                    );
                    FlagError::DeserializeFiltersError
                })?;

                Ok(FeatureFlag {
                    id: row.id,
                    team_id: row.team_id,
                    name: row.name,
                    key: row.key,
                    filters,
                    deleted: row.deleted,
                    active: row.active,
                    ensure_experience_continuity: row.ensure_experience_continuity,
                    version: row.version,
                })
            })
            .collect::<Result<Vec<FeatureFlag>, FlagError>>()?;

        Ok(FeatureFlagList { flags: flags_list })
    }

    pub async fn update_flags_in_redis(
        client: Arc<dyn RedisClient + Send + Sync>,
        project_id: i64,
        flags: &FeatureFlagList,
    ) -> Result<(), FlagError> {
        let payload = serde_json::to_string(&flags.flags).map_err(|e| {
            tracing::error!(
                "Failed to serialize {} flags for project {}: {}",
                flags.flags.len(),
                project_id,
                e
            );
            FlagError::RedisDataParsingError
        })?;

        tracing::info!(
            "Writing flags to Redis at key '{}{}': {} flags",
            TEAM_FLAGS_CACHE_PREFIX,
            project_id,
            flags.flags.len()
        );

        client
            .set(format!("{TEAM_FLAGS_CACHE_PREFIX}{}", project_id), payload)
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to update Redis cache for project {}: {}",
                    project_id,
                    e
                );
                FlagError::CacheUpdateError
            })?;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::{
        insert_flag_for_team_in_pg, insert_flags_for_team_in_redis, insert_new_team_in_pg,
        insert_new_team_in_redis, setup_invalid_pg_client, setup_pg_reader_client,
        setup_redis_client,
    };
    use rand::Rng;

    #[tokio::test]
    async fn test_fetch_flags_from_redis() {
        let redis_client = setup_redis_client(None).await;

        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert team");

        insert_flags_for_team_in_redis(redis_client.clone(), team.id, team.project_id, None)
            .await
            .expect("Failed to insert flags");

        let flags_from_redis = FeatureFlagList::from_redis(redis_client.clone(), team.project_id)
            .await
            .expect("Failed to fetch flags from redis");
        assert_eq!(flags_from_redis.flags.len(), 1);
        let flag = flags_from_redis
            .flags
            .first()
            .expect("Empty flags in redis");
        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].properties.as_ref().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn test_fetch_invalid_team_from_redis() {
        let redis_client = setup_redis_client(None).await;

        match FeatureFlagList::from_redis(redis_client.clone(), 1234).await {
            Err(FlagError::TokenValidationError) => {
                // Expected error
            }
            _ => panic!("Expected TokenValidationError"),
        }
    }

    #[tokio::test]
    #[should_panic(expected = "Failed to create redis client")]
    async fn test_cant_connect_to_redis_error_is_not_token_validation_error() {
        // Test that client creation fails when Redis is unavailable
        setup_redis_client(Some("redis://localhost:1111/".to_string())).await;
    }

    #[tokio::test]
    async fn test_fetch_flags_from_pg() {
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
            .await
            .expect("Failed to insert team");

        insert_flag_for_team_in_pg(reader.clone(), team.id, None)
            .await
            .expect("Failed to insert flag");

        let flags_from_pg = FeatureFlagList::from_pg(reader.clone(), team.project_id)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.flags.len(), 1);
        let flag = flags_from_pg.flags.first().expect("Flags should be in pg");
        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].properties.as_ref().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn test_fetch_empty_team_from_pg() {
        let reader = setup_pg_reader_client(None).await;

        let FeatureFlagList { flags } = FeatureFlagList::from_pg(reader.clone(), 1234)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags.len(), 0);
    }

    #[tokio::test]
    async fn test_fetch_nonexistent_team_from_pg() {
        let reader = setup_pg_reader_client(None).await;

        match FeatureFlagList::from_pg(reader.clone(), -1).await {
            Ok(flags) => assert_eq!(flags.flags.len(), 0),
            Err(err) => panic!("Expected empty result, got error: {:?}", err),
        }
    }

    #[tokio::test]
    async fn test_fetch_flags_db_connection_failure() {
        let invalid_client = setup_invalid_pg_client().await;

        match FeatureFlagList::from_pg(invalid_client, 1).await {
            Ok(_) => panic!("Expected error for invalid database connection"),
            Err(FlagError::DatabaseUnavailable) => {
                // Expected error
            }
            Err(e) => panic!("Unexpected error: {:?}", e),
        }
    }

    #[tokio::test]
    async fn test_fetch_multiple_flags_from_pg() {
        let reader = setup_pg_reader_client(None).await;

        let team = insert_new_team_in_pg(reader.clone(), None)
            .await
            .expect("Failed to insert team");

        let random_id_1 = rand::thread_rng().gen_range(0..10_000_000);
        let random_id_2 = rand::thread_rng().gen_range(0..10_000_000);

        let flag1 = FeatureFlagRow {
            id: random_id_1,
            team_id: team.id,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: false,
            version: Some(1),
        };

        let flag2 = FeatureFlagRow {
            id: random_id_2,
            team_id: team.id,
            name: Some("Test Flag 2".to_string()),
            key: "test_flag_2".to_string(),
            filters: serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: false,
            version: Some(1),
        };

        // Insert multiple flags for the team
        insert_flag_for_team_in_pg(reader.clone(), team.id, Some(flag1))
            .await
            .expect("Failed to insert flags");

        insert_flag_for_team_in_pg(reader.clone(), team.id, Some(flag2))
            .await
            .expect("Failed to insert flags");

        let flags_from_pg = FeatureFlagList::from_pg(reader.clone(), team.project_id)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.flags.len(), 2);
        for flag in &flags_from_pg.flags {
            assert_eq!(flag.team_id, team.id);
        }
    }
}
