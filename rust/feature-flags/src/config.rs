use common_cookieless::CookielessConfig;
use envconfig::Envconfig;
use once_cell::sync::Lazy;
use std::net::SocketAddr;
use std::num::ParseIntError;
use std::ops::Deref;
use std::path::{Path, PathBuf};
use std::str::FromStr;
use tracing::Level;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FlexBool(pub bool);

impl FromStr for FlexBool {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "true" | "1" | "yes" | "on" => Ok(FlexBool(true)),
            "false" | "0" | "no" | "off" | "" => Ok(FlexBool(false)),
            _ => Err(format!("Invalid boolean value: {s}")),
        }
    }
}

impl From<FlexBool> for bool {
    fn from(flex: FlexBool) -> Self {
        flex.0
    }
}

impl Deref for FlexBool {
    type Target = bool;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TeamIdCollection {
    All,
    None,
    TeamIds(Vec<i32>),
}

#[derive(Debug)]
pub enum ParseTeamIdsError {
    InvalidRange(String),
    InvalidNumber(ParseIntError),
}

impl std::fmt::Display for ParseTeamIdsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ParseTeamIdsError::InvalidRange(r) => write!(f, "Invalid range: {r}"),
            ParseTeamIdsError::InvalidNumber(e) => write!(f, "Invalid number: {e}"),
        }
    }
}

impl std::error::Error for ParseTeamIdsError {}

