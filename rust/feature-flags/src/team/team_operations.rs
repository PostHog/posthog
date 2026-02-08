use crate::{
    api::errors::FlagError, database::get_connection_with_metrics, team::team_models::Team,
};
use common_database::PostgresReader;
use serde_json::Value;

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
    logs_settings,
    session_recording_opt_in,
    inject_web_apps,
    surveys_opt_in,
    product_tours_opt_in,
    heatmaps_opt_in,
    conversations_enabled,
    conversations_settings,
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
    /// Parse team from HyperCache JSON value (team_metadata cache format).
    pub fn from_hypercache_value(value: Value) -> Result<Team, FlagError> {
        serde_json::from_value(value).map_err(|e| {
            tracing::error!("Failed to deserialize team from HyperCache: {e}");
            FlagError::RedisDataParsingError
        })
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
    use serde_json::json;

    use super::*;
    use crate::utils::test_utils::{
        insert_new_team_in_redis, setup_redis_client, setup_team_hypercache_reader, TestContext,
    };

    #[tokio::test]
    async fn test_fetch_team_from_hypercache() {
        let client = setup_redis_client(None).await;

        let team = insert_new_team_in_redis(client.clone())
            .await
            .expect("Failed to insert team in redis");

        // Verify we can fetch team from HyperCache
        let team_hypercache_reader = setup_team_hypercache_reader(client.clone()).await;
        let key = common_hypercache::KeyType::string(&team.api_token);
        let (data, _source) = team_hypercache_reader.get_with_source(&key).await.unwrap();

        let team_from_cache = Team::from_hypercache_value(data).unwrap();
        assert_eq!(team_from_cache.api_token, team.api_token);
        assert_eq!(team_from_cache.id, team.id);
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
    async fn test_from_hypercache_value_parses_extra_settings() {
        let extra_settings = json!({
            "recorder_script": "posthog-recorder",
            "something_else": 123
        });

        let team_data = json!({
            "id": 12345,
            "name": "Test Team",
            "api_token": "phc_test123",
            "uuid": "00000000-0000-0000-0000-000000012345",
            "timezone": "America/New_York",
            "extra_settings": extra_settings,
        });

        let team = Team::from_hypercache_value(team_data).expect("Failed to parse team");
        assert_eq!(team.id, 12345);
        assert_eq!(team.api_token, "phc_test123");
        assert_eq!(team.timezone, "America/New_York");
        assert!(team.extra_settings.is_some());

        let config = team.extra_settings.unwrap();
        assert_eq!(
            config.get("recorder_script").and_then(|v| v.as_str()),
            Some("posthog-recorder")
        );
    }

    #[tokio::test]
    async fn test_from_hypercache_value_handles_all_optional_fields() {
        let team_data = json!({
            "id": 99999,
            "name": "Minimal Team",
            "api_token": "phc_minimal",
            "uuid": "00000000-0000-0000-0000-000000000001",
            "organization_id": "00000000-0000-0000-0000-000000000002",
            "autocapture_opt_out": true,
            "session_recording_opt_in": false,
            "session_recording_sample_rate": "0.75",
            "cookieless_server_hash_mode": 1,
            "timezone": "Europe/London",
        });

        let team = Team::from_hypercache_value(team_data).expect("Failed to parse team");
        assert_eq!(team.id, 99999);
        assert_eq!(team.api_token, "phc_minimal");
        assert_eq!(team.autocapture_opt_out, Some(true));
        assert!(!team.session_recording_opt_in);
        assert_eq!(team.cookieless_server_hash_mode, Some(1));
        assert_eq!(team.timezone, "Europe/London");
    }

    #[tokio::test]
    async fn test_from_hypercache_value_rejects_non_object() {
        // Test with array
        let result = Team::from_hypercache_value(json!(["not", "an", "object"]));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));

        // Test with string
        let result = Team::from_hypercache_value(json!("just a string"));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));

        // Test with number
        let result = Team::from_hypercache_value(json!(42));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));

        // Test with null
        let result = Team::from_hypercache_value(json!(null));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));
    }

    #[tokio::test]
    async fn test_from_hypercache_value_rejects_missing_required_fields() {
        // Missing id
        let result = Team::from_hypercache_value(json!({
            "api_token": "phc_test",
            "uuid": "00000000-0000-0000-0000-000000000001"
        }));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));

        // Missing api_token
        let result = Team::from_hypercache_value(json!({
            "id": 123,
            "uuid": "00000000-0000-0000-0000-000000000001"
        }));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));

        // Missing uuid
        let result = Team::from_hypercache_value(json!({
            "id": 123,
            "api_token": "phc_test"
        }));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));

        // Empty object
        let result = Team::from_hypercache_value(json!({}));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));
    }

    #[tokio::test]
    async fn test_from_hypercache_value_rejects_invalid_uuid() {
        let result = Team::from_hypercache_value(json!({
            "id": 123,
            "api_token": "phc_test",
            "uuid": "not-a-valid-uuid"
        }));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));

        let result = Team::from_hypercache_value(json!({
            "id": 123,
            "api_token": "phc_test",
            "uuid": ""
        }));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));
    }

    #[tokio::test]
    async fn test_from_hypercache_value_rejects_wrong_field_types() {
        // id as string instead of number
        let result = Team::from_hypercache_value(json!({
            "id": "not-a-number",
            "api_token": "phc_test",
            "uuid": "00000000-0000-0000-0000-000000000001"
        }));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));

        // api_token as number instead of string
        let result = Team::from_hypercache_value(json!({
            "id": 123,
            "api_token": 12345,
            "uuid": "00000000-0000-0000-0000-000000000001"
        }));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));

        // uuid as number instead of string
        let result = Team::from_hypercache_value(json!({
            "id": 123,
            "api_token": "phc_test",
            "uuid": 12345
        }));
        assert!(matches!(result, Err(FlagError::RedisDataParsingError)));
    }
}
