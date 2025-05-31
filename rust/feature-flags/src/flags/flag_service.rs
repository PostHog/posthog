use crate::{
    api::errors::FlagError,
    flags::flag_models::FeatureFlagList,
    metrics::consts::{
        DB_FLAG_READS_COUNTER, DB_TEAM_READS_COUNTER, FLAG_CACHE_ERRORS_COUNTER,
        FLAG_CACHE_HIT_COUNTER, TEAM_CACHE_ERRORS_COUNTER, TEAM_CACHE_HIT_COUNTER,
        TOKEN_VALIDATION_ERRORS_COUNTER,
    },
    team::team_models::Team,
};
use common_database::Client as DatabaseClient;
use common_metrics::inc;
use common_redis::Client as RedisClient;
use std::sync::Arc;

/// Service layer for handling feature flag operations
pub struct FlagService {
    redis_client: Arc<dyn RedisClient + Send + Sync>,
    pg_client: Arc<dyn DatabaseClient + Send + Sync>,
}

impl FlagService {
    pub fn new(
        redis_client: Arc<dyn RedisClient + Send + Sync>,
        pg_client: Arc<dyn DatabaseClient + Send + Sync>,
    ) -> Self {
        Self {
            redis_client,
            pg_client,
        }
    }

    /// Verifies the Project API token against the cache or the database.
    /// If the token is not found in the cache, it will be verified against the database,
    /// and the result will be cached in redis.
    pub async fn verify_token(&self, token: &str) -> Result<String, FlagError> {
        let (result, cache_hit) = match Team::from_redis(self.redis_client.clone(), token).await {
            Ok(_) => (Ok(token), true),
            Err(_) => {
                match Team::from_pg(self.pg_client.clone(), token).await {
                    Ok(team) => {
                        inc(DB_TEAM_READS_COUNTER, &[], 1);
                        // Token found in PostgreSQL, update Redis cache so that we can verify it from Redis next time
                        if let Err(e) =
                            Team::update_redis_cache(self.redis_client.clone(), &team).await
                        {
                            tracing::warn!("Failed to update Redis cache: {}", e);
                            inc(
                                TEAM_CACHE_ERRORS_COUNTER,
                                &[("reason".to_string(), "redis_update_failed".to_string())],
                                1,
                            );
                        }
                        (Ok(token), false)
                    }
                    Err(e) => {
                        tracing::error!("Token validation failed for token '{}': {:?}", token, e);
                        inc(
                            TOKEN_VALIDATION_ERRORS_COUNTER,
                            &[("reason".to_string(), "token_not_found".to_string())],
                            1,
                        );
                        (Err(FlagError::TokenValidationError), false)
                    }
                }
            }
        };

        inc(
            TEAM_CACHE_HIT_COUNTER,
            &[("cache_hit".to_string(), cache_hit.to_string())],
            1,
        );

        result.map(|token| token.to_string())
    }

    /// Fetches the team from the cache or the database.
    /// If the team is not found in the cache, it will be fetched from the database and stored in the cache.
    /// Returns the team if found, otherwise an error.
    pub async fn get_team_from_cache_or_pg(&self, token: &str) -> Result<Team, FlagError> {
        let (team_result, cache_hit) = match Team::from_redis(self.redis_client.clone(), token)
            .await
        {
            Ok(team) => (Ok(team), true),
            Err(_) => match Team::from_pg(self.pg_client.clone(), token).await {
                Ok(team) => {
                    inc(DB_TEAM_READS_COUNTER, &[], 1);
                    // If we have the team in postgres, but not redis, update redis so we're faster next time
                    if (Team::update_redis_cache(self.redis_client.clone(), &team).await).is_err() {
                        inc(
                            TEAM_CACHE_ERRORS_COUNTER,
                            &[("reason".to_string(), "redis_update_failed".to_string())],
                            1,
                        );
                    }
                    (Ok(team), false)
                }
                // TODO what kind of error should we return here?
                Err(e) => (Err(e), false),
            },
        };

        inc(
            TEAM_CACHE_HIT_COUNTER,
            &[("cache_hit".to_string(), cache_hit.to_string())],
            1,
        );

        team_result
    }

