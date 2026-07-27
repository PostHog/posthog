//! Environment configuration, validated once at startup into a typed
//! [`RuntimeConfig`] (plan §2.9). After [`Config::validate`] the rest of the
//! service never sees raw strings: durations are `Duration`s, overrides and the
//! allowlist are parsed maps/sets, and stagger windows are clamped so a
//! sub-minimum (or zero) value is not representable downstream.

use std::collections::{HashMap, HashSet};
use std::net::SocketAddr;
use std::str::FromStr;
use std::time::Duration;

use axum_client_ip::SecureClientIpSource;
use common_types::TeamId;
use envconfig::Envconfig;
use serde::Deserialize;
use thiserror::Error;

use crate::domain::CacheKind;

/// A stagger window in seconds, clamped at construction.
///
/// The constructor is the only way to build one, and it clamps up to the
/// configured minimum and unconditionally to at least 1, so "a misconfigured 0
/// must not be expressible on the wire" holds by type alone (plan §2.6/§2.9),
/// independent of any caller-side validation.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct StaggerWindowSecs(u64);

impl StaggerWindowSecs {
    /// Clamp `value` up to `min`, and unconditionally to at least 1: even a
    /// caller passing an unvalidated zero `min` cannot construct a zero window.
    pub fn clamped(value: u64, min: u64) -> Self {
        StaggerWindowSecs(value.max(min).max(1))
    }

    pub fn get(self) -> u64 {
        self.0
    }
}

/// Per-team stream overrides, one object per team so stagger and future limiter
/// pairing cannot drift apart (plan §2.9). Only `stagger_s` is used today;
/// unknown fields are ignored so additive changes don't break parsing.
#[derive(Clone, Copy, Debug, Deserialize)]
struct TeamStreamOverride {
    stagger_s: Option<u64>,
}

/// Raw environment config. Every field defaults, so startup never fails on a
/// missing variable; [`validate`](Self::validate) turns it into a typed
/// [`RuntimeConfig`] and rejects incoherent values.
#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    /// Bind address.
    #[envconfig(default = "0.0.0.0:3302")]
    pub address: SocketAddr,

    /// Shared tier primary: `flags_with_cohorts.json` etag sweep + hints.
    #[envconfig(default = "redis://localhost:6379/")]
    pub redis_url: String,

    /// Dedicated flags tier primary. Empty means no dedicated tier (M4 falls
    /// back to shared).
    #[envconfig(default = "")]
    pub flags_redis_url: String,

    /// Optional reader for the auth-path team-cache probe only (staleness
    /// harmless there); trigger reads never use it.
    #[envconfig(default = "")]
    pub flags_redis_reader_url: String,

    /// ETag sweep cadence in ms (RFC 1 Hz shortcut).
    #[envconfig(default = "1000")]
    pub sweep_interval_ms: u64,

    /// Pub/sub fast-path toggle; sweep-only remains correct.
    #[envconfig(default = "true")]
    pub hints_enabled: bool,

    /// Version-carrying heartbeat cadence in seconds.
    #[envconfig(default = "15")]
    pub heartbeat_interval_secs: u64,

    /// Max connection age in seconds (M4 jitters ±10%).
    #[envconfig(default = "1800")]
    pub max_connection_age_secs: u64,

    /// Per-pod global connection cap (both kinds).
    #[envconfig(default = "50000")]
    pub max_connections: usize,

    /// Per-token cap for `Definitions`; no `RemoteEval` analogue by design.
    #[envconfig(default = "300")]
    pub definitions_max_connections_per_token: usize,

    /// Server-tier per-IP connect rate; stored now, enforced in M4.
    #[envconfig(default = "60")]
    pub definitions_connect_rate_per_ip_per_minute: u32,

    /// Default stagger window for `Definitions` (plan §2.6 arithmetic).
    #[envconfig(default = "60")]
    pub definitions_default_stagger_window_secs: u64,

    /// Default stagger window for `RemoteEval`.
    #[envconfig(default = "30")]
    pub remote_eval_default_stagger_window_secs: u64,

    /// Clamp floor for every stagger window; a configured 0 is rejected.
    #[envconfig(default = "5")]
    pub min_stagger_window_secs: u64,

    /// JSON `{"<team_id>": {"stagger_s": N}}`.
    #[envconfig(default = "{}")]
    pub team_stream_overrides: String,

    /// Comma-separated team ids admitted to `kind=remote_eval`.
    #[envconfig(default = "")]
    pub mode2_team_allowlist: String,

    /// Pretty (human) tracing when true, JSON when false — mirrors Django's
    /// `DEBUG` split. Off in production so logs ship as structured JSON.
    #[envconfig(default = "false")]
    pub debug: bool,

    /// Mount the Prometheus `/metrics` route and install the global recorder.
    /// Default true; tests set it false so they don't clobber the process-global
    /// recorder (feature-flags router.rs precedent).
    #[envconfig(default = "true")]
    pub enable_metrics: bool,

    /// Where the client IP is read from, parsed into an [`SecureClientIpSource`]
    /// (e.g. `ConnectInfo`, `RightmostXForwardedFor`). Default `ConnectInfo` suits
    /// a direct connection; Phase 2 verifies the correct X-Forwarded-For depth
    /// behind the ALB → Envoy path before switching this. Only the `definitions`
    /// per-IP connect-rate limit reads it (plan §2.5).
    #[envconfig(default = "ConnectInfo")]
    pub client_ip_source: String,

    /// S3 region for the HyperCache readers. The gateway builds an S3 client at
    /// startup (HyperCacheReader requires one) but NEVER reads S3 — every trigger
    /// and auth read is Redis-only (plan §2.7, §2.8). These exist only to satisfy
    /// the constructor.
    #[envconfig(default = "us-east-1")]
    pub object_storage_region: String,

    /// S3 bucket for the HyperCache readers (constructed, never read — see
    /// `object_storage_region`).
    #[envconfig(default = "posthog")]
    pub object_storage_bucket: String,

    /// Optional S3 endpoint override for the HyperCache readers (constructed,
    /// never read — see `object_storage_region`).
    #[envconfig(default = "")]
    pub object_storage_endpoint: String,
}

