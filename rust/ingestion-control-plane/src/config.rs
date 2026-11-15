use std::collections::HashMap;
use std::str::FromStr;

use anyhow::Context;
use envconfig::Envconfig;
use personhog_coordination::types::ClusterEndpoint;
use serde::Deserialize;

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

    /// Messages scanned per synchronous browse request while filling a page
    /// of matches; a rarely-matching filter stops here and resumes from the
    /// returned cursor on the next request.
    #[envconfig(default = "25000")]
    pub browse_scan_message_count: u64,

    #[envconfig(default = "10")]
    pub browse_deadline_secs: u64,

    /// Kafka transfers full records even though browsing only returns
    /// headers, so bound the bytes fetched per request. 256 MiB by default.
    #[envconfig(default = "268435456")]
    pub browse_max_fetch_bytes: u64,

    /// Concurrent synchronous browse requests; more are rejected with 429.
    #[envconfig(default = "3")]
    pub browse_max_concurrent: usize,

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

    #[envconfig(from = "PARITY_MONITOR_URL")]
    pub parity_monitor_url: Option<String>,

    #[envconfig(default = "10000")]
    pub kafka_metadata_timeout_ms: u64,

    #[envconfig(default = "1000")]
    pub kafka_fetch_poll_timeout_ms: u64,

    /// Comma-separated etcd endpoints for the etcd explorer and personhog
    /// topology tools. Empty disables both tools.
    #[envconfig(from = "ETCD_ENDPOINTS", default = "")]
    pub etcd_endpoints: String,

    /// Comma-separated key prefixes the etcd explorer may read and write.
    /// Every operation's key must fall under one of them.
    #[envconfig(from = "ETCD_ALLOWED_PREFIXES", default = "/")]
    pub etcd_allowed_prefixes: String,

    /// Key prefix the personhog coordination state lives under; must match
    /// the personhog services' `ETCD_PREFIX`.
    #[envconfig(from = "PERSONHOG_ETCD_PREFIX", default = "/personhog/")]
    pub personhog_etcd_prefix: String,

    /// Versioned S3 bucket that keeps a copy of `config/changelog` after
    /// every change; empty disables backups and restore.
    #[envconfig(from = "CHANGELOG_BACKUP_BUCKET", default = "")]
    pub changelog_backup_bucket: String,

    /// The personhog changelog's Kafka cluster; unset means `KAFKA_HOSTS`.
    #[envconfig(from = "PERSONHOG_KAFKA_HOSTS")]
    pub personhog_kafka_hosts: Option<String>,

    /// TLS for `PERSONHOG_KAFKA_HOSTS`; unset means `KAFKA_TLS`.
    #[envconfig(from = "PERSONHOG_KAFKA_TLS")]
    pub personhog_kafka_tls: Option<bool>,

    /// Clusters the changelog can live on, as JSON `{"name": {"hosts": "...", "tls": bool}}`.
    #[envconfig(from = "CHANGELOG_KAFKA_CLUSTERS", default = "")]
    pub changelog_kafka_clusters: String,

    /// Allows migrations onto another cluster. An older router's coordinator drops the
    /// cluster at the flip, and an older leader, writer or relay ignores it.
    #[envconfig(from = "PERSONHOG_CROSS_CLUSTER_MIGRATIONS", default = "false")]
    pub personhog_cross_cluster_migrations: bool,

    /// Per-phase handoff deadline used to flag stuck handoffs; must match
    /// the coordinator's `COORDINATOR_HANDOFF_DEADLINE_SECS` to agree with
    /// its cancellation decisions.
    #[envconfig(from = "PERSONHOG_HANDOFF_DEADLINE_SECS", default = "120")]
    pub personhog_handoff_deadline_secs: u64,

    /// Warming-phase deadline, mirroring `COORDINATOR_WARMING_DEADLINE_SECS`.
    #[envconfig(from = "PERSONHOG_WARMING_DEADLINE_SECS", default = "1800")]
    pub personhog_warming_deadline_secs: u64,
}

/// One cluster in `CHANGELOG_KAFKA_CLUSTERS`; `tls` is required and unknown keys are
/// refused, so neither an omission nor a typo can drop TLS.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ClusterSpec {
    hosts: String,
    tls: bool,
}

