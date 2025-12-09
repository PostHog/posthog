use crate::{
    api::errors::FlagError,
    database::get_connection_with_metrics,
    team::team_models::{Team, TEAM_TOKEN_CACHE_PREFIX},
};
use common_database::PostgresReader;
use common_redis::Client as RedisClient;
use std::{future::Future, sync::Arc};
use tracing::{debug, warn};

/// Fetches a team from Redis cache with PostgreSQL fallback
///
/// This helper consolidates the common pattern of:
/// 1. Try Redis cache first
/// 2. On cache miss, fetch from PostgreSQL using the provided lookup function
/// 3. Update Redis cache on successful database fetch
/// 4. Return the team
///
/// # Arguments
/// * `redis_client` - Redis client (ReadWriteClient automatically routes reads to replica, writes to primary)
/// * `token` - Token to use for cache key lookup
/// * `db_lookup` - Async function to fetch team from PostgreSQL on cache miss
/// * `cache_ttl_seconds` - Optional TTL for Redis cache entries in seconds
pub async fn fetch_team_from_redis_with_fallback<F, Fut>(
    redis_client: Arc<dyn RedisClient + Send + Sync>,
    token: &str,
    cache_ttl_seconds: Option<u64>,
    db_lookup: F,
) -> Result<Team, FlagError>
where
    F: FnOnce() -> Fut,
    Fut: Future<Output = Result<Team, FlagError>>,
{
    // Try to get team from cache first (ReadWriteClient routes reads to replica)
    match Team::from_redis(redis_client.clone(), token).await {
        Ok(team) => {
            debug!(team_id = team.id, "Found team in Redis cache");
            Ok(team)
        }
        Err(e) => {
            debug!(error = %e, "Team not found in Redis cache");
            // Fallback to database using provided lookup function
            match db_lookup().await {
                Ok(team) => {
                    debug!(team_id = team.id, "Found team in PostgreSQL");
                    // Update Redis cache for next time (ReadWriteClient routes writes to primary)
                    if let Err(e) =
                        Team::update_redis_cache(redis_client, &team, cache_ttl_seconds).await
                    {
                        warn!(team_id = team.id, error = %e, "Failed to update Redis cache");
                    }
                    Ok(team)
                }
                Err(e) => {
                    warn!(error = %e, "Team not found in PostgreSQL");
                    Err(e)
                }
            }
        }
    }
}

/// SQL fragment for selecting all Team columns
const TEAM_COLUMNS: &str = "
    id,
    uuid,
    name,
    api_token,
    organization_id,
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
    extra_settings,
    session_recording_url_trigger_config,
    session_recording_url_blocklist_config,
    session_recording_event_trigger_config,
    session_recording_trigger_match_type_config,
    recording_domains
