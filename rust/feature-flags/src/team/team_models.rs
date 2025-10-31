use common_types::{ProjectId, TeamId, TeamIdentifier};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use sqlx::types::{Json, Uuid};

pub const TEAM_TOKEN_CACHE_PREFIX: &str = "posthog:1:team_token:";

#[derive(Clone, Debug, Default, Deserialize, Serialize, sqlx::FromRow)]
pub struct Team {
    pub id: TeamId,
    pub name: String,
    pub api_token: String,
    /// Project ID. This field is not present in Redis cache before Dec 2025, but this is not a problem at all,
    /// because we know all Teams created before Dec 2025 have `project_id` = `id`. To handle this case gracefully,
    /// we use 0 as a fallback value in deserialization here, and handle this in `Team::from_redis`.
    /// Thanks to this default-base approach, we avoid invalidating the whole cache needlessly.
    pub project_id: ProjectId,
    pub uuid: Uuid,
    pub organization_id: Option<Uuid>,
    pub autocapture_opt_out: Option<bool>,
    pub autocapture_exceptions_opt_in: Option<bool>,
    pub autocapture_web_vitals_opt_in: Option<bool>,
    pub capture_performance_opt_in: Option<bool>,
    pub capture_console_log_opt_in: Option<bool>,
    #[serde(default)]
    pub session_recording_opt_in: bool, // Not nullable in schema, so needs to be handled in deserialization
    pub inject_web_apps: Option<bool>,
    pub surveys_opt_in: Option<bool>,
    pub heatmaps_opt_in: Option<bool>,
    pub capture_dead_clicks: Option<bool>,
    pub flags_persistence_default: Option<bool>,
    pub session_recording_sample_rate: Option<Decimal>, // numeric(3,2) in postgres, see https://docs.rs/sqlx/latest/sqlx/postgres/types/index.html#rust_decimal
    pub session_recording_minimum_duration_milliseconds: Option<i32>,
    pub autocapture_web_vitals_allowed_metrics: Option<Json<serde_json::Value>>,
    pub autocapture_exceptions_errors_to_ignore: Option<Json<serde_json::Value>>,
    pub session_recording_linked_flag: Option<Json<serde_json::Value>>,
    pub session_recording_network_payload_capture_config: Option<Json<serde_json::Value>>,
    pub session_recording_masking_config: Option<Json<serde_json::Value>>,
    pub session_replay_config: Option<Json<serde_json::Value>>,
    pub survey_config: Option<Json<serde_json::Value>>,
    pub session_recording_url_trigger_config: Option<Vec<Json<serde_json::Value>>>, // jsonb[] in postgres
    pub session_recording_url_blocklist_config: Option<Vec<Json<serde_json::Value>>>, // jsonb[] in postgres
    pub session_recording_event_trigger_config: Option<Vec<Option<String>>>, // text[] in postgres. NB: this also contains NULL entries along with strings.
    pub session_recording_trigger_match_type_config: Option<String>, // character varying(24) in postgres
    pub recording_domains: Option<Vec<String>>, // character varying(200)[] in postgres
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

impl TeamIdentifier for Team {
    fn team_id(&self) -> TeamId {
        self.id
    }

    fn api_token(&self) -> &str {
        &self.api_token
    }
}
