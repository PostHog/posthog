use std::net::SocketAddr;
use std::str::FromStr;
use std::time::Duration;

use cymbal_alerting::ALERTING_STAGE_ID;
use cymbal_core::routing::{RemoteRoutingConfig, RoutingPolicy};
use cymbal_grouping::GROUPING_STAGE_ID;
use cymbal_linking::LINKING_STAGE_ID;
use cymbal_resolution::RESOLUTION_STAGE_ID;
use cymbal_runtime::RuntimeConfig;
use envconfig::Envconfig;

use crate::remote::{RemoteStageConnectionOptions, RemoteStageTarget};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ServerMode {
    Pipeline,
    Stage,
    All,
}

impl FromStr for ServerMode {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "pipeline" => Ok(Self::Pipeline),
            "stage" => Ok(Self::Stage),
            "all" => Ok(Self::All),
            _ => Err(format!(
                "invalid CYMBAL_MODE {value}; expected pipeline, stage, or all"
            )),
        }
    }
}

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(nested = true)]
    pub runtime: RuntimeConfig,
    #[envconfig(default = "127.0.0.1:50051")]
    pub grpc_address: SocketAddr,
    #[envconfig(default = "pipeline")]
    pub cymbal_mode: ServerMode,
    #[envconfig(default = "resolution:v1,linking:v1")]
    pub cymbal_stage_ids: String,
    #[envconfig(default = "")]
    pub cymbal_remote_targets: String,
    #[envconfig(default = "")]
    pub cymbal_remote_stages: String,
    #[envconfig(default = "30000")]
    pub cymbal_remote_refresh_interval_ms: u64,
    #[envconfig(default = "5000")]
    pub cymbal_remote_connect_timeout_ms: u64,
    #[envconfig(default = "30000")]
    pub cymbal_remote_tcp_keepalive_ms: u64,
    #[envconfig(default = "30000")]
    pub cymbal_remote_http2_keepalive_interval_ms: u64,
    #[envconfig(default = "10000")]
    pub cymbal_remote_keepalive_timeout_ms: u64,
    #[envconfig(default = "30000")]
    pub cymbal_remote_stage_timeout_ms: u64,
    #[envconfig(default = "true")]
    pub cymbal_remote_routing_enabled: bool,
    #[envconfig(default = "")]
    pub cymbal_remote_routing_policies: String,
    #[envconfig(default = "500")]
    pub cymbal_max_batch_events: usize,
    #[envconfig(default = "10000")]
    pub cymbal_max_stage_items: usize,
    #[envconfig(default = "64")]
    pub cymbal_max_in_flight_batches: usize,
    #[envconfig(default = "0")]
    pub cymbal_max_in_flight_stage_items: usize,
    #[envconfig(default = "")]
    pub cymbal_stage_max_in_flight_items: String,
    #[envconfig(default = "")]
    pub cymbal_readiness_file: String,
    #[envconfig(default = "0")]
    pub cymbal_shutdown_drain_delay_ms: u64,
    #[envconfig(default = "60000")]
    pub cymbal_shutdown_max_wait_ms: u64,
}

pub fn parse_stage_ids(stage_ids: &str) -> Vec<String> {
    stage_ids
        .split(',')
        .map(str::trim)
        .filter(|stage_id| !stage_id.is_empty())
        .map(ToString::to_string)
        .collect()
}

pub fn parse_remote_targets(targets: &str) -> Result<Vec<RemoteStageTarget>, String> {
    targets
        .split(',')
        .map(str::trim)
        .filter(|target| !target.is_empty())
        .map(parse_remote_target)
        .collect()
}

pub fn parse_remote_stage_routes(routes: &str) -> Result<Vec<(String, String)>, String> {
    routes
        .split(',')
        .map(str::trim)
        .filter(|route| !route.is_empty())
        .map(|route| {
            let Some((stage_id, target_name)) = route.split_once('=') else {
                return Err(format!(
                    "invalid remote stage route {route}; expected stage_id=target_name"
                ));
            };
            Ok((stage_id.trim().to_string(), target_name.trim().to_string()))
        })
        .collect()
}

/// Derive `(stage_id, target_name)` routes from `targets` under the convention
/// that one remote target serves a single stage whose ID matches the target's
/// name. The Helm chart relies on this so an operator only configures a single
/// `CYMBAL_REMOTE_TARGETS=resolution=...,linking=...` list rather than keeping
/// `CYMBAL_REMOTE_STAGES` in sync with it.
pub fn derive_remote_stage_routes_from_targets(
    targets: &[RemoteStageTarget],
) -> Vec<(String, String)> {
    targets
        .iter()
        .map(|target| (target.name.clone(), target.name.clone()))
        .collect()
}

