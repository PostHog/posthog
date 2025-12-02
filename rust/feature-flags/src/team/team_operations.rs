use crate::{
    api::errors::FlagError, database::get_connection_with_metrics, team::team_models::Team,
};
use common_database::PostgresReader;
use rust_decimal::Decimal;
use serde_json::Value;
use sqlx::types::{Json, Uuid};
use std::str::FromStr;

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
    /// Parse team from HyperCache JSON value (team_metadata cache format).
    ///
    /// The HyperCache format from Django's team_metadata_cache stores team fields
    /// as a JSON object. This method parses the relevant fields into a Team struct,
    /// using defaults for any missing optional fields.
    pub fn from_hypercache_value(value: Value) -> Result<Team, FlagError> {
        let obj = value.as_object().ok_or_else(|| {
            tracing::error!("HyperCache team value is not an object");
            FlagError::RedisDataParsingError
        })?;

        // Required fields
        let id = obj
            .get("id")
            .and_then(|v| v.as_i64())
            .map(|v| v as i32)
            .ok_or_else(|| {
                tracing::error!("Missing or invalid 'id' field in team metadata");
                FlagError::RedisDataParsingError
            })?;

        let api_token = obj
            .get("api_token")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .ok_or_else(|| {
                tracing::error!("Missing or invalid 'api_token' field in team metadata");
                FlagError::RedisDataParsingError
            })?;

        let uuid_str = obj.get("uuid").and_then(|v| v.as_str()).ok_or_else(|| {
            tracing::error!("Missing or invalid 'uuid' field in team metadata");
            FlagError::RedisDataParsingError
        })?;
        let uuid = Uuid::from_str(uuid_str).map_err(|e| {
            tracing::error!("Failed to parse uuid '{}': {}", uuid_str, e);
            FlagError::RedisDataParsingError
        })?;

        // Helper to get optional string
        let get_str = |key: &str| -> Option<String> {
            obj.get(key).and_then(|v| v.as_str()).map(|s| s.to_string())
        };

        // Helper to get optional bool
        let get_bool = |key: &str| -> Option<bool> { obj.get(key).and_then(|v| v.as_bool()) };

        // Helper to get optional i32
        let get_i32 =
            |key: &str| -> Option<i32> { obj.get(key).and_then(|v| v.as_i64()).map(|v| v as i32) };

        // Helper to get optional JSON value wrapped in Json<>
        let get_json = |key: &str| -> Option<Json<serde_json::Value>> {
            obj.get(key)
                .filter(|v| !v.is_null())
                .map(|v| Json(v.clone()))
        };

        // Parse organization_id (stored as string UUID in cache)
        let organization_id = obj
            .get("organization_id")
            .and_then(|v| v.as_str())
            .and_then(|s| Uuid::from_str(s).ok());

        // Parse session_recording_sample_rate (stored as f64 in cache, need Decimal)
        let session_recording_sample_rate = obj
            .get("session_recording_sample_rate")
            .and_then(|v| v.as_f64())
            .and_then(|f| Decimal::try_from(f).ok());

        // Parse array fields for session recording configs
        let session_recording_url_trigger_config: Option<Vec<Json<serde_json::Value>>> = obj
            .get("session_recording_url_trigger_config")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().map(|item| Json(item.clone())).collect());

        let session_recording_url_blocklist_config: Option<Vec<Json<serde_json::Value>>> = obj
            .get("session_recording_url_blocklist_config")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().map(|item| Json(item.clone())).collect());

        let session_recording_event_trigger_config: Option<Vec<Option<String>>> = obj
            .get("session_recording_event_trigger_config")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .map(|item| item.as_str().map(|s| s.to_string()))
                    .collect()
            });

        let recording_domains: Option<Vec<String>> = obj
            .get("recording_domains")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|item| item.as_str().map(|s| s.to_string()))
                    .collect()
            });

        // Parse cookieless_server_hash_mode (may be stored as integer)
        let cookieless_server_hash_mode = obj
            .get("cookieless_server_hash_mode")
            .and_then(|v| v.as_i64())
            .map(|v| v as i16);

        Ok(Team {
            id,
            name: get_str("name").unwrap_or_default(),
            api_token,
            uuid,
            organization_id,
            autocapture_opt_out: get_bool("autocapture_opt_out"),
            autocapture_exceptions_opt_in: get_bool("autocapture_exceptions_opt_in"),
            autocapture_web_vitals_opt_in: get_bool("autocapture_web_vitals_opt_in"),
            capture_performance_opt_in: get_bool("capture_performance_opt_in"),
            capture_console_log_opt_in: get_bool("capture_console_log_opt_in"),
            session_recording_opt_in: get_bool("session_recording_opt_in").unwrap_or(false),
            inject_web_apps: get_bool("inject_web_apps"),
            surveys_opt_in: get_bool("surveys_opt_in"),
            heatmaps_opt_in: get_bool("heatmaps_opt_in"),
            capture_dead_clicks: get_bool("capture_dead_clicks"),
            flags_persistence_default: get_bool("flags_persistence_default"),
            session_recording_sample_rate,
            session_recording_minimum_duration_milliseconds: get_i32(
                "session_recording_minimum_duration_milliseconds",
            ),
            autocapture_web_vitals_allowed_metrics: get_json(
                "autocapture_web_vitals_allowed_metrics",
            ),
            autocapture_exceptions_errors_to_ignore: get_json(
                "autocapture_exceptions_errors_to_ignore",
            ),
            session_recording_linked_flag: get_json("session_recording_linked_flag"),
            session_recording_network_payload_capture_config: get_json(
                "session_recording_network_payload_capture_config",
            ),
            session_recording_masking_config: get_json("session_recording_masking_config"),
            session_replay_config: get_json("session_replay_config"),
            survey_config: get_json("survey_config"),
            extra_settings: get_json("extra_settings"),
            session_recording_url_trigger_config,
            session_recording_url_blocklist_config,
            session_recording_event_trigger_config,
            session_recording_trigger_match_type_config: get_str(
                "session_recording_trigger_match_type_config",
            ),
            recording_domains,
            cookieless_server_hash_mode,
            timezone: get_str("timezone").unwrap_or_else(|| "UTC".to_string()),
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
}
