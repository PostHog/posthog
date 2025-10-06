use crate::{
    api::errors::FlagError,
    team::team_models::{Team, TEAM_TOKEN_CACHE_PREFIX},
};
use common_database::PostgresReader;
use common_redis::Client as RedisClient;
use std::sync::Arc;

impl Team {
    /// Validates a token, and returns a team if it exists.
    pub async fn from_redis(
        client: Arc<dyn RedisClient + Send + Sync>,
        token: &str,
    ) -> Result<Team, FlagError> {
        tracing::debug!(
            "Attempting to read team from Redis at key '{TEAM_TOKEN_CACHE_PREFIX}{token}'"
        );

        // NB: if this lookup fails, we fall back to the database before returning an error
        let serialized_team = client
            .get(format!("{TEAM_TOKEN_CACHE_PREFIX}{token}"))
            .await?;

        // TODO: Consider an LRU cache for teams as well, with small TTL to skip redis/pg lookups
        let mut team: Team = serde_json::from_str(&serialized_team).map_err(|e| {
            tracing::error!("failed to parse data to team for token {token}: {e}");
            FlagError::RedisDataParsingError
        })?;
        if team.project_id == 0 {
            // If `project_id` is 0, this means the payload is from before December 2024, which we correct for here
            team.project_id = team.id as i64;
        }

        tracing::debug!(
            "Successfully read team {} from Redis at key '{}{}'",
            team.id,
            TEAM_TOKEN_CACHE_PREFIX,
            token
        );

        Ok(team)
    }

    pub async fn update_redis_cache(
        client: Arc<dyn RedisClient + Send + Sync>,
        team: &Team,
    ) -> Result<(), FlagError> {
        let serialized_team = serde_json::to_string(&team).map_err(|e| {
            tracing::error!(
                "Failed to serialize team {} (token {}): {}",
                team.id,
                team.api_token,
                e
            );
            FlagError::RedisDataParsingError
        })?;

        tracing::info!(
            "Writing team to Redis at key '{}{}': team_id={}",
            TEAM_TOKEN_CACHE_PREFIX,
            team.api_token,
            team.id
        );

        client
            .set(
                format!("{TEAM_TOKEN_CACHE_PREFIX}{}", team.api_token),
                serialized_team,
            )
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to update Redis cache for team {} (token {}): {}",
                    team.id,
                    team.api_token,
                    e
                );
                FlagError::CacheUpdateError
            })?;

        Ok(())
    }

    pub async fn from_pg(client: PostgresReader, token: &str) -> Result<Team, FlagError> {
        let mut conn = client.get_connection().await?;

        let query = "SELECT 
            id, 
            uuid,
            name, 
            api_token, 
            project_id, 
            cookieless_server_hash_mode, 
            timezone,
            autocapture_opt_out,
            autocapture_exceptions_opt_in,
            autocapture_web_vitals_opt_in,
            capture_performance_opt_in,
            capture_console_log_opt_in,
            session_recording_opt_in,
            inject_web_apps,
            surveys_opt_in,
            heatmaps_opt_in,
            capture_dead_clicks,
            flags_persistence_default,
            session_recording_sample_rate,
            session_recording_minimum_duration_milliseconds,
            autocapture_web_vitals_allowed_metrics,
            autocapture_exceptions_errors_to_ignore,
            session_recording_linked_flag,
            session_recording_network_payload_capture_config,
            session_recording_masking_config,
            session_replay_config,
            survey_config,
            session_recording_url_trigger_config,
            session_recording_url_blocklist_config,
            session_recording_event_trigger_config,
            session_recording_trigger_match_type_config,
            recording_domains
        FROM posthog_team 
        WHERE api_token = $1";
        let row = sqlx::query_as::<_, Team>(query)
            .bind(token)
            .fetch_one(&mut *conn)
            .await?;

        Ok(row)
    }
}

#[cfg(test)]
mod tests {
    use rand::Rng;
    use redis::AsyncCommands;
    use uuid::Uuid;

    use super::*;
    use crate::utils::test_utils::{
        insert_new_team_in_redis, random_string, setup_redis_client, TestContext,
    };

    #[tokio::test]
    async fn test_fetch_team_from_redis() {
        let client = setup_redis_client(None).await;

        let team = insert_new_team_in_redis(client.clone())
            .await
            .expect("Failed to insert team in redis");

        let target_token = team.api_token;

        let team_from_redis = Team::from_redis(client.clone(), &target_token)
            .await
            .unwrap();
        assert_eq!(team_from_redis.api_token, target_token);
        assert_eq!(team_from_redis.id, team.id);
        assert_eq!(team_from_redis.project_id, team.project_id);
    }

    #[tokio::test]
    async fn test_fetch_invalid_team_from_redis() {
        let client = setup_redis_client(None).await;

        match Team::from_redis(client.clone(), "banana").await {
            Err(FlagError::TokenValidationError) => (),
            _ => panic!("Expected TokenValidationError"),
        };
    }

    #[tokio::test]
    #[should_panic(expected = "Failed to create redis client")]
    async fn test_cant_connect_to_redis_error_is_not_token_validation_error() {
        // Test that client creation fails when Redis is unavailable
        setup_redis_client(Some("redis://localhost:1111/".to_string())).await;
    }