    /// Fetches the flags from the cache or the database. Returns a tuple containing
    /// the flags and a boolean indicating whether the flags came from cache.  Also, it
    /// tracks cache hits and misses for a given project_id.
    pub async fn get_flags_from_cache_or_pg(
        &self,
        project_id: i64,
    ) -> Result<FeatureFlagList, FlagError> {
        let (flags_result, cache_hit) =
            match FeatureFlagList::from_redis(self.redis_client.clone(), project_id).await {
                Ok(flags) => (Ok(flags), true),
                Err(_) => {
                    match FeatureFlagList::from_pg(self.pg_client.clone(), project_id).await {
                        Ok(flags) => {
                            inc(DB_FLAG_READS_COUNTER, &[], 1);
                            if (FeatureFlagList::update_flags_in_redis(
                                self.redis_client.clone(),
                                project_id,
                                &flags,
                            )
                            .await)
                                .is_err()
                            {
                                inc(
                                    FLAG_CACHE_ERRORS_COUNTER,
                                    &[("reason".to_string(), "redis_update_failed".to_string())],
                                    1,
                                );
                            }
                            (Ok(flags), false)
                        }
                        Err(e) => (Err(e), false),
                    }
                }
            };

        // Track cache hits and misses
        inc(
            FLAG_CACHE_HIT_COUNTER,
            &[("cache_hit".to_string(), cache_hit.to_string())],
            1,
        );

        flags_result
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use crate::{
        flags::flag_models::{
            FeatureFlag, FlagFilters, FlagPropertyGroup, TEAM_FLAGS_CACHE_PREFIX,
        },
        properties::property_models::{OperatorType, PropertyFilter},
        utils::test_utils::{insert_new_team_in_redis, setup_pg_reader_client, setup_redis_client},
    };

    use super::*;

    #[tokio::test]
    async fn test_verify_token() {
        let redis_client = setup_redis_client(None);
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let flag_service = FlagService::new(redis_client.clone(), pg_client.clone());

        // Test valid token in Redis
        let result = flag_service.verify_token(&team.api_token).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), team.api_token);

        // Test valid token in PostgreSQL (simulate Redis miss)
        // First, remove the team from Redis
        redis_client
            .del(format!("team:{}", team.api_token))
            .await
            .expect("Failed to remove team from Redis");

