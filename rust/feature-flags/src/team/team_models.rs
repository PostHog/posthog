use crate::config::TeamIdCollection;
use crate::team::request_blocklist::{self, BlockReason, BlockedHosts, BlockedIps};
use common_types::{TeamId, TeamIdentifier};
use rust_decimal::Decimal;
use serde::de::{value, IntoDeserializer};
use serde::{Deserialize, Serialize};
use sqlx::types::{Json, Uuid};
use std::net::IpAddr;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize, sqlx::Type)]
#[serde(transparent)]
#[sqlx(transparent)]
pub struct PropertyMatchingVersion(pub i16);

impl PropertyMatchingVersion {
    pub const LEGACY: Self = Self(1);
    pub const EXPLICIT: Self = Self(2);

    pub fn uses_explicit_matching(self) -> bool {
        self == Self::EXPLICIT
    }
}

impl Default for PropertyMatchingVersion {
    fn default() -> Self {
        Self::LEGACY
    }
}

/// The team's level in Django's `cohort_realtime_team_access` table, with the strings of
/// `RealtimeCohortLevel` in `products/cohorts/backend/models/team_access.py`. A team without a
/// row is `Off`.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RealtimeCohortLevel {
    #[default]
    Off,
    Processing,
    Serving,
    /// A level Django writes that this build does not know. It does not serve, so a new level
    /// never fails a team read.
    #[serde(other)]
    Unrecognized,
}

impl RealtimeCohortLevel {
    fn serves(self) -> bool {
        match self {
            Self::Serving => true,
            Self::Off | Self::Processing | Self::Unrecognized => false,
        }
    }
}

/// Parses with the serde names, so the Postgres read and the cache read accept the same strings.
impl From<String> for RealtimeCohortLevel {
    fn from(level: String) -> Self {
        let level: value::StringDeserializer<value::Error> = level.into_deserializer();
        Self::deserialize(level).expect("the catch-all variant accepts every string")
    }
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, sqlx::FromRow)]
pub struct Team {
    pub id: TeamId,
    pub name: String,
    pub api_token: String,
    pub uuid: Uuid,
    pub organization_id: Option<Uuid>,
    // The project (environment parent) this team belongs to. Django writes it into the team
    // metadata cache payload; `#[serde(default)]` keeps cache entries written before the
    // field existed deserializing (they get `None`, and the handler falls back to a query).
    #[serde(default)]
    pub project_id: Option<i64>,
    pub autocapture_opt_out: Option<bool>,
    pub autocapture_exceptions_opt_in: Option<bool>,
    pub autocapture_web_vitals_opt_in: Option<bool>,
    pub capture_performance_opt_in: Option<bool>,
    pub capture_console_log_opt_in: Option<bool>,
    pub logs_settings: Option<Json<serde_json::Value>>,
    #[serde(default)]
    pub session_recording_opt_in: bool, // Not nullable in schema, so needs to be handled in deserialization
    pub inject_web_apps: Option<bool>,
    pub surveys_opt_in: Option<bool>,
    pub product_tours_opt_in: Option<bool>,
    pub heatmaps_opt_in: Option<bool>,
    pub conversations_enabled: Option<bool>,
    pub conversations_settings: Option<Json<serde_json::Value>>,
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
    pub extra_settings: Option<Json<serde_json::Value>>,
    pub session_recording_url_trigger_config: Option<Vec<Json<serde_json::Value>>>, // jsonb[] in postgres
    pub session_recording_url_blocklist_config: Option<Vec<Json<serde_json::Value>>>, // jsonb[] in postgres
    pub session_recording_event_trigger_config: Option<Vec<Option<String>>>, // text[] in postgres. NB: this also contains NULL entries along with strings.
    pub session_recording_trigger_match_type_config: Option<String>, // character varying(24) in postgres
    pub recording_domains: Option<Vec<String>>, // character varying(200)[] in postgres
    #[serde(default, with = "option_i16_as_i16")]
    pub cookieless_server_hash_mode: Option<i16>,
    #[serde(default = "default_timezone")]
    pub timezone: String,
    // Sourced from the internal-only TeamFeatureFlagsConfig extension, not a posthog_team
    // column. #[serde(default)] keeps cache entries written before this field existed
    // deserializing to `false` (full events), fail-safe.
    #[serde(default)]
    pub minimal_flag_called_events: bool,
    // Cache entries written before this field existed retain legacy matching.
    #[serde(default)]
    pub property_matching_version: PropertyMatchingVersion,
    // Sourced from the customer-editable TeamFeatureFlagPolicyConfig extension. Cache entries
    // written before these fields existed deserialize to empty lists, which block nothing.
    #[serde(default)]
    #[sqlx(try_from = "Vec<String>")]
    pub flags_blocked_hosts: BlockedHosts,
    #[serde(default)]
    #[sqlx(try_from = "Vec<String>")]
    pub flags_blocked_ips: BlockedIps,
    // Sourced from the cohorts product's team access row. Cache entries written before this field
    // existed read `Off`, which leaves the team to REALTIME_COHORT_EVALUATION_TEAM_IDS.
    #[serde(default)]
    #[sqlx(try_from = "String")]
    pub realtime_cohort_level: RealtimeCohortLevel,
}