/// A startup validation failure.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum ConfigError {
    #[error("MIN_STAGGER_WINDOW_SECS must be > 0")]
    ZeroMinStagger,
    #[error("SWEEP_INTERVAL_MS must be > 0")]
    ZeroSweepInterval,
    #[error("HEARTBEAT_INTERVAL_SECS must be > 0")]
    ZeroHeartbeatInterval,
    #[error("MAX_CONNECTIONS must be > 0 (a zero cap rejects every connection while readiness stays green)")]
    ZeroMaxConnections,
    #[error("MAX_CONNECTION_AGE_SECS must be > 0")]
    ZeroMaxConnectionAge,
    #[error("invalid TEAM_STREAM_OVERRIDES: {0}")]
    InvalidTeamOverrides(String),
    #[error("invalid MODE2_TEAM_ALLOWLIST: {0}")]
    InvalidAllowlist(String),
    #[error("invalid CLIENT_IP_SOURCE: {0}")]
    InvalidClientIpSource(String),
}

impl Config {
    /// Validate once at startup into the typed [`RuntimeConfig`].
    pub fn validate(&self) -> Result<RuntimeConfig, ConfigError> {
        if self.min_stagger_window_secs == 0 {
            return Err(ConfigError::ZeroMinStagger);
        }
        if self.sweep_interval_ms == 0 {
            return Err(ConfigError::ZeroSweepInterval);
        }
        if self.heartbeat_interval_secs == 0 {
            return Err(ConfigError::ZeroHeartbeatInterval);
        }
        if self.max_connections == 0 {
            return Err(ConfigError::ZeroMaxConnections);
        }
        if self.max_connection_age_secs == 0 {
            return Err(ConfigError::ZeroMaxConnectionAge);
        }

        let min = self.min_stagger_window_secs;
        let team_overrides = parse_team_overrides(&self.team_stream_overrides, min)?;
        let mode2_allowlist = parse_allowlist(&self.mode2_team_allowlist)?;
        let client_ip_source = SecureClientIpSource::from_str(self.client_ip_source.trim())
            .map_err(|e| ConfigError::InvalidClientIpSource(e.to_string()))?;

        Ok(RuntimeConfig {
            address: self.address,
            redis_url: self.redis_url.clone(),
            flags_redis_url: non_empty(&self.flags_redis_url),
            flags_redis_reader_url: non_empty(&self.flags_redis_reader_url),
            sweep_interval: Duration::from_millis(self.sweep_interval_ms),
            hints_enabled: self.hints_enabled,
            heartbeat_interval: Duration::from_secs(self.heartbeat_interval_secs),
            max_connection_age: Duration::from_secs(self.max_connection_age_secs),
            max_connections: self.max_connections,
            definitions_max_connections_per_token: self.definitions_max_connections_per_token,
            definitions_connect_rate_per_ip_per_minute: self
                .definitions_connect_rate_per_ip_per_minute,
            min_stagger_window_secs: min,
            definitions_default_stagger: StaggerWindowSecs::clamped(
                self.definitions_default_stagger_window_secs,
                min,
            ),
            remote_eval_default_stagger: StaggerWindowSecs::clamped(
                self.remote_eval_default_stagger_window_secs,
                min,
            ),
            team_overrides,
            mode2_allowlist,
            debug: self.debug,
            enable_metrics: self.enable_metrics,
            client_ip_source,
            object_storage_region: self.object_storage_region.clone(),
            object_storage_bucket: self.object_storage_bucket.clone(),
            object_storage_endpoint: non_empty(&self.object_storage_endpoint),
        })
    }