/// Resolve the effective `(stage_id, target_name)` routes the pipeline pod
/// should register. An explicit `CYMBAL_REMOTE_STAGES` value wins so an
/// operator can still split a target across multiple stages or rename. When
/// unset, fall back to the by-convention derivation from `targets`.
pub fn resolve_remote_stage_routes(
    routes_env: &str,
    targets: &[RemoteStageTarget],
) -> Result<Vec<(String, String)>, String> {
    let explicit = parse_remote_stage_routes(routes_env)?;
    if !explicit.is_empty() {
        return Ok(explicit);
    }
    Ok(derive_remote_stage_routes_from_targets(targets))
}

pub fn parse_stage_item_limits(limits: &str) -> Result<Vec<(String, usize)>, String> {
    limits
        .split(',')
        .map(str::trim)
        .filter(|limit| !limit.is_empty())
        .map(|limit| {
            let Some((stage_id, max_items)) = limit.split_once('=') else {
                return Err(format!(
                    "invalid stage item limit {limit}; expected stage_id=max_in_flight_items"
                ));
            };
            let max_items = max_items.trim().parse::<usize>().map_err(|error| {
                format!("invalid stage item limit {max_items} for {stage_id}: {error}")
            })?;
            if max_items == 0 {
                return Err(format!(
                    "invalid stage item limit {limit}; max_in_flight_items must be greater than zero"
                ));
            }

            Ok((stage_id.trim().to_string(), max_items))
        })
        .collect()
}

pub fn remote_connection_options(config: &Config) -> RemoteStageConnectionOptions {
    RemoteStageConnectionOptions {
        connect_timeout: Duration::from_millis(config.cymbal_remote_connect_timeout_ms),
        tcp_keepalive: non_zero_duration(config.cymbal_remote_tcp_keepalive_ms),
        http2_keep_alive_interval: non_zero_duration(
            config.cymbal_remote_http2_keepalive_interval_ms,
        ),
        keep_alive_timeout: Duration::from_millis(config.cymbal_remote_keepalive_timeout_ms),
        stage_timeout: non_zero_duration(config.cymbal_remote_stage_timeout_ms),
    }
}

pub fn remote_routing_config(config: &Config) -> Result<RemoteRoutingConfig, String> {
    if !config.cymbal_remote_routing_enabled {
        return Ok(emergency_random_remote_routing_config());
    }

    let mut routing = default_remote_routing_config();
    for (stage_id, policy) in parse_remote_routing_policies(&config.cymbal_remote_routing_policies)?
    {
        routing.set_stage_policy(stage_id, policy);
    }
    Ok(routing)
}

pub fn default_remote_routing_config() -> RemoteRoutingConfig {
    RemoteRoutingConfig::new(RoutingPolicy::affinity_first())
        .with_stage_policy(RESOLUTION_STAGE_ID, RoutingPolicy::affinity_first())
        .with_stage_policy(GROUPING_STAGE_ID, RoutingPolicy::affinity_first())
        .with_stage_policy(LINKING_STAGE_ID, RoutingPolicy::strict_affinity())
        .with_stage_policy(ALERTING_STAGE_ID, RoutingPolicy::strict_affinity())
}

pub fn emergency_random_remote_routing_config() -> RemoteRoutingConfig {
    RemoteRoutingConfig::new(RoutingPolicy::random().with_max_fallback_attempts(0))
        .with_stage_policy(
            RESOLUTION_STAGE_ID,
            RoutingPolicy::random().with_max_fallback_attempts(0),
        )
        .with_stage_policy(
            GROUPING_STAGE_ID,
            RoutingPolicy::random().with_max_fallback_attempts(0),
        )
        .with_stage_policy(
            LINKING_STAGE_ID,
            RoutingPolicy::random().with_max_fallback_attempts(0),
        )
        .with_stage_policy(
            ALERTING_STAGE_ID,
            RoutingPolicy::random().with_max_fallback_attempts(0),
        )
        .without_observed_load()
}

pub fn parse_remote_routing_policies(
    policies: &str,
) -> Result<Vec<(String, RoutingPolicy)>, String> {
    policies
        .split(',')
        .map(str::trim)
        .filter(|policy| !policy.is_empty())
        .map(|policy| {
            let Some((stage_id, spec)) = policy.split_once('=') else {
                return Err(format!(
                    "invalid remote routing policy {policy}; expected stage_id=mode[:max_fallback_attempts]"
                ));
            };
            Ok((stage_id.trim().to_string(), parse_routing_policy(spec.trim())?))
        })
        .collect()
}