impl Team {
    /// Whether the team's realtime cohorts may read membership from the behavioral cohorts DB:
    /// the rollout list names the team, or its team access row is at `serving`.
    pub fn evaluates_realtime_cohorts(&self, rollout: &TeamIdCollection) -> bool {
        rollout.includes_team(self.id) || self.realtime_cohort_level.serves()
    }

    /// The reason this team's request blocklist refuses a caller with this host and these
    /// client IPs, or `None` when the caller is allowed.
    pub fn request_block_reason(
        &self,
        origin_host: Option<&str>,
        client_ips: impl IntoIterator<Item = IpAddr>,
    ) -> Option<BlockReason> {
        request_blocklist::check(
            &self.flags_blocked_hosts,
            &self.flags_blocked_ips,
            origin_host,
            client_ips,
        )
    }
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

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[test]
    fn test_minimal_flag_called_events_defaults_false_on_legacy_cache_blob() {
        // A HyperCache JSON blob written before this field existed has no
        // minimal_flag_called_events key. #[serde(default)] must make that
        // deserialize to `false` (full events) rather than erroring.
        let legacy_json = serde_json::json!({
            "id": 1,
            "name": "test team",
            "api_token": "test_token",
            "uuid": Uuid::new_v4().to_string(),
        });

        let team: Team =
            serde_json::from_value(legacy_json).expect("legacy blob must still deserialize");

        assert!(!team.minimal_flag_called_events);
        assert_eq!(
            team.property_matching_version,
            PropertyMatchingVersion::LEGACY
        );
        assert_eq!(
            team.request_block_reason(Some("example.com"), ["203.0.113.7".parse().unwrap()]),
            None
        );
        assert_eq!(team.realtime_cohort_level, RealtimeCohortLevel::Off);
    }

    #[rstest]
    #[case("off", RealtimeCohortLevel::Off)]
    #[case("processing", RealtimeCohortLevel::Processing)]
    #[case("serving", RealtimeCohortLevel::Serving)]
    #[case("beta", RealtimeCohortLevel::Unrecognized)]
    fn test_realtime_cohort_level_reads_django_levels_and_unknown_ones(
        #[case] level: &str,
        #[case] expected: RealtimeCohortLevel,
    ) {
        let cached = serde_json::json!({
            "id": 1,
            "name": "test team",
            "api_token": "test_token",
            "uuid": Uuid::new_v4().to_string(),
            "realtime_cohort_level": level,
        });

        let team: Team = serde_json::from_value(cached).expect("cache blob must deserialize");
        let reserialized: Team =
            serde_json::from_value(serde_json::to_value(&team).unwrap()).unwrap();

        assert_eq!(team.realtime_cohort_level, expected);
        assert_eq!(reserialized.realtime_cohort_level, expected);
        assert_eq!(RealtimeCohortLevel::from(level.to_string()), expected);
    }

    #[rstest]
    #[case::listed_without_a_row(TeamIdCollection::TeamIds(vec![1]), RealtimeCohortLevel::Off, true)]
    #[case::unlisted_at_serving(TeamIdCollection::None, RealtimeCohortLevel::Serving, true)]
    #[case::unlisted_at_processing(
        TeamIdCollection::TeamIds(vec![2]),
        RealtimeCohortLevel::Processing,
        false
    )]
    #[case::unlisted_at_an_unknown_level(
        TeamIdCollection::None,
        RealtimeCohortLevel::Unrecognized,
        false
    )]
    fn test_realtime_cohorts_follow_the_rollout_list_or_a_serving_row(
        #[case] rollout: TeamIdCollection,
        #[case] level: RealtimeCohortLevel,
        #[case] expected: bool,
    ) {
        let team = Team {
            id: 1,
            realtime_cohort_level: level,
            ..Default::default()
        };

        assert_eq!(team.evaluates_realtime_cohorts(&rollout), expected);
    }

    #[test]
    fn test_blocklist_survives_a_cache_round_trip() {
        let cached = serde_json::json!({
            "id": 1,
            "name": "test team",
            "api_token": "test_token",
            "uuid": Uuid::new_v4().to_string(),
            "flags_blocked_hosts": ["example.com"],
            "flags_blocked_ips": ["203.0.113.0/24", "not-an-ip"],
        });

        let team: Team = serde_json::from_value(cached).expect("cache blob must deserialize");
        let reserialized: Team =
            serde_json::from_value(serde_json::to_value(&team).unwrap()).unwrap();

        assert_eq!(reserialized.flags_blocked_ips, team.flags_blocked_ips);
        assert_eq!(
            reserialized
                .request_block_reason(Some("app.example.com"), ["198.51.100.1".parse().unwrap()]),
            Some(BlockReason::Host)
        );
        assert_eq!(
            reserialized.request_block_reason(None, ["203.0.113.9".parse().unwrap()]),
            Some(BlockReason::Ip)
        );
    }
}
