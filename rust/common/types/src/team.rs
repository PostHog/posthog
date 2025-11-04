use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use sqlx::types::Json;
use sqlx::Postgres;
use uuid::Uuid;

pub type TeamId = i32;
pub type ProjectId = i64;

/// Trait for types that can provide team identification for caching purposes
pub trait TeamIdentifier: std::fmt::Debug + Send + Sync {
    /// Returns the team ID
    fn team_id(&self) -> TeamId;
    /// Returns the API token for this team
    fn api_token(&self) -> &str;
}

// Actually an "environment"
#[derive(Debug, Clone, Default, Deserialize, Serialize, sqlx::FromRow)]
pub struct Team {
    pub id: TeamId,
    pub project_id: Option<ProjectId>,
    pub organization_id: Uuid,
    pub uuid: Uuid,
    pub api_token: String,
    pub name: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub anonymize_ips: bool,
    pub person_processing_opt_out: Option<bool>,
    pub autocapture_opt_out: Option<bool>,
    pub autocapture_exceptions_opt_in: Option<bool>,
    pub autocapture_web_vitals_opt_in: Option<bool>,
    pub capture_performance_opt_in: Option<bool>,
    pub capture_console_log_opt_in: Option<bool>,
    pub session_recording_opt_in: bool,
    pub inject_web_apps: Option<bool>,
    pub surveys_opt_in: Option<bool>,
    pub heatmaps_opt_in: Option<bool>,
    pub capture_dead_clicks: Option<bool>,
    pub flags_persistence_default: Option<bool>,
    pub session_recording_sample_rate: Option<Decimal>,
    pub session_recording_minimum_duration_milliseconds: Option<i32>,
    pub autocapture_web_vitals_allowed_metrics: Option<Json<JsonValue>>,
    pub autocapture_exceptions_errors_to_ignore: Option<Json<JsonValue>>,
    pub session_recording_linked_flag: Option<Json<JsonValue>>,
    pub session_recording_network_payload_capture_config: Option<Json<JsonValue>>,
    pub session_recording_masking_config: Option<Json<JsonValue>>,
    pub session_replay_config: Option<Json<JsonValue>>,
    pub survey_config: Option<Json<JsonValue>>,
    pub session_recording_url_trigger_config: Option<Vec<Json<JsonValue>>>,
    pub session_recording_url_blocklist_config: Option<Vec<Json<JsonValue>>>,
    pub session_recording_event_trigger_config: Option<Vec<Option<String>>>,
    pub session_recording_trigger_match_type_config: Option<String>,
    pub recording_domains: Option<Vec<String>>,
    #[serde(with = "option_i16_as_i16")]
    pub cookieless_server_hash_mode: Option<i16>,
    #[serde(default = "default_timezone")]
    pub timezone: String,
}

fn default_timezone() -> String {
    "UTC".to_string()
}

mod option_i16_as_i16 {
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S>(value: &Option<i16>, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_i16(value.unwrap_or(0))
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Option<i16>, D::Error>
    where
        D: Deserializer<'de>,
    {
        Option::<i16>::deserialize(deserializer)
    }
}

impl Team {
    pub fn project_id(&self) -> ProjectId {
        // If `project_id` is not present, this means the payload is from before December 2024, which we correct for here
        self.project_id.unwrap_or(self.id as ProjectId)
    }

    pub async fn load<'c, E>(e: E, id: TeamId) -> Result<Option<Team>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Team,
            r#"
                SELECT
                    id,
                    project_id,
                    organization_id,
                    uuid,
                    api_token,
                    name,
                    created_at,
                    updated_at,
                    anonymize_ips,
                    person_processing_opt_out,
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
                    autocapture_web_vitals_allowed_metrics as "autocapture_web_vitals_allowed_metrics: _",
                    autocapture_exceptions_errors_to_ignore as "autocapture_exceptions_errors_to_ignore: _",
                    session_recording_linked_flag as "session_recording_linked_flag: _",
                    session_recording_network_payload_capture_config as "session_recording_network_payload_capture_config: _",
                    session_recording_masking_config as "session_recording_masking_config: _",
                    session_replay_config as "session_replay_config: _",
                    survey_config as "survey_config: _",
                    session_recording_url_trigger_config as "session_recording_url_trigger_config: _",
                    session_recording_url_blocklist_config as "session_recording_url_blocklist_config: _",
                    session_recording_event_trigger_config as "session_recording_event_trigger_config: _",
                    session_recording_trigger_match_type_config,
                    recording_domains,
                    cookieless_server_hash_mode,
                    timezone
                FROM posthog_team
                WHERE id = $1
                LIMIT 1
            "#,
            id
        )
        .fetch_optional(e)
        .await
    }

    pub async fn load_by_token<'c, E>(e: E, token: &str) -> Result<Option<Team>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Team,
            r#"
                SELECT
                    id,
                    project_id,
                    organization_id,
                    uuid,
                    api_token,
                    name,
                    created_at,
                    updated_at,
                    anonymize_ips,
                    person_processing_opt_out,
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
                    autocapture_web_vitals_allowed_metrics as "autocapture_web_vitals_allowed_metrics: _",
                    autocapture_exceptions_errors_to_ignore as "autocapture_exceptions_errors_to_ignore: _",
                    session_recording_linked_flag as "session_recording_linked_flag: _",
                    session_recording_network_payload_capture_config as "session_recording_network_payload_capture_config: _",
                    session_recording_masking_config as "session_recording_masking_config: _",
                    session_replay_config as "session_replay_config: _",
                    survey_config as "survey_config: _",
                    session_recording_url_trigger_config as "session_recording_url_trigger_config: _",
                    session_recording_url_blocklist_config as "session_recording_url_blocklist_config: _",
                    session_recording_event_trigger_config as "session_recording_event_trigger_config: _",
                    session_recording_trigger_match_type_config,
                    recording_domains,
                    cookieless_server_hash_mode,
                    timezone
                FROM posthog_team
                WHERE api_token = $1
                LIMIT 1
            "#,
            token
        )
        .fetch_optional(e)
        .await
    }
}

impl TeamIdentifier for Team {
    fn team_id(&self) -> TeamId {
        self.id
    }

    fn api_token(&self) -> &str {
        &self.api_token
    }
}