    /// Baseline config for tests, mirroring the envconfig defaults so a test can
    /// tweak one field and call [`validate`](Self::validate).
    pub fn default_test_config() -> Self {
        Self {
            address: "0.0.0.0:3302".parse().expect("valid addr"),
            redis_url: "redis://localhost:6379/".to_string(),
            flags_redis_url: String::new(),
            flags_redis_reader_url: String::new(),
            sweep_interval_ms: 1000,
            hints_enabled: true,
            heartbeat_interval_secs: 15,
            max_connection_age_secs: 1800,
            max_connections: 50_000,
            definitions_max_connections_per_token: 300,
            definitions_connect_rate_per_ip_per_minute: 60,
            definitions_default_stagger_window_secs: 60,
            remote_eval_default_stagger_window_secs: 30,
            min_stagger_window_secs: 5,
            team_stream_overrides: "{}".to_string(),
            mode2_team_allowlist: String::new(),
            debug: false,
            enable_metrics: true,
            client_ip_source: "ConnectInfo".to_string(),
            object_storage_region: "us-east-1".to_string(),
            object_storage_bucket: "posthog".to_string(),
            object_storage_endpoint: String::new(),
        }
    }
}

/// The validated, typed config the rest of the service reads.
#[derive(Clone, Debug)]
pub struct RuntimeConfig {
    pub address: SocketAddr,
    pub redis_url: String,
    /// `None` when no dedicated flags tier is configured (M4 falls back to
    /// the shared tier).
    pub flags_redis_url: Option<String>,
    pub flags_redis_reader_url: Option<String>,
    pub sweep_interval: Duration,
    pub hints_enabled: bool,
    pub heartbeat_interval: Duration,
    pub max_connection_age: Duration,
    pub max_connections: usize,
    pub definitions_max_connections_per_token: usize,
    pub definitions_connect_rate_per_ip_per_minute: u32,
    pub min_stagger_window_secs: u64,
    definitions_default_stagger: StaggerWindowSecs,
    remote_eval_default_stagger: StaggerWindowSecs,
    team_overrides: HashMap<TeamId, StaggerWindowSecs>,
    mode2_allowlist: HashSet<TeamId>,
    pub debug: bool,
    pub enable_metrics: bool,
    pub client_ip_source: SecureClientIpSource,
    pub object_storage_region: String,
    pub object_storage_bucket: String,
    /// `None` when unset (the S3 client uses AWS defaults). Never actually read
    /// by the gateway — see the raw [`Config`] field docs.
    pub object_storage_endpoint: Option<String>,
}

impl RuntimeConfig {
    /// The stagger window for a team+kind: a team override wins over the
    /// per-kind default, and every value is already clamped to the minimum.
    pub fn stagger_for(&self, team_id: TeamId, kind: CacheKind) -> StaggerWindowSecs {
        if let Some(window) = self.team_overrides.get(&team_id) {
            return *window;
        }
        match kind {
            CacheKind::Definitions => self.definitions_default_stagger,
            CacheKind::RemoteEval => self.remote_eval_default_stagger,
        }
    }

    /// Whether a team may open a `kind=remote_eval` stream (Mode 2 admission).
    pub fn is_team_allowlisted_for_remote_eval(&self, team_id: TeamId) -> bool {
        self.mode2_allowlist.contains(&team_id)
    }
}