fn parse_remote_target(target: &str) -> Result<RemoteStageTarget, String> {
    let Some((name, endpoint)) = target.split_once('=') else {
        return Err(format!(
            "invalid remote target {target}; expected name=host:port or name=scheme://host:port"
        ));
    };
    let name = name.trim();
    let endpoint = endpoint.trim();
    let (scheme, address) = endpoint
        .split_once("://")
        .map_or(("http", endpoint), |(scheme, address)| (scheme, address));
    let Some((dns_name, port)) = address.rsplit_once(':') else {
        return Err(format!(
            "invalid remote target endpoint {endpoint}; expected host:port"
        ));
    };
    let port = port
        .parse::<u16>()
        .map_err(|error| format!("invalid remote target port {port}: {error}"))?;

    Ok(RemoteStageTarget::with_scheme(
        name.to_string(),
        dns_name.trim().to_string(),
        port,
        scheme.to_string(),
    ))
}

fn parse_routing_policy(spec: &str) -> Result<RoutingPolicy, String> {
    let (mode, max_fallback_attempts) = spec
        .split_once(':')
        .map_or((spec, None), |(mode, attempts)| (mode, Some(attempts)));
    let mut policy = match normalize_policy_mode(mode).as_str() {
        "affinity-first" | "affinity" => RoutingPolicy::affinity_first(),
        "random" => RoutingPolicy::random(),
        "strict-affinity" | "strict" | "no-fallback" => RoutingPolicy::strict_affinity(),
        _ => {
            return Err(format!(
                "invalid remote routing policy mode {mode}; expected affinity-first, random, or strict-affinity"
            ))
        }
    };

    if let Some(max_fallback_attempts) = max_fallback_attempts {
        let attempts = max_fallback_attempts.parse::<usize>().map_err(|error| {
            format!("invalid max fallback attempts {max_fallback_attempts}: {error}")
        })?;
        policy = policy.with_max_fallback_attempts(attempts);
    }

    Ok(policy)
}

fn normalize_policy_mode(mode: &str) -> String {
    mode.trim().to_ascii_lowercase().replace('_', "-")
}

