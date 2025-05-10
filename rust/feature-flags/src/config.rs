use common_cookieless::CookielessConfig;
use envconfig::Envconfig;
use once_cell::sync::Lazy;
use std::net::SocketAddr;
use std::num::ParseIntError;
use std::path::{Path, PathBuf};
use std::str::FromStr;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TeamIdsToTrack {
    All,
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
            ParseTeamIdsError::InvalidRange(r) => write!(f, "Invalid range: {}", r),
            ParseTeamIdsError::InvalidNumber(e) => write!(f, "Invalid number: {}", e),
        }
    }
}

impl std::error::Error for ParseTeamIdsError {}

impl FromStr for TeamIdsToTrack {
    type Err = ParseTeamIdsError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let s = s.trim();
        if s.eq_ignore_ascii_case("all") {
            Ok(TeamIdsToTrack::All)
        } else {
            let mut team_ids = Vec::new();
            for part in s.split(',').map(|p| p.trim()) {
                if part.contains(':') {
                    let bounds: Vec<&str> = part.split(':').collect();
                    if bounds.len() != 2 {
                        return Err(ParseTeamIdsError::InvalidRange(part.to_string()));
                    }
                    let start = bounds[0]
                        .parse::<i32>()
                        .map_err(ParseTeamIdsError::InvalidNumber)?;
                    let end = bounds[1]
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
            Ok(TeamIdsToTrack::TeamIds(team_ids))
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

    #[envconfig(default = "1000")]
    pub max_concurrency: usize,

    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    #[envconfig(default = "redis://localhost:6379/")]
    pub redis_url: String,

    #[envconfig(default = "redis://localhost:6379/")]
    pub redis_reader_url: String,

    #[envconfig(default = "1")]
    pub acquire_timeout_secs: u64,

    #[envconfig(from = "MAXMIND_DB_PATH", default = "")]
    pub maxmind_db_path: String,

    #[envconfig(default = "false")]
    pub enable_metrics: bool,

    #[envconfig(from = "TEAM_IDS_TO_TRACK", default = "all")]
    pub team_ids_to_track: TeamIdsToTrack,

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
}

impl Config {
    pub fn default_test_config() -> Self {
        Self {
            address: SocketAddr::from_str("127.0.0.1:0").unwrap(),
            redis_url: "redis://localhost:6379/".to_string(),
            redis_reader_url: "redis://localhost:6379/".to_string(),
            write_database_url: "postgres://posthog:posthog@localhost:5432/test_posthog"
                .to_string(),
            read_database_url: "postgres://posthog:posthog@localhost:5432/test_posthog".to_string(),
            max_concurrency: 1000,
            max_pg_connections: 10,
            acquire_timeout_secs: 5,
            maxmind_db_path: "".to_string(),
            enable_metrics: false,
            team_ids_to_track: TeamIdsToTrack::All,
            cache_max_cohort_entries: 100_000,
            cache_ttl_seconds: 300,
            cookieless_disabled: false,
            cookieless_force_stateless: false,
            cookieless_identifies_ttl_seconds: 7200,
            cookieless_salt_ttl_seconds: 86400,
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

    pub fn get_cookieless_config(&self) -> CookielessConfig {
        CookielessConfig {
            disabled: self.cookieless_disabled,
            force_stateless_mode: self.cookieless_force_stateless,
            identifies_ttl_seconds: self.cookieless_identifies_ttl_seconds,
            salt_ttl_seconds: self.cookieless_salt_ttl_seconds,
        }
    }
}

pub static DEFAULT_TEST_CONFIG: Lazy<Config> = Lazy::new(Config::default_test_config);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
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
        assert_eq!(config.redis_reader_url, "redis://localhost:6379/");
        assert_eq!(config.team_ids_to_track, TeamIdsToTrack::All);
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
        assert_eq!(config.redis_reader_url, "redis://localhost:6379/");
        assert_eq!(config.team_ids_to_track, TeamIdsToTrack::All);
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
        assert_eq!(config.redis_reader_url, "redis://localhost:6379/");
        assert_eq!(config.team_ids_to_track, TeamIdsToTrack::All);
    }

    #[test]
    fn test_team_ids_to_track_all() {
        let team_ids: TeamIdsToTrack = "all".parse().unwrap();
        assert_eq!(team_ids, TeamIdsToTrack::All);
    }

    #[test]
    fn test_team_ids_to_track_single_ids() {
        let team_ids: TeamIdsToTrack = "1,5,7,13".parse().unwrap();
        assert_eq!(team_ids, TeamIdsToTrack::TeamIds(vec![1, 5, 7, 13]));
    }

    #[test]
    fn test_team_ids_to_track_ranges() {
        let team_ids: TeamIdsToTrack = "1:3".parse().unwrap();
        assert_eq!(team_ids, TeamIdsToTrack::TeamIds(vec![1, 2, 3]));
    }

    #[test]
    fn test_team_ids_to_track_mixed() {
        let team_ids: TeamIdsToTrack = "1:3,5,7:9".parse().unwrap();
        assert_eq!(team_ids, TeamIdsToTrack::TeamIds(vec![1, 2, 3, 5, 7, 8, 9]));
    }

    #[test]
    fn test_invalid_range() {
        let result: Result<TeamIdsToTrack, _> = "5:3".parse();
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_number() {
        let result: Result<TeamIdsToTrack, _> = "abc".parse();
        assert!(result.is_err());
    }
}