impl FromStr for TeamIdCollection {
    type Err = ParseTeamIdsError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let s = s.trim();
        if s.eq_ignore_ascii_case("all") || s == "*" {
            Ok(TeamIdCollection::All)
        } else if s.eq_ignore_ascii_case("none") {
            Ok(TeamIdCollection::None)
        } else {
            let mut team_ids = Vec::new();
            for part in s.split(',').map(|p| p.trim()) {
                if part.contains(':') {
                    let mut bounds = part.split(':');
                    let (Some(start_str), Some(end_str)) = (bounds.next(), bounds.next()) else {
                        return Err(ParseTeamIdsError::InvalidRange(part.to_string()));
                    };
                    if bounds.next().is_some() {
                        return Err(ParseTeamIdsError::InvalidRange(part.to_string()));
                    }
                    let start = start_str
                        .parse::<i32>()
                        .map_err(ParseTeamIdsError::InvalidNumber)?;
                    let end = end_str
                        .parse::<i32>()
                        .map_err(ParseTeamIdsError::InvalidNumber)?;
                    if end < start {
                        return Err(ParseTeamIdsError::InvalidRange(part.to_string()));
                    }
                    for id in start..=end {
                        team_ids.push(id);
                    }
                } else {
                    let id = part
                        .parse::<i32>()
                        .map_err(ParseTeamIdsError::InvalidNumber)?;
                    team_ids.push(id);
                }
            }
            Ok(TeamIdCollection::TeamIds(team_ids))
        }
    }
}

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:3001")]
    pub address: SocketAddr,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub write_database_url: String,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub read_database_url: String,

    #[envconfig(default = "")]
    pub persons_write_database_url: String,

    #[envconfig(default = "")]
    pub persons_read_database_url: String,

    #[envconfig(default = "1000")]
    pub max_concurrency: usize,

    // Database connection pool settings:
    // - High traffic: Increase max_pg_connections (e.g., 20-50)
    // - Bursty traffic: Increase idle_timeout_secs to keep connections warm
    // - Note: With 4 pools (readers/writers × persons/non-persons), total connections = 4 × max_pg_connections
    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    #[envconfig(default = "redis://localhost:6379/")]
    pub redis_url: String,

    #[envconfig(default = "")]
    pub redis_reader_url: String,

    #[envconfig(default = "")]
    pub redis_writer_url: String,

    // How long to wait for a connection from the pool before timing out
    // - Increase if seeing "pool timed out" errors under load (e.g., 5-10s)
    // - Decrease for faster failure detection (minimum 1s)
    #[envconfig(default = "3")]
    pub acquire_timeout_secs: u64,

    // Close connections that have been idle for this many seconds
    // - Set to 0 to disable (connections never close due to idle)
    // - Increase for bursty traffic to avoid reconnection overhead (e.g., 600-900)
    // - Decrease to free resources more aggressively (e.g., 60-120)
    #[envconfig(default = "300")]
    pub idle_timeout_secs: u64,

    // Force refresh connections after this many seconds regardless of activity
    // - Set to 0 to disable (connections never refresh automatically)
    // - Decrease for unreliable networks or frequent DB restarts (e.g., 600-900)
    // - Increase for stable environments to reduce overhead (e.g., 3600-7200)
    #[envconfig(default = "1800")]
    pub max_lifetime_secs: u64,

    // Test connection health before returning from pool
    // - Set to true for production to catch stale connections
    // - Set to false in tests or very stable environments for slight performance gain
    #[envconfig(default = "true")]
    pub test_before_acquire: FlexBool,

    // How often to report database pool metrics (seconds)
    // - Decrease for more granular monitoring (e.g., 10-15)
    // - Increase to reduce metric volume (e.g., 60-120)
    #[envconfig(default = "30")]
    pub db_monitor_interval_secs: u64,

    // Pool utilization percentage that triggers warnings (0.0-1.0)
    // - Lower values (e.g., 0.7) provide earlier warnings
    // - Higher values (e.g., 0.9) reduce alert noise
    #[envconfig(default = "0.8")]
    pub db_pool_warn_utilization: f64,

    // How long to cache billing quota checks (seconds)
    // - Lower values ensure fresh quota data but increase Redis load
    // - Higher values reduce Redis queries but may allow brief overages
    #[envconfig(default = "5")]
    pub billing_limiter_cache_ttl_secs: u64,

    // Health check registration interval (seconds)
    // - Should be less than your orchestrator's liveness probe timeout
    // - Common values: 10-30 for Kubernetes environments
    #[envconfig(default = "30")]
    pub health_check_interval_secs: u64,

    // OpenTelemetry exporter timeout (seconds)
    // - Increase if OTEL endpoint is slow or remote
    // - Decrease to fail fast and avoid blocking
    #[envconfig(default = "3")]
    pub otel_export_timeout_secs: u64,

    #[envconfig(from = "MAXMIND_DB_PATH", default = "")]
    pub maxmind_db_path: String,

    #[envconfig(default = "false")]
    pub enable_metrics: bool,

    #[envconfig(from = "TEAM_IDS_TO_TRACK", default = "all")]
    pub team_ids_to_track: TeamIdCollection,

    #[envconfig(from = "CACHE_MAX_COHORT_ENTRIES", default = "100000")]
    pub cache_max_cohort_entries: u64,

    #[envconfig(from = "CACHE_TTL_SECONDS", default = "300")]
    pub cache_ttl_seconds: u64,

    // cookieless, should match the values in plugin-server/src/types.ts, except we don't use sessions here
    #[envconfig(from = "COOKIELESS_DISABLED", default = "false")]
    pub cookieless_disabled: bool,

    #[envconfig(from = "COOKIELESS_FORCE_STATELESS", default = "false")]
    pub cookieless_force_stateless: bool,

    #[envconfig(from = "COOKIELESS_IDENTIFIES_TTL_SECONDS", default = "7200")]
    pub cookieless_identifies_ttl_seconds: u64,

    #[envconfig(from = "COOKIELESS_SALT_TTL_SECONDS", default = "86400")]
    pub cookieless_salt_ttl_seconds: u64,

    #[envconfig(from = "COOKIELESS_REDIS_HOST", default = "localhost")]
    pub cookieless_redis_host: String,

    #[envconfig(from = "COOKIELESS_REDIS_PORT", default = "6379")]
    pub cookieless_redis_port: u64,

    #[envconfig(from = "NEW_ANALYTICS_CAPTURE_ENDPOINT", default = "/i/v0/e/")]
    pub new_analytics_capture_endpoint: String,

    #[envconfig(from = "NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS", default = "none")]
    pub new_analytics_capture_excluded_team_ids: TeamIdCollection,

    #[envconfig(from = "ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS", default = "none")]
    pub element_chain_as_string_excluded_teams: TeamIdCollection,

    #[envconfig(from = "DEBUG", default = "false")]
    pub debug: FlexBool,

    #[envconfig(from = "SESSION_REPLAY_RRWEB_SCRIPT", default = "")]
    pub session_replay_rrweb_script: String,

    #[envconfig(from = "SESSION_REPLAY_RRWEB_SCRIPT_ALLOWED_TEAMS", default = "none")]
    pub session_replay_rrweb_script_allowed_teams: TeamIdCollection,

    #[envconfig(from = "FLAGS_SESSION_REPLAY_QUOTA_CHECK", default = "false")]
    pub flags_session_replay_quota_check: bool,

    // OpenTelemetry configuration
    #[envconfig(from = "OTEL_EXPORTER_OTLP_ENDPOINT")]
    pub otel_url: Option<String>,

    #[envconfig(from = "OTEL_TRACES_SAMPLER_ARG", default = "0.001")]
    pub otel_sampling_rate: f64,

    #[envconfig(from = "OTEL_SERVICE_NAME", default = "posthog-feature-flags")]
    pub otel_service_name: String,

    #[envconfig(from = "OTEL_LOG_LEVEL", default = "info")]
    pub otel_log_level: Level,
}

