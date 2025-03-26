use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use sqlx::types::{Json, Uuid};

pub const TEAM_TOKEN_CACHE_PREFIX: &str = "posthog:1:team_token:";

pub type TeamId = i32;
pub type ProjectId = i64;

#[derive(Clone, Debug, Default, Deserialize, Serialize, sqlx::FromRow)]
pub struct Team {
    pub id: TeamId,
    pub name: String,
    pub api_token: String,
    pub project_id: ProjectId,
    pub uuid: Uuid,
    // Optional boolean flags
    pub autocapture_opt_out: Option<bool>,
    pub autocapture_exceptions_opt_in: Option<bool>,
    pub autocapture_web_vitals_opt_in: Option<bool>,
    pub capture_performance_opt_in: Option<bool>,
    pub capture_console_log_opt_in: Option<bool>,
    pub session_recording_opt_in: bool, // Not nullable in schema
    pub inject_web_apps: Option<bool>,
    pub surveys_opt_in: Option<bool>,
    pub heatmaps_opt_in: Option<bool>,
    pub capture_dead_clicks: Option<bool>,
    pub flags_persistence_default: Option<bool>,
    // Numeric fields
    pub session_recording_sample_rate: Option<Decimal>, // numeric(3,2) in postgres
    pub session_recording_minimum_duration_milliseconds: Option<i32>,
    // JSON fields
    pub autocapture_web_vitals_allowed_metrics: Option<Json<serde_json::Value>>,
    pub autocapture_exceptions_errors_to_ignore: Option<Json<serde_json::Value>>,
    pub session_recording_linked_flag: Option<Json<serde_json::Value>>,
    pub session_recording_network_payload_capture_config: Option<Json<serde_json::Value>>,
    pub session_recording_masking_config: Option<Json<serde_json::Value>>,
    pub session_replay_config: Option<Json<serde_json::Value>>,
    pub survey_config: Option<Json<serde_json::Value>>,
    // Array fields
    pub session_recording_url_trigger_config: Option<Vec<Json<serde_json::Value>>>, // jsonb[] in postgres
    pub session_recording_url_blocklist_config: Option<Vec<Json<serde_json::Value>>>, // jsonb[] in postgres
    pub session_recording_event_trigger_config: Option<Vec<String>>, // text[] in postgres
    pub recording_domains: Option<Vec<String>>, // character varying(200)[] in postgres
}