        let result = flag_service.verify_token(&team.api_token).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), team.api_token);

        // Test invalid token
        let result = flag_service.verify_token("invalid_token").await;
        assert!(matches!(result, Err(FlagError::TokenValidationError)));

        // Verify that the team was re-added to Redis after PostgreSQL hit
        let redis_team = Team::from_redis(redis_client.clone(), &team.api_token).await;
        assert!(redis_team.is_ok());
    }

    #[tokio::test]
    async fn test_get_team_from_cache_or_pg() {
        let redis_client = setup_redis_client(None);
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let flag_service = FlagService::new(redis_client.clone(), pg_client.clone());

        // Test fetching from Redis
        let result = flag_service
            .get_team_from_cache_or_pg(&team.api_token)
            .await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().id, team.id);

        // Test fetching from PostgreSQL (simulate Redis miss)
        // First, remove the team from Redis
        redis_client
            .del(format!("team:{}", team.api_token))
            .await
            .expect("Failed to remove team from Redis");

        let flag_service = FlagService::new(redis_client.clone(), pg_client.clone());

        let result = flag_service
            .get_team_from_cache_or_pg(&team.api_token)
            .await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().id, team.id);

        // Verify that the team was re-added to Redis
        let redis_team = Team::from_redis(redis_client.clone(), &team.api_token).await;
        assert!(redis_team.is_ok());
    }

    #[tokio::test]
    async fn test_get_flags_from_cache_or_pg() {
        let redis_client = setup_redis_client(None);
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        // Insert some mock flags into Redis
        let mock_flags = FeatureFlagList {
            flags: vec![
                FeatureFlag {
                    id: 1,
                    team_id: team.id,
                    name: Some("Beta Feature".to_string()),
                    key: "beta_feature".to_string(),
                    filters: FlagFilters {
                        groups: vec![FlagPropertyGroup {
                            properties: Some(vec![PropertyFilter {
                                key: "country".to_string(),
                                value: Some(json!("US")),
                                operator: Some(OperatorType::Exact),
                                prop_type: "person".to_string(),
                                group_type_index: None,
                                negation: None,
                            }]),
                            rollout_percentage: Some(50.0),
                            variant: None,
                        }],
                        multivariate: None,
                        aggregation_group_type_index: None,
                        payloads: None,
                        super_groups: None,
                        holdout_groups: None,
                    },
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: false,
                    version: Some(1),
                    creation_context: None,
                },
                FeatureFlag {
                    id: 2,
                    team_id: team.id,
                    name: Some("New User Interface".to_string()),
                    key: "new_ui".to_string(),
                    filters: FlagFilters {
                        groups: vec![],
                        multivariate: None,
                        aggregation_group_type_index: None,
                        payloads: None,
                        super_groups: None,
                        holdout_groups: None,
                    },
                    deleted: false,
                    active: false,
                    ensure_experience_continuity: false,
                    version: Some(1),
                    creation_context: None,
                },
                FeatureFlag {
                    id: 3,
                    team_id: team.id,
                    name: Some("Premium Feature".to_string()),
                    key: "premium_feature".to_string(),
                    filters: FlagFilters {
                        groups: vec![FlagPropertyGroup {
                            properties: Some(vec![PropertyFilter {
                                key: "is_premium".to_string(),
                                value: Some(json!(true)),
                                operator: Some(OperatorType::Exact),
                                prop_type: "person".to_string(),
                                group_type_index: None,
                                negation: None,
                            }]),
                            rollout_percentage: Some(100.0),
                            variant: None,
                        }],
                        multivariate: None,
                        aggregation_group_type_index: None,
                        payloads: None,
                        super_groups: None,
                        holdout_groups: None,
                    },
                    deleted: false,
                    active: true,
                    ensure_experience_continuity: false,
                    version: Some(1),
                    creation_context: None,
                },
            ],
        };

        FeatureFlagList::update_flags_in_redis(redis_client.clone(), team.project_id, &mock_flags)
            .await
            .expect("Failed to insert mock flags in Redis");

        let flag_service = FlagService::new(redis_client.clone(), pg_client.clone());

        // Test fetching from Redis
        let result = flag_service
            .get_flags_from_cache_or_pg(team.project_id)
            .await;
        assert!(result.is_ok());
        let fetched_flags = result.unwrap();
        assert_eq!(fetched_flags.flags.len(), mock_flags.flags.len());

        // Verify the contents of the fetched flags
        let beta_feature = fetched_flags
            .flags
            .iter()
            .find(|f| f.key == "beta_feature")
            .unwrap();
        assert!(beta_feature.active);
        assert_eq!(
            beta_feature.filters.groups[0].rollout_percentage,
            Some(50.0)
        );
        assert_eq!(
            beta_feature.filters.groups[0].properties.as_ref().unwrap()[0].key,
            "country"
        );

        let new_ui = fetched_flags
            .flags
            .iter()
            .find(|f| f.key == "new_ui")
            .unwrap();
        assert!(!new_ui.active);
        assert!(new_ui.filters.groups.is_empty());

        let premium_feature = fetched_flags
            .flags
            .iter()
            .find(|f| f.key == "premium_feature")
            .unwrap();
        assert!(premium_feature.active);
        assert_eq!(
            premium_feature.filters.groups[0].rollout_percentage,
            Some(100.0)
        );
        assert_eq!(
            premium_feature.filters.groups[0]
                .properties
                .as_ref()
                .unwrap()[0]
                .key,
            "is_premium"
        );

        // Test fetching from PostgreSQL (simulate Redis miss)
        // First, remove the flags from Redis
        redis_client
            .del(format!("{}:{}", TEAM_FLAGS_CACHE_PREFIX, team.id))
            .await
            .expect("Failed to remove flags from Redis");

        let result = flag_service
            .get_flags_from_cache_or_pg(team.project_id)
            .await;
        assert!(result.is_ok());
        // Verify that the flags were re-added to Redis
        let redis_flags = FeatureFlagList::from_redis(redis_client.clone(), team.project_id).await;
        assert!(redis_flags.is_ok());
        assert_eq!(redis_flags.unwrap().flags.len(), mock_flags.flags.len());
    }
}
