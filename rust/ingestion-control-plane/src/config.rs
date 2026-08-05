use std::str::FromStr;

use envconfig::Envconfig;

/// How consumer pods are discovered, mirroring the ingestion-consumer's
/// typed `DiscoveryMode`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum PodDiscoveryMode {
    /// Query the Kubernetes API for pods matching the configured targets.
    #[default]
    Kubernetes,
    /// Fixed list from `STATIC_PODS` (local testing).
    Static,
}

impl FromStr for PodDiscoveryMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "kubernetes" | "k8s" => Ok(PodDiscoveryMode::Kubernetes),
            "static" => Ok(PodDiscoveryMode::Static),
            other => Err(format!(
                "unknown pod discovery mode '{other}' (expected 'kubernetes' or 'static')"
            )),
        }
    }
}

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "0.0.0.0")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3305")]
    pub port: u16,

    #[envconfig(default = "localhost:19092")]
    pub kafka_hosts: String,

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    #[envconfig(from = "KAFKA_CLIENT_RACK")]
    pub kafka_client_rack: Option<String>,

    /// Topics and consumer groups are discovered from the cluster by prefix
    /// instead of being configured per environment; a group is associated
    /// with a topic when it has committed offsets on it. The prefixes also
    /// bound which groups/topics the API may scan.
    #[envconfig(default = "ingestion-")]
    pub topic_prefix: String,

    #[envconfig(default = "ingestion-")]
    pub group_prefix: String,

    /// Topology (topics, groups, partitions) changes rarely; discovered
    /// targets are cached this long.
    #[envconfig(default = "300")]
    pub discovery_cache_ttl_secs: u64,

    /// The lag overview triggers broker-wide offset/watermark scans; results
    /// are cached (with single-flight refresh) this long so repeated requests
    /// coalesce instead of multiplying broker load.
    #[envconfig(default = "15")]
    pub overview_cache_ttl_secs: u64,

    /// Read-replica Postgres URL for token -> team_id resolution. When unset,
    /// resolution is disabled and analyses report `team_id: null`.
    #[envconfig(from = "DATABASE_URL")]
    pub database_url: Option<String>,

    #[envconfig(default = "2")]
    pub pg_max_connections: u32,

    #[envconfig(default = "10000")]
    pub analysis_message_count: u64,

    #[envconfig(default = "120")]
    pub analysis_deadline_secs: u64,

    /// Kafka transfers full records even though we only analyze headers, so
    /// bound the bytes fetched per analysis. 512 MiB by default.
    #[envconfig(default = "536870912")]
    pub analysis_max_fetch_bytes: u64,

    #[envconfig(default = "2")]
    pub analysis_max_concurrent_jobs: usize,

    /// `kubernetes` discovers consumer pods via the K8s API; `static` uses
    /// the fixed `STATIC_PODS` list (local testing, like the
    /// ingestion-consumer's static worker discovery).
    #[envconfig(default = "kubernetes")]
    pub pod_discovery_mode: PodDiscoveryMode,

    /// Comma-separated `name=host:port` entries used by static discovery.
    #[envconfig(default = "local=127.0.0.1:3301")]
    pub static_pods: String,

    /// Default namespace for `POD_LABEL_SELECTORS` entries without an
    /// explicit `namespace/` prefix.
    #[envconfig(default = "posthog")]
    pub k8s_namespace: String,

    /// Comma-separated pod label selectors, one per consumer deployment.
    /// Entries may be namespace-qualified (`namespace/key=value`) since each
    /// ingestion lane runs in its own namespace; bare `key=value` entries use
    /// `K8S_NAMESPACE`.
    #[envconfig(
        default = "ingestion-analytics-main/app=ingestion-analytics-main,ingestion-analytics-async/app=ingestion-analytics-async"
    )]
    pub pod_label_selectors: String,

    /// Port the ingestion-consumer serves its debug API on.
    #[envconfig(default = "3301")]
    pub debug_port: u16,

    /// Secret presented as `X-Debug-Api-Secret` on every proxied debug API
    /// request. Must match the consumers' `DEBUG_API_SECRET` (the AWS secret
    /// `ingestion-consumer-debug-api-secrets` in each environment); the
    /// consumer rejects unauthenticated requests, so leaving this unset only
    /// works against local consumers running without auth.
    #[envconfig(from = "DEBUG_API_SECRET")]
    pub debug_api_secret: Option<String>,

    #[envconfig(default = "10000")]
    pub kafka_metadata_timeout_ms: u64,

    #[envconfig(default = "1000")]
    pub kafka_fetch_poll_timeout_ms: u64,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Self::init_from_env()
    }

    pub fn pod_targets(&self) -> Vec<PodTarget> {
        self.pod_label_selectors
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(|entry| match entry.split_once('/') {
                // Only treat the prefix as a namespace when it is a valid
                // namespace name. Label keys may themselves contain `/`
                // (`app.kubernetes.io/name=x`), but their prefixes are DNS
                // subdomains with dots, which namespace names cannot contain.
                // A selector with a prefixed label key must be written
                // namespace-qualified (`ns/team.example.com/role=x`).
                Some((namespace, selector)) if is_valid_namespace(namespace.trim()) => PodTarget {
                    namespace: namespace.trim().to_string(),
                    selector: selector.trim().to_string(),
                },
                _ => PodTarget {
                    namespace: self.k8s_namespace.clone(),
                    selector: entry.to_string(),
                },
            })
            .collect()
    }
}

/// RFC 1123 label: lowercase alphanumerics and `-`, no leading/trailing `-`.
fn is_valid_namespace(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 63
        && !s.starts_with('-')
        && !s.ends_with('-')
        && s.chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

/// One pod-discovery target: a label selector scoped to a namespace.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PodTarget {
    pub namespace: String,
    pub selector: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pod_targets_support_namespace_prefix_with_default_fallback() {
        let mut config = Config::init_with_defaults().expect("config defaults are valid");
        config.k8s_namespace = "default-ns".to_string();
        config.pod_label_selectors =
            "ingestion-analytics-main/app=ingestion-analytics-main, app=bare-selector".to_string();

        assert_eq!(
            config.pod_targets(),
            vec![
                PodTarget {
                    namespace: "ingestion-analytics-main".to_string(),
                    selector: "app=ingestion-analytics-main".to_string(),
                },
                PodTarget {
                    namespace: "default-ns".to_string(),
                    selector: "app=bare-selector".to_string(),
                },
            ]
        );
    }

    #[test]
    fn prefixed_label_keys_are_not_mistaken_for_namespaces() {
        let mut config = Config::init_with_defaults().expect("config defaults are valid");
        config.k8s_namespace = "default-ns".to_string();
        config.pod_label_selectors =
            "app.kubernetes.io/name=consumer,my-ns/app.kubernetes.io/name=consumer".to_string();

        assert_eq!(
            config.pod_targets(),
            vec![
                PodTarget {
                    namespace: "default-ns".to_string(),
                    selector: "app.kubernetes.io/name=consumer".to_string(),
                },
                PodTarget {
                    namespace: "my-ns".to_string(),
                    selector: "app.kubernetes.io/name=consumer".to_string(),
                },
            ]
        );
    }
}