fn non_empty(s: &str) -> Option<String> {
    let s = s.trim();
    if s.is_empty() {
        None
    } else {
        Some(s.to_string())
    }
}

fn parse_team_overrides(
    raw: &str,
    min: u64,
) -> Result<HashMap<TeamId, StaggerWindowSecs>, ConfigError> {
    let raw = raw.trim();
    if raw.is_empty() {
        return Ok(HashMap::new());
    }
    let parsed: HashMap<String, TeamStreamOverride> =
        serde_json::from_str(raw).map_err(|e| ConfigError::InvalidTeamOverrides(e.to_string()))?;

    let mut out = HashMap::new();
    for (team_id_str, override_) in parsed {
        let team_id = team_id_str.trim().parse::<TeamId>().map_err(|e| {
            ConfigError::InvalidTeamOverrides(format!("bad team id {team_id_str:?}: {e}"))
        })?;
        if let Some(stagger_s) = override_.stagger_s {
            out.insert(team_id, StaggerWindowSecs::clamped(stagger_s, min));
        }
    }
    Ok(out)
}

fn parse_allowlist(raw: &str) -> Result<HashSet<TeamId>, ConfigError> {
    let raw = raw.trim();
    if raw.is_empty() {
        return Ok(HashSet::new());
    }
    let mut out = HashSet::new();
    for part in raw.split(',').map(str::trim) {
        if part.is_empty() {
            continue;
        }
        let team_id = part
            .parse::<TeamId>()
            .map_err(|e| ConfigError::InvalidAllowlist(format!("bad team id {part:?}: {e}")))?;
        out.insert(team_id);
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_validate_to_documented_values() {
        let cfg = Config::default_test_config().validate().expect("valid");
        assert_eq!(cfg.sweep_interval, Duration::from_millis(1000));
        assert_eq!(cfg.heartbeat_interval, Duration::from_secs(15));
        assert_eq!(cfg.max_connection_age, Duration::from_secs(1800));
        assert_eq!(cfg.max_connections, 50_000);
        assert_eq!(cfg.definitions_max_connections_per_token, 300);
        assert_eq!(cfg.min_stagger_window_secs, 5);
        assert!(cfg.hints_enabled);
        assert_eq!(cfg.flags_redis_url, None);
        assert_eq!(
            cfg.stagger_for(1, CacheKind::Definitions),
            StaggerWindowSecs::clamped(60, 5)
        );
        assert_eq!(
            cfg.stagger_for(1, CacheKind::RemoteEval),
            StaggerWindowSecs::clamped(30, 5)
        );
    }

    #[test]
    fn flags_redis_url_present_becomes_some() {
        let mut cfg = Config::default_test_config();
        cfg.flags_redis_url = "redis://flags:6379/".to_string();
        let rc = cfg.validate().expect("valid");
        assert_eq!(rc.flags_redis_url.as_deref(), Some("redis://flags:6379/"));
    }

    #[test]
    fn zero_min_stagger_rejected() {
        let mut cfg = Config::default_test_config();
        cfg.min_stagger_window_secs = 0;
        assert_eq!(cfg.validate().unwrap_err(), ConfigError::ZeroMinStagger);
    }

    #[test]
    fn zero_sweep_interval_rejected() {
        let mut cfg = Config::default_test_config();
        cfg.sweep_interval_ms = 0;
        assert_eq!(cfg.validate().unwrap_err(), ConfigError::ZeroSweepInterval);
    }

    #[test]
    fn zero_heartbeat_interval_rejected() {
        let mut cfg = Config::default_test_config();
        cfg.heartbeat_interval_secs = 0;
        assert_eq!(
            cfg.validate().unwrap_err(),
            ConfigError::ZeroHeartbeatInterval
        );
    }

    #[test]
    fn override_beats_default_and_is_clamped_to_min() {
        let mut cfg = Config::default_test_config();
        // team 7 asks for 2s, below the min of 5 -> clamps up to 5.
        cfg.team_stream_overrides = r#"{"7": {"stagger_s": 2}}"#.to_string();
        let rc = cfg.validate().expect("valid");
        assert_eq!(
            rc.stagger_for(7, CacheKind::Definitions),
            StaggerWindowSecs::clamped(5, 5)
        );
        assert_eq!(rc.stagger_for(7, CacheKind::Definitions).get(), 5);
        // A team without an override still gets the per-kind default.
        assert_eq!(rc.stagger_for(99, CacheKind::RemoteEval).get(), 30);
    }

    #[test]
    fn override_without_stagger_is_skipped() {
        let mut cfg = Config::default_test_config();
        cfg.team_stream_overrides = r#"{"7": {}}"#.to_string();
        let rc = cfg.validate().expect("valid");
        // Falls through to the per-kind default.
        assert_eq!(rc.stagger_for(7, CacheKind::Definitions).get(), 60);
    }

    #[test]
    fn malformed_overrides_rejected() {
        let mut cfg = Config::default_test_config();
        cfg.team_stream_overrides = "{not json".to_string();
        assert!(matches!(
            cfg.validate().unwrap_err(),
            ConfigError::InvalidTeamOverrides(_)
        ));
    }

    #[test]
    fn non_numeric_override_team_id_rejected() {
        let mut cfg = Config::default_test_config();
        cfg.team_stream_overrides = r#"{"abc": {"stagger_s": 60}}"#.to_string();
        assert!(matches!(
            cfg.validate().unwrap_err(),
            ConfigError::InvalidTeamOverrides(_)
        ));
    }

    #[test]
    fn allowlist_parses_with_spaces() {
        let mut cfg = Config::default_test_config();
        cfg.mode2_team_allowlist = " 1, 2 ,3 ".to_string();
        let rc = cfg.validate().expect("valid");
        assert!(rc.is_team_allowlisted_for_remote_eval(1));
        assert!(rc.is_team_allowlisted_for_remote_eval(2));
        assert!(rc.is_team_allowlisted_for_remote_eval(3));
        assert!(!rc.is_team_allowlisted_for_remote_eval(4));
    }

    #[test]
    fn empty_allowlist_admits_nobody() {
        let rc = Config::default_test_config().validate().expect("valid");
        assert!(!rc.is_team_allowlisted_for_remote_eval(1));
    }

    #[test]
    fn malformed_allowlist_entry_rejected() {
        let mut cfg = Config::default_test_config();
        cfg.mode2_team_allowlist = "1,x,3".to_string();
        assert!(matches!(
            cfg.validate().unwrap_err(),
            ConfigError::InvalidAllowlist(_)
        ));
    }

    #[test]
    fn stagger_window_clamps_up() {
        assert_eq!(StaggerWindowSecs::clamped(0, 5).get(), 5);
        assert_eq!(StaggerWindowSecs::clamped(3, 5).get(), 5);
        assert_eq!(StaggerWindowSecs::clamped(60, 5).get(), 60);
        // Zero is unrepresentable even with an unvalidated zero minimum.
        assert_eq!(StaggerWindowSecs::clamped(0, 0).get(), 1);
    }

    #[test]
    fn zero_max_connections_rejected() {
        let mut cfg = Config::default_test_config();
        cfg.max_connections = 0;
        assert_eq!(cfg.validate().unwrap_err(), ConfigError::ZeroMaxConnections);
    }

    #[test]
    fn zero_max_connection_age_rejected() {
        let mut cfg = Config::default_test_config();
        cfg.max_connection_age_secs = 0;
        assert_eq!(
            cfg.validate().unwrap_err(),
            ConfigError::ZeroMaxConnectionAge
        );
    }

    #[test]
    fn override_team_id_key_is_trimmed() {
        let mut cfg = Config::default_test_config();
        cfg.team_stream_overrides = r#"{" 7 ": {"stagger_s": 45}}"#.to_string();
        let rc = cfg.validate().expect("valid");
        assert_eq!(rc.stagger_for(7, CacheKind::Definitions).get(), 45);
    }

    #[test]
    fn default_client_ip_source_is_connect_info() {
        let rc = Config::default_test_config().validate().expect("valid");
        assert!(matches!(
            rc.client_ip_source,
            SecureClientIpSource::ConnectInfo
        ));
    }

    #[test]
    fn malformed_client_ip_source_rejected() {
        let mut cfg = Config::default_test_config();
        cfg.client_ip_source = "NotARealSource".to_string();
        assert!(matches!(
            cfg.validate().unwrap_err(),
            ConfigError::InvalidClientIpSource(_)
        ));
    }
}