impl ClusterSpec {
    fn endpoint(self, name: String) -> ClusterEndpoint {
        ClusterEndpoint {
            name,
            hosts: self.hosts,
            tls: self.tls,
        }
    }
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Self::init_from_env()
    }

    /// This config pointed at the personhog changelog's Kafka cluster.
    pub fn personhog_kafka(&self) -> Config {
        let mut config = self.clone();
        if let Some(hosts) = self
            .personhog_kafka_hosts
            .as_ref()
            .filter(|h| !h.is_empty())
        {
            config.kafka_hosts = hosts.clone();
        }
        if let Some(tls) = self.personhog_kafka_tls {
            config.kafka_tls = tls;
        }
        config
    }

    fn changelog_clusters(&self) -> anyhow::Result<HashMap<String, ClusterSpec>> {
        match self.changelog_kafka_clusters.trim() {
            "" => Ok(HashMap::new()),
            spec => serde_json::from_str(spec)
                .context("CHANGELOG_KAFKA_CLUSTERS is not a valid cluster map"),
        }
    }

    pub fn changelog_cluster_names(&self) -> anyhow::Result<Vec<String>> {
        let mut names: Vec<String> = self.changelog_clusters()?.into_keys().collect();
        names.sort();
        Ok(names)
    }

    pub fn changelog_cluster(&self, name: &str) -> anyhow::Result<ClusterEndpoint> {
        let spec = self
            .changelog_clusters()?
            .remove(name)
            .with_context(|| format!("cluster {name:?} is not in CHANGELOG_KAFKA_CLUSTERS"))?;
        Ok(spec.endpoint(name.to_string()))
    }

    pub fn current_changelog_cluster(&self) -> anyhow::Result<Option<ClusterEndpoint>> {
        let current = self.personhog_kafka();
        Ok(self
            .changelog_clusters()?
            .into_iter()
            .find(|(_, spec)| spec.hosts == current.kafka_hosts && spec.tls == current.kafka_tls)
            .map(|(name, spec)| spec.endpoint(name)))
    }

    pub fn changelog_kafka(&self, cluster: Option<&ClusterEndpoint>) -> Config {
        let mut config = self.personhog_kafka();
        if let Some(cluster) = cluster {
            config.kafka_hosts = cluster.hosts.clone();
            config.kafka_tls = cluster.tls;
        }
        config
    }

    pub fn etcd_endpoint_list(&self) -> Vec<String> {
        self.etcd_endpoints
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .collect()
    }

    pub fn etcd_allowed_prefix_list(&self) -> Vec<String> {
        self.etcd_allowed_prefixes
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .collect()
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
    fn the_personhog_cluster_overrides_only_what_is_set() {
        let mut config = Config::init_with_defaults().expect("config defaults are valid");
        config.kafka_hosts = "main:9092".to_string();
        config.kafka_tls = false;
        let unset = config.personhog_kafka();
        assert_eq!(
            (unset.kafka_hosts.as_str(), unset.kafka_tls),
            ("main:9092", false)
        );

        config.personhog_kafka_hosts = Some("personhog:9094".to_string());
        config.personhog_kafka_tls = Some(true);
        let set = config.personhog_kafka();
        assert_eq!(
            (set.kafka_hosts.as_str(), set.kafka_tls),
            ("personhog:9094", true)
        );

        config.changelog_kafka_clusters =
            r#"{"dedicated": {"hosts": "d:9092", "tls": false}}"#.to_string();
        let dedicated = config.changelog_cluster("dedicated").unwrap();
        let moved = config.changelog_kafka(Some(&dedicated));
        assert_eq!(
            (moved.kafka_hosts.as_str(), moved.kafka_tls),
            ("d:9092", false)
        );
        assert!(config.changelog_cluster("unknown").is_err());
        config.changelog_kafka_clusters =
            r#"{"dedicated": {"hosts": "d:9092", "tsl": true}}"#.to_string();
        assert!(config.changelog_cluster("dedicated").is_err());
        config.changelog_kafka_clusters = r#"{"dedicated": {"hosts": "d:9092"}}"#.to_string();
        assert!(config.changelog_cluster("dedicated").is_err());
    }

    #[test]
    fn the_current_cluster_is_the_entry_matching_the_personhog_hosts() {
        let mut config = Config::init_with_defaults().expect("config defaults are valid");
        config.personhog_kafka_hosts = Some("ingestion:9092".to_string());
        config.personhog_kafka_tls = Some(true);
        config.changelog_kafka_clusters = r#"{
            "ingestion": {"hosts": "ingestion:9092", "tls": true},
            "dedicated": {"hosts": "dedicated:9092", "tls": true}
        }"#
        .to_string();
        assert_eq!(
            config.current_changelog_cluster().unwrap(),
            Some(config.changelog_cluster("ingestion").unwrap())
        );

        config.personhog_kafka_tls = Some(false);
        assert_eq!(config.current_changelog_cluster().unwrap(), None);
    }

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