fn non_zero_duration(duration_ms: u64) -> Option<Duration> {
    if duration_ms == 0 {
        return None;
    }

    Some(Duration::from_millis(duration_ms))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn server_mode_parses_known_modes() {
        assert_eq!("pipeline".parse::<ServerMode>(), Ok(ServerMode::Pipeline));
        assert_eq!("stage".parse::<ServerMode>(), Ok(ServerMode::Stage));
        assert_eq!("all".parse::<ServerMode>(), Ok(ServerMode::All));
    }

    #[test]
    fn server_mode_rejects_unknown_modes() {
        assert!("unknown".parse::<ServerMode>().is_err());
    }

    #[test]
    fn stage_id_parser_trims_and_ignores_empty_entries() {
        assert_eq!(
            parse_stage_ids(" resolution:v1, ,linking:v1,"),
            vec!["resolution:v1".to_string(), "linking:v1".to_string()]
        );
    }

    #[test]
    fn remote_target_parser_accepts_default_http_targets() {
        assert_eq!(
            parse_remote_targets("resolution=cymbal-resolution.default.svc.cluster.local:50051")
                .unwrap(),
            vec![RemoteStageTarget::new(
                "resolution",
                "cymbal-resolution.default.svc.cluster.local",
                50051
            )]
        );
    }

    #[test]
    fn remote_target_parser_accepts_explicit_schemes() {
        assert_eq!(
            parse_remote_targets("resolution=https://cymbal-resolution:50051").unwrap(),
            vec![RemoteStageTarget::with_scheme(
                "resolution",
                "cymbal-resolution",
                50051,
                "https"
            )]
        );
    }

    #[test]
    fn remote_stage_route_parser_trims_routes() {
        assert_eq!(
            parse_remote_stage_routes(" resolution:v1 = resolution , linking:v1=linking ").unwrap(),
            vec![
                ("resolution:v1".to_string(), "resolution".to_string()),
                ("linking:v1".to_string(), "linking".to_string())
            ]
        );
    }

    #[test]
    fn derive_remote_stage_routes_uses_target_name_as_stage_id() {
        let targets = vec![
            RemoteStageTarget::new("resolution:v1", "resolution.svc", 50051),
            RemoteStageTarget::new("linking:v1", "linking.svc", 50051),
        ];

        assert_eq!(
            derive_remote_stage_routes_from_targets(&targets),
            vec![
                ("resolution:v1".to_string(), "resolution:v1".to_string()),
                ("linking:v1".to_string(), "linking:v1".to_string()),
            ]
        );
    }

    #[test]
    fn resolve_remote_stage_routes_prefers_explicit_env() {
        let targets = vec![RemoteStageTarget::new(
            "resolution:v1",
            "resolution.svc",
            50051,
        )];

        // Explicit `CYMBAL_REMOTE_STAGES` should win even when targets exist —
        // operators may need to point one stage at a target with a different name.
        let resolved = resolve_remote_stage_routes("grouping:v1=resolution:v1", &targets).unwrap();
        assert_eq!(
            resolved,
            vec![("grouping:v1".to_string(), "resolution:v1".to_string())]
        );
    }

    #[test]
    fn resolve_remote_stage_routes_falls_back_to_target_derivation() {
        let targets = vec![
            RemoteStageTarget::new("resolution:v1", "resolution.svc", 50051),
            RemoteStageTarget::new("linking:v1", "linking.svc", 50051),
        ];

        let resolved = resolve_remote_stage_routes("", &targets).unwrap();
        assert_eq!(
            resolved,
            vec![
                ("resolution:v1".to_string(), "resolution:v1".to_string()),
                ("linking:v1".to_string(), "linking:v1".to_string()),
            ]
        );
    }

    #[test]
    fn resolve_remote_stage_routes_returns_empty_when_no_targets_and_no_env() {
        let resolved = resolve_remote_stage_routes("", &[]).unwrap();
        assert!(resolved.is_empty());
    }

    #[test]
    fn resolve_remote_stage_routes_propagates_parse_errors() {
        // Malformed explicit env should bubble up, not silently fall back to
        // derivation — otherwise a typo could quietly turn into the wrong topology.
        let result = resolve_remote_stage_routes("not-a-mapping", &[]);
        assert!(result.is_err());
    }

    #[test]
    fn stage_item_limit_parser_accepts_stage_overrides() {
        assert_eq!(
            parse_stage_item_limits(" resolution:v1 = 32 , linking:v1=4 ").unwrap(),
            vec![
                ("resolution:v1".to_string(), 32),
                ("linking:v1".to_string(), 4)
            ]
        );
    }

    #[test]
    fn stage_item_limit_parser_rejects_zero_limits() {
        assert!(parse_stage_item_limits("resolution:v1=0").is_err());
    }

    #[test]
    fn remote_routing_config_uses_conservative_stage_defaults() {
        let routing = default_remote_routing_config();

        assert_eq!(
            routing.policy_for_stage(RESOLUTION_STAGE_ID),
            RoutingPolicy::affinity_first()
        );
        assert_eq!(
            routing.policy_for_stage(GROUPING_STAGE_ID),
            RoutingPolicy::affinity_first()
        );
        assert_eq!(
            routing.policy_for_stage(LINKING_STAGE_ID),
            RoutingPolicy::strict_affinity()
        );
        assert_eq!(
            routing.policy_for_stage(ALERTING_STAGE_ID),
            RoutingPolicy::strict_affinity()
        );
    }

    #[test]
    fn emergency_random_remote_routing_config_disables_affinity_fallback_and_load_demotions() {
        let routing = emergency_random_remote_routing_config();
        let emergency_policy = RoutingPolicy::random().with_max_fallback_attempts(0);

        assert!(!routing.use_observed_load());
        assert_eq!(
            routing.policy_for_stage(RESOLUTION_STAGE_ID),
            emergency_policy
        );
        assert_eq!(
            routing.policy_for_stage(GROUPING_STAGE_ID),
            emergency_policy
        );
        assert_eq!(routing.policy_for_stage(LINKING_STAGE_ID), emergency_policy);
        assert_eq!(
            routing.policy_for_stage(ALERTING_STAGE_ID),
            emergency_policy
        );
    }

    #[test]
    fn remote_routing_policy_parser_accepts_modes_and_fallback_limits() {
        assert_eq!(
            parse_remote_routing_policies(
                " resolution:v1 = affinity-first:2 , linking:v1 = strict-affinity , alerting:v1=random "
            )
            .unwrap(),
            vec![
                (
                    RESOLUTION_STAGE_ID.to_string(),
                    RoutingPolicy::affinity_first().with_max_fallback_attempts(2)
                ),
                (LINKING_STAGE_ID.to_string(), RoutingPolicy::strict_affinity()),
                (ALERTING_STAGE_ID.to_string(), RoutingPolicy::random())
            ]
        );
    }

    #[test]
    fn remote_routing_policy_parser_rejects_unknown_modes() {
        assert!(parse_remote_routing_policies("resolution:v1=sticky").is_err());
    }
}