";

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
        let team: Team = serde_json::from_str(&serialized_team).map_err(|e| {
            tracing::error!("failed to parse data to team for token {token}: {e}");
            FlagError::RedisDataParsingError
        })?;

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
        ttl_seconds: Option<u64>,
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

        let cache_key = format!("{TEAM_TOKEN_CACHE_PREFIX}{}", team.api_token);

        match ttl_seconds {
            Some(ttl) => {
                tracing::info!(
                    "Writing team to Redis at key '{}' with TTL {} seconds: team_id={}",
                    cache_key,
                    ttl,
                    team.id
                );
                client
                    .setex(cache_key, serialized_team, ttl)
                    .await
                    .map_err(|e| {
                        tracing::error!(
                            "Failed to update Redis cache with TTL for team {} (token {}): {}",
                            team.id,
                            team.api_token,
                            e
                        );
                        FlagError::CacheUpdateError
                    })?;
            }
            None => {
                tracing::info!(
                    "Writing team to Redis at key '{}' without TTL: team_id={}",
                    cache_key,
                    team.id
                );
                client.set(cache_key, serialized_team).await.map_err(|e| {
                    tracing::error!(
                        "Failed to update Redis cache for team {} (token {}): {}",
                        team.id,
                        team.api_token,
                        e
                    );
                    FlagError::CacheUpdateError
                })?;
            }
        }

        Ok(())
    }

    pub async fn from_pg(client: PostgresReader, token: &str) -> Result<Team, FlagError> {
        let mut conn =
            get_connection_with_metrics(&client, "non_persons_reader", "fetch_team").await?;

        let query = format!("SELECT {TEAM_COLUMNS} FROM posthog_team WHERE api_token = $1");
        let row = sqlx::query_as::<_, Team>(&query)
            .bind(token)
            .fetch_one(&mut *conn)
            .await?;

        Ok(row)
    }

    pub async fn from_pg_by_secret_token(
        client: PostgresReader,
        token: &str,
    ) -> Result<Team, FlagError> {
        let mut conn =
            get_connection_with_metrics(&client, "non_persons_reader", "fetch_team_by_secret")
                .await?;

        let query = format!(
            "SELECT {TEAM_COLUMNS} FROM posthog_team WHERE secret_api_token = $1 OR secret_api_token_backup = $1"
        );
        let row = sqlx::query_as::<_, Team>(&query)
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
    use sqlx::types::Json;
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
        let id = rand::thread_rng().gen_range(1_000_000..100_000_000);
        let token = random_string("phc_", 12);
        let team = Team {
            id,
            name: "team".to_string(),
            api_token: token,
            cookieless_server_hash_mode: Some(0),
            timezone: "UTC".to_string(),
            ..Default::default()
        };
        let serialized_team = serde_json::to_string(&team).expect("Failed to serialise team");

        // manually insert non-pickled data in redis
        let client =
            redis::Client::open("redis://localhost:6379/").expect("Failed to create redis client");
        let mut conn = client
            .get_multiplexed_async_connection()
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
        let mut conn = get_connection_with_metrics(
            &context.non_persons_reader,
            "non_persons_reader",
            "test_update_team",
        )
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

    #[tokio::test]
    async fn test_fetch_team_from_redis_with_fallback_writes_on_not_found() {
        use common_redis::{CustomRedisError, MockRedisClient};

        let team_id = rand::thread_rng().gen_range(1_000_000..100_000_000);
        let token = random_string("phc_", 12);
        let test_team = Team {
            id: team_id,
            name: "team".to_string(),
            api_token: token.clone(),
            organization_id: Some(Uuid::new_v4()),
            ..Default::default()
        };

        // Set up mock redis client to return NotFound (which maps to TokenValidationError)
        let mut mock_client = MockRedisClient::new();
        mock_client.get_ret(
            &format!("{TEAM_TOKEN_CACHE_PREFIX}{token}"),
            Err(CustomRedisError::NotFound),
        );

        let redis_client: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client.clone());

        // Call the function with a DB lookup that returns the team
        let result =
            fetch_team_from_redis_with_fallback(redis_client, &token, Some(3600), || async {
                Ok(test_team.clone())
            })
            .await;

        // Should succeed and return the team
        assert!(result.is_ok());
        assert_eq!(result.unwrap().id, team_id);

        // Verify SETEX was called (cache write happened with TTL)
        let client_calls = mock_client.get_calls();
        assert!(
            client_calls.iter().any(|call| call.op == "setex"),
            "Expected SETEX to be called for NotFound error, but it wasn't"
        );
    }

    #[tokio::test]
    async fn test_fetch_team_from_redis_with_fallback_skips_write_on_timeout() {
        use common_redis::{CustomRedisError, MockRedisClient};

        let team_id = rand::thread_rng().gen_range(1_000_000..100_000_000);
        let token = random_string("phc_", 12);
        let test_team = Team {
            id: team_id,
            name: "team".to_string(),
            api_token: token.clone(),
            organization_id: Some(Uuid::new_v4()),
            ..Default::default()
        };

        // Set up mock redis client to return Timeout
        let mut mock_client = MockRedisClient::new();
        mock_client.get_ret(
            &format!("{TEAM_TOKEN_CACHE_PREFIX}{token}"),
            Err(CustomRedisError::Timeout),
        );

        let redis_client: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client.clone());

        // Call the function with a DB lookup that returns the team
        let result =
            fetch_team_from_redis_with_fallback(redis_client, &token, Some(3600), || async {
                Ok(test_team.clone())
            })
            .await;

        // Should succeed and return the team
        assert!(result.is_ok());
        assert_eq!(result.unwrap().id, team_id);

        // Verify SET was NOT called (cache write was skipped)
        let client_calls = mock_client.get_calls();
        assert!(
            !client_calls.iter().any(|call| call.op == "set"),
            "Expected SET to NOT be called for Timeout error, but it was"
        );
    }

    #[tokio::test]
    async fn test_fetch_team_from_redis_with_fallback_skips_write_on_redis_unavailable() {
        use common_redis::{CustomRedisError, MockRedisClient, RedisErrorKind};

        let team_id = rand::thread_rng().gen_range(1_000_000..100_000_000);
        let token = random_string("phc_", 12);
        let test_team = Team {
            id: team_id,
            name: "team".to_string(),
            api_token: token.clone(),
            organization_id: Some(Uuid::new_v4()),
            ..Default::default()
        };

        // Set up mock redis client to return Redis error (unavailable)
        let mut mock_client = MockRedisClient::new();
        mock_client.get_ret(
            &format!("{TEAM_TOKEN_CACHE_PREFIX}{token}"),
            Err(CustomRedisError::from_redis_kind(
                RedisErrorKind::IoError,
                "Connection refused",
            )),
        );

        let redis_client: Arc<dyn RedisClient + Send + Sync> = Arc::new(mock_client.clone());

        // Call the function with a DB lookup that returns the team
        let result =
            fetch_team_from_redis_with_fallback(redis_client, &token, Some(3600), || async {
                Ok(test_team.clone())
            })
            .await;

        // Should succeed and return the team
        assert!(result.is_ok());
        assert_eq!(result.unwrap().id, team_id);

        // Verify SET was NOT called (cache write was skipped)
        let client_calls = mock_client.get_calls();
        assert!(
            !client_calls.iter().any(|call| call.op == "set"),
            "Expected SET to NOT be called for Redis unavailable error, but it was"
        );
    }

    #[tokio::test]
    async fn test_fetch_team_with_extra_settings_from_pg() {
        let context = TestContext::new(None).await;

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        // Update the team with extra_settings containing recorder_script
        let mut conn = get_connection_with_metrics(
            &context.non_persons_reader,
            "non_persons_reader",
            "test_extra_settings",
        )
        .await
        .expect("Failed to get connection");

        let extra_settings = serde_json::json!({
            "recorder_script": "posthog-recorder",
            "something_else": 123
        });

        sqlx::query("UPDATE posthog_team SET extra_settings = $1 WHERE id = $2")
            .bind(&extra_settings)
            .bind(team.id)
            .execute(&mut *conn)
            .await
            .expect("Failed to update team with extra_settings");

        // Fetch the team and verify extra_settings deserializes correctly
        let team_from_pg = Team::from_pg(context.non_persons_reader.clone(), &team.api_token)
            .await
            .expect("Failed to fetch team with extra_settings from pg");

        assert!(team_from_pg.extra_settings.is_some());
        let config = team_from_pg.extra_settings.unwrap();
        assert_eq!(
            config.get("recorder_script").and_then(|v| v.as_str()),
            Some("posthog-recorder")
        );
    }

    #[tokio::test]
    async fn test_fetch_team_with_empty_recorder_script_from_pg() {
        let context = TestContext::new(None).await;

        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team in pg");

        // Update the team with extra_settings containing empty recorder_script
        let mut conn = get_connection_with_metrics(
            &context.non_persons_reader,
            "non_persons_reader",
            "test_empty_recorder_script",
        )
        .await
        .expect("Failed to get connection");

        let extra_settings = serde_json::json!({
            "recorder_script": ""
        });

        sqlx::query("UPDATE posthog_team SET extra_settings = $1 WHERE id = $2")
            .bind(&extra_settings)
            .bind(team.id)
            .execute(&mut *conn)
            .await
            .expect("Failed to update team with empty recorder_script");

        // Fetch the team and verify empty string is handled correctly
        let team_from_pg = Team::from_pg(context.non_persons_reader.clone(), &team.api_token)
            .await
            .expect("Failed to fetch team with empty recorder_script from pg");

        assert!(team_from_pg.extra_settings.is_some());
        let config = team_from_pg.extra_settings.unwrap();
        let recorder_script = config.get("recorder_script").and_then(|v| v.as_str());
        assert_eq!(recorder_script, Some(""));
    }

    #[tokio::test]
    async fn test_fetch_team_with_extra_settings_from_redis() {
        let client = setup_redis_client(None).await;

        let team_id = rand::thread_rng().gen_range(1_000_000..100_000_000);
        let token = random_string("phc_", 12);

        let extra_settings = serde_json::json!({
            "recorder_script": "posthog-recorder"
        });

        let team = Team {
            id: team_id,
            name: "team".to_string(),
            api_token: token.clone(),
            extra_settings: Some(Json(extra_settings.clone())),
            cookieless_server_hash_mode: Some(0),
            timezone: "UTC".to_string(),
            ..Default::default()
        };

        // Manually set team with extra_settings in Redis
        let serialized_team = serde_json::to_string(&team).expect("Failed to serialize team");

        client
            .set(format!("{TEAM_TOKEN_CACHE_PREFIX}{token}"), serialized_team)
            .await
            .expect("Failed to write team to redis");

        // Fetch from Redis and verify extra_settings deserializes correctly
        let team_from_redis = Team::from_redis(client.clone(), &token)
            .await
            .expect("Failed to fetch team with extra_settings from redis");

        assert_eq!(team_from_redis.api_token, token);
        assert_eq!(team_from_redis.id, team_id);
        assert!(team_from_redis.extra_settings.is_some());

        let config = team_from_redis.extra_settings.unwrap();
        assert_eq!(
            config.get("recorder_script").and_then(|v| v.as_str()),
            Some("posthog-recorder")
        );
    }

    #[tokio::test]
    async fn test_fetch_team_with_empty_recorder_script_from_redis() {
        let client = setup_redis_client(None).await;

        let team_id = rand::thread_rng().gen_range(1_000_000..100_000_000);
        let token = random_string("phc_", 12);

        let extra_settings = serde_json::json!({
            "recorder_script": ""
        });

        let team = Team {
            id: team_id,
            name: "team".to_string(),
            api_token: token.clone(),
            extra_settings: Some(Json(extra_settings.clone())),
            cookieless_server_hash_mode: Some(0),
            timezone: "UTC".to_string(),
            ..Default::default()
        };

        // Manually set team with empty recorder_script in Redis
        let serialized_team = serde_json::to_string(&team).expect("Failed to serialize team");

        client
            .set(format!("{TEAM_TOKEN_CACHE_PREFIX}{token}"), serialized_team)
            .await
            .expect("Failed to write team to redis");

        // Fetch from Redis and verify empty recorder_script is preserved
        let team_from_redis = Team::from_redis(client.clone(), &token)
            .await
            .expect("Failed to fetch team with empty recorder_script from redis");

        assert!(team_from_redis.extra_settings.is_some());
        let config = team_from_redis.extra_settings.unwrap();
        let recorder_script = config.get("recorder_script").and_then(|v| v.as_str());
        assert_eq!(recorder_script, Some(""));
    }
}