impl Config {
    pub fn default_test_config() -> Self {
        Self {
            address: SocketAddr::from_str("127.0.0.1:0").unwrap(),
            redis_url: "redis://localhost:6379/".to_string(),
            redis_reader_url: "".to_string(),
            redis_writer_url: "".to_string(),
            write_database_url: "postgres://posthog:posthog@localhost:5432/test_posthog"
                .to_string(),
            read_database_url: "postgres://posthog:posthog@localhost:5432/test_posthog".to_string(),
            persons_write_database_url: "".to_string(),
            persons_read_database_url: "".to_string(),
            max_concurrency: 1000,
            max_pg_connections: 10,
            acquire_timeout_secs: 3,
            idle_timeout_secs: 300,
            max_lifetime_secs: 1800,
            test_before_acquire: FlexBool(true),
            db_monitor_interval_secs: 30,
            db_pool_warn_utilization: 0.8,
            billing_limiter_cache_ttl_secs: 5,
            health_check_interval_secs: 30,
            otel_export_timeout_secs: 3,
            maxmind_db_path: "".to_string(),
            enable_metrics: false,
            team_ids_to_track: TeamIdCollection::All,
            cache_max_cohort_entries: 100_000,
            cache_ttl_seconds: 300,
            cookieless_disabled: false,
            cookieless_force_stateless: false,
            cookieless_identifies_ttl_seconds: 7200,
            cookieless_salt_ttl_seconds: 86400,
            cookieless_redis_host: "localhost".to_string(),
            cookieless_redis_port: 6379,
            new_analytics_capture_endpoint: "/i/v0/e/".to_string(),
            new_analytics_capture_excluded_team_ids: TeamIdCollection::None,
            element_chain_as_string_excluded_teams: TeamIdCollection::None,
            debug: FlexBool(false),
            session_replay_rrweb_script: "".to_string(),
            session_replay_rrweb_script_allowed_teams: TeamIdCollection::None,
            flags_session_replay_quota_check: false,
            otel_url: None,
            otel_sampling_rate: 1.0,
            otel_service_name: "posthog-feature-flags".to_string(),
            otel_log_level: Level::ERROR,
        }
    }

    pub fn get_maxmind_db_path(&self) -> PathBuf {
        if self.maxmind_db_path.is_empty() {
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap()
                .parent()
                .unwrap()
                .join("share")
                .join("GeoLite2-City.mmdb")
        } else {
            PathBuf::from(&self.maxmind_db_path)
        }
    }

    pub fn get_redis_reader_url(&self) -> &str {
        if self.redis_reader_url.is_empty() {
            &self.redis_url
        } else {
            &self.redis_reader_url
        }
    }

    pub fn get_redis_writer_url(&self) -> &str {
        if self.redis_writer_url.is_empty() {
            &self.redis_url
        } else {
            &self.redis_writer_url
        }
    }

    pub fn get_redis_cookieless_url(&self) -> String {
        format!(
            "redis://{}:{}",
            self.cookieless_redis_host, self.cookieless_redis_port
        )
    }

    pub fn get_cookieless_config(&self) -> CookielessConfig {
        CookielessConfig {
            disabled: self.cookieless_disabled,
            force_stateless_mode: self.cookieless_force_stateless,
            identifies_ttl_seconds: self.cookieless_identifies_ttl_seconds,
            salt_ttl_seconds: self.cookieless_salt_ttl_seconds,
        }
    }

    pub fn is_team_excluded(&self, team_id: i32, teams_to_exclude: &TeamIdCollection) -> bool {
        match teams_to_exclude {
            TeamIdCollection::All => true,
            TeamIdCollection::None => false,
            TeamIdCollection::TeamIds(ids) => ids.contains(&team_id),
        }
    }

    /// Check if persons database routing is enabled
    pub fn is_persons_db_routing_enabled(&self) -> bool {
        !self.persons_read_database_url.is_empty() && !self.persons_write_database_url.is_empty()
    }

    /// Get the database URL for persons reads, falling back to the default read URL
    pub fn get_persons_read_database_url(&self) -> String {
        if self.persons_read_database_url.is_empty() {
            self.read_database_url.clone()
        } else {
            self.persons_read_database_url.clone()
        }
    }

    /// Get the database URL for persons writes, falling back to the default write URL
    pub fn get_persons_write_database_url(&self) -> String {
        if self.persons_write_database_url.is_empty() {
            self.write_database_url.clone()
        } else {
            self.persons_write_database_url.clone()
        }
    }
}