    #[tokio::test]
    async fn test_corrupted_data_in_redis_is_handled() {
        let id = rand::thread_rng().gen_range(1..10_000_000);
        let token = random_string("phc_", 12);
        let team = Team {
            id,
            project_id: i64::from(id) - 1,
            name: "team".to_string(),
            api_token: token,
            cookieless_server_hash_mode: 0,
            timezone: "UTC".to_string(),
            ..Default::default()
        };
        let serialized_team = serde_json::to_string(&team).expect("Failed to serialise team");

        // manually insert non-pickled data in redis
        let client =
            redis::Client::open("redis://localhost:6379/").expect("Failed to create redis client");
        let mut conn = client
            .get_async_connection()
            .await
            .expect("Failed to get redis connection");
        conn.set::<String, String, ()>(
            format!("{}{}", TEAM_TOKEN_CACHE_PREFIX, team.api_token.clone()),
            serialized_team,
        )
        .await
        .expect("Failed to write data to redis");

        // now get client connection for data
        let client = setup_redis_client(None).await;

        match Team::from_redis(client.clone(), team.api_token.as_str()).await {
            Err(FlagError::RedisDataParsingError) => (),
            Err(other) => panic!("Expected DataParsingError, got {other:?}"),
            Ok(_) => panic!("Expected DataParsingError"),
        };
    }

    #[tokio::test]
    async fn test_fetch_team_from_before_project_id_from_redis() {
        let client = setup_redis_client(None).await;
        let target_token = "phc_123456789012".to_string();
        // A payload form before December 2025, it's missing `project_id`
        let test_team = Team {
            id: 343,
            name: "team".to_string(),
            api_token: target_token.clone(),
            project_id: 0,
            uuid: Uuid::nil(),
            session_recording_opt_in: false,
            cookieless_server_hash_mode: 0,
            timezone: "UTC".to_string(),
            ..Default::default()
        };

        let serialized_team = serde_json::to_string(&test_team).expect("Failed to serialize team");
        tracing::info!("Inserting test team payload: {serialized_team}");
        client
            .set(
                format!("{TEAM_TOKEN_CACHE_PREFIX}{target_token}"),
                serialized_team,
            )
            .await
            .expect("Failed to write data to redis");

        let team_from_redis = Team::from_redis(client.clone(), target_token.as_str())
            .await
            .expect("Failed to fetch team from redis");

        assert_eq!(team_from_redis.api_token, target_token);
        assert_eq!(team_from_redis.id, 343);
        assert_eq!(team_from_redis.project_id, 343); // Same as `id`
        assert_eq!(team_from_redis.cookieless_server_hash_mode, 0);
    }

    #[tokio::test]
    async fn test_fetch_team_from_pg() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        let target_token = team.api_token;

        let team_from_pg = Team::from_pg(context.non_persons_reader.clone(), target_token.as_str())
            .await
            .expect("Failed to fetch team from pg");

        assert_eq!(team_from_pg.api_token, target_token);
        assert_eq!(team_from_pg.id, team.id);
        assert_eq!(team_from_pg.name, team.name);
    }

    #[tokio::test]
    async fn test_fetch_team_from_pg_with_invalid_token() {
        // TODO: Figure out a way such that `run_database_migrations` is called only once, and already called
        // before running these tests.

        let context = TestContext::new(None).await;
        let target_token = "xxxx".to_string();

        match Team::from_pg(context.non_persons_reader.clone(), target_token.as_str()).await {
            Err(FlagError::RowNotFound) => (),
            _ => panic!("Expected RowNotFound"),
        };
    }

    #[tokio::test]
    async fn test_fetch_team_with_null_array_elements_from_pg() {
        let context = TestContext::new(None).await;

        // Insert a team with NULL elements in the array
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        // Manually update the team to have NULL elements in session_recording_event_trigger_config
        let mut conn = context
            .non_persons_reader
            .get_connection()
            .await
            .expect("Failed to get connection");

        // Update with an array containing NULL elements: {NULL, 'valid_event', NULL, 'another_event'}
        sqlx::query(
            "UPDATE posthog_team SET session_recording_event_trigger_config = $1 WHERE id = $2",
        )
        .bind(vec![
            None,
            Some("valid_event".to_string()),
            None,
            Some("another_event".to_string()),
        ])
        .bind(team.id)
        .execute(&mut *conn)
        .await
        .expect("Failed to update team with NULL array elements");

        // Now fetch the team and verify it deserializes correctly
        let team_from_pg = Team::from_pg(context.non_persons_reader.clone(), &team.api_token)
            .await
            .expect("Failed to fetch team with NULL array elements from pg");

        // Verify the field was deserialized correctly
        assert!(team_from_pg
            .session_recording_event_trigger_config
            .is_some());
        let config = team_from_pg.session_recording_event_trigger_config.unwrap();
        assert_eq!(config.len(), 4);
        assert_eq!(config[0], None);
        assert_eq!(config[1], Some("valid_event".to_string()));
        assert_eq!(config[2], None);
        assert_eq!(config[3], Some("another_event".to_string()));
    }
}