pub static DEFAULT_TEST_CONFIG: Lazy<Config> = Lazy::new(Config::default_test_config);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        std::env::set_var("DEBUG", "false");
        let config = Config::init_from_env().unwrap();
        assert_eq!(
            config.address,
            SocketAddr::from_str("127.0.0.1:3001").unwrap()
        );
        assert_eq!(
            config.write_database_url,
            "postgres://posthog:posthog@localhost:5432/posthog"
        );
        assert_eq!(
            config.read_database_url,
            "postgres://posthog:posthog@localhost:5432/posthog"
        );
        assert_eq!(config.max_concurrency, 1000);
        assert_eq!(config.max_pg_connections, 10);
        assert_eq!(config.redis_url, "redis://localhost:6379/");
        assert_eq!(config.team_ids_to_track, TeamIdCollection::All);
        assert_eq!(
            config.new_analytics_capture_excluded_team_ids,
            TeamIdCollection::None
        );
        assert_eq!(
            config.element_chain_as_string_excluded_teams,
            TeamIdCollection::None
        );
        assert_eq!(config.new_analytics_capture_endpoint, "/i/v0/e/");
        assert_eq!(config.debug, FlexBool(false));
        assert!(!config.flags_session_replay_quota_check);
    }

    #[test]
    fn test_default_test_config() {
        let config = Config::default_test_config();
        assert_eq!(config.address, SocketAddr::from_str("127.0.0.1:0").unwrap());
        assert_eq!(
            config.write_database_url,
            "postgres://posthog:posthog@localhost:5432/test_posthog"
        );
        assert_eq!(
            config.read_database_url,
            "postgres://posthog:posthog@localhost:5432/test_posthog"
        );
        assert_eq!(config.max_concurrency, 1000);
        assert_eq!(config.max_pg_connections, 10);
        assert_eq!(config.redis_url, "redis://localhost:6379/");
        assert_eq!(config.team_ids_to_track, TeamIdCollection::All);
        assert_eq!(
            config.new_analytics_capture_excluded_team_ids,
            TeamIdCollection::None
        );
        assert_eq!(
            config.element_chain_as_string_excluded_teams,
            TeamIdCollection::None
        );
    }

    #[test]
    fn test_default_test_config_static() {
        let config = &*DEFAULT_TEST_CONFIG;
        assert_eq!(config.address, SocketAddr::from_str("127.0.0.1:0").unwrap());
        assert_eq!(
            config.write_database_url,
            "postgres://posthog:posthog@localhost:5432/test_posthog"
        );
        assert_eq!(
            config.read_database_url,
            "postgres://posthog:posthog@localhost:5432/test_posthog"
        );
        assert_eq!(config.max_concurrency, 1000);
        assert_eq!(config.max_pg_connections, 10);
        assert_eq!(config.redis_url, "redis://localhost:6379/");
        assert_eq!(config.team_ids_to_track, TeamIdCollection::All);
        assert_eq!(
            config.new_analytics_capture_excluded_team_ids,
            TeamIdCollection::None
        );
        assert_eq!(
            config.element_chain_as_string_excluded_teams,
            TeamIdCollection::None
        );
    }

    #[test]
    fn test_team_ids_to_track_all() {
        let team_ids: TeamIdCollection = "all".parse().unwrap();
        assert_eq!(team_ids, TeamIdCollection::All);
    }

    #[test]
    fn test_team_ids_to_track_wildcard() {
        let team_ids: TeamIdCollection = "*".parse().unwrap();
        assert_eq!(team_ids, TeamIdCollection::All);
    }

    #[test]
    fn test_team_ids_to_track_none() {
        let team_ids: TeamIdCollection = "none".parse().unwrap();
        assert_eq!(team_ids, TeamIdCollection::None);
    }

    #[test]
    fn test_team_ids_to_track_single_ids() {
        let team_ids: TeamIdCollection = "1,5,7,13".parse().unwrap();
        assert_eq!(team_ids, TeamIdCollection::TeamIds(vec![1, 5, 7, 13]));
    }

    #[test]
    fn test_team_ids_to_track_ranges() {
        let team_ids: TeamIdCollection = "1:3".parse().unwrap();
        assert_eq!(team_ids, TeamIdCollection::TeamIds(vec![1, 2, 3]));
    }

    #[test]
    fn test_team_ids_to_track_mixed() {
        let team_ids: TeamIdCollection = "1:3,5,7:9".parse().unwrap();
        assert_eq!(
            team_ids,
            TeamIdCollection::TeamIds(vec![1, 2, 3, 5, 7, 8, 9])
        );
    }

    #[test]
    fn test_invalid_range() {
        let result: Result<TeamIdCollection, _> = "5:3".parse();
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_number() {
        let result: Result<TeamIdCollection, _> = "abc".parse();
        assert!(result.is_err());
    }
}
