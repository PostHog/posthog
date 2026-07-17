use std::collections::BTreeMap;

use anyhow::{anyhow, Context};
use k8s_awareness::DiscoveredPod;
use kube::Client;
use tokio::sync::OnceCell;

use crate::config::{Config, PodDiscoveryMode};

/// Pseudo-namespace that static pods are listed and resolved under.
pub const STATIC_NAMESPACE: &str = "static";

/// A fixed proxy target used by static discovery (local testing), mirroring
/// the ingestion-consumer's static worker discovery.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StaticPod {
    pub name: String,
    /// `host:port` of the pod's debug API.
    pub address: String,
}

/// Discovers ingestion-consumer pods. In `kubernetes` mode the client is
/// created lazily on first use so the service still starts (and the Kafka
/// tools still work) outside a cluster; in `static` mode a fixed list of
/// `name=host:port` targets is served instead.
pub enum PodDiscovery {
    Kubernetes(OnceCell<Client>),
    Static(Vec<StaticPod>),
}

impl PodDiscovery {
    pub fn from_config(config: &Config) -> anyhow::Result<Self> {
        match config.pod_discovery_mode {
            PodDiscoveryMode::Kubernetes => Ok(Self::Kubernetes(OnceCell::new())),
            PodDiscoveryMode::Static => Ok(Self::Static(parse_static_pods(&config.static_pods)?)),
        }
    }

    async fn client(cell: &OnceCell<Client>) -> anyhow::Result<&Client> {
        cell.get_or_try_init(|| async {
            Client::try_default().await.context(
                "no Kubernetes environment detected (in-cluster service account or kubeconfig)",
            )
        })
        .await
    }

    pub async fn list_pods(&self, config: &Config) -> anyhow::Result<Vec<DiscoveredPod>> {
        match self {
            Self::Static(static_pods) => Ok(static_pods
                .iter()
                .map(|static_pod| {
                    let host = static_pod
                        .address
                        .rsplit_once(':')
                        .map(|(host, _)| host)
                        .unwrap_or(&static_pod.address);
                    DiscoveredPod {
                        name: static_pod.name.clone(),
                        namespace: STATIC_NAMESPACE.to_string(),
                        ip: Some(host.to_string()),
                        node: None,
                        phase: Some("Static".to_string()),
                        ready: true,
                        started_at: None,
                        restarts: 0,
                        labels: BTreeMap::from([("app".to_string(), "static".to_string())]),
                    }
                })
                .collect()),
            Self::Kubernetes(cell) => {
                let client = Self::client(cell).await?;
                let mut pods = Vec::new();
                for target in config.pod_targets() {
                    let mut found = k8s_awareness::list_pods_by_selector(
                        client,
                        &target.namespace,
                        &target.selector,
                    )
                    .await
                    .with_context(|| {
                        format!(
                            "list pods for selector '{}' in namespace '{}'",
                            target.selector, target.namespace
                        )
                    })?;
                    pods.append(&mut found);
                }
                pods.sort_by(|a, b| {
                    (a.namespace.as_str(), a.name.as_str())
                        .cmp(&(b.namespace.as_str(), b.name.as_str()))
                });
                pods.dedup_by(|a, b| a.namespace == b.namespace && a.name == b.name);
                Ok(pods)
            }
        }
    }

    /// Resolve a namespace-qualified pod to the `host:port` of its debug API.
    /// In kubernetes mode the namespace must be one of the configured targets
    /// and the pod is fetched fresh from the API and must match one of that
    /// namespace's label selectors — the debug proxy must never dial a
    /// client-chosen host. Static pods live under the `static` pseudo-namespace.
    pub async fn resolve_proxy_target(
        &self,
        config: &Config,
        namespace: &str,
        name: &str,
    ) -> anyhow::Result<Option<String>> {
        match self {
            Self::Static(static_pods) => Ok(static_pods
                .iter()
                .filter(|_| namespace == STATIC_NAMESPACE)
                .find(|static_pod| static_pod.name == name)
                .map(|static_pod| static_pod.address.clone())),
            Self::Kubernetes(cell) => {
                let targets = config.pod_targets();
                let selectors: Vec<&str> = targets
                    .iter()
                    .filter(|t| t.namespace == namespace)
                    .map(|t| t.selector.as_str())
                    .collect();
                // Only namespaces we are configured to discover are dialable.
                if selectors.is_empty() {
                    return Ok(None);
                }
                let client = Self::client(cell).await?;
                let pod = k8s_awareness::get_pod(client, namespace, name)
                    .await
                    .with_context(|| format!("fetch pod '{name}' in '{namespace}'"))?;
                Ok(pod
                    .filter(|p| matches_any_selector(&p.labels, &selectors))
                    .and_then(|p| p.ip)
                    .map(|ip| format!("{ip}:{}", config.debug_port)))
            }
        }
    }
}

fn parse_static_pods(raw: &str) -> anyhow::Result<Vec<StaticPod>> {
    raw.split(',')
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .map(|entry| {
            let (name, address) = entry.split_once('=').ok_or_else(|| {
                anyhow!("invalid STATIC_PODS entry '{entry}' (expected name=host:port)")
            })?;
            let (name, address) = (name.trim(), address.trim());
            if name.is_empty() || address.is_empty() {
                return Err(anyhow!(
                    "invalid STATIC_PODS entry '{entry}' (expected name=host:port)"
                ));
            }
            Ok(StaticPod {
                name: name.to_string(),
                address: address.to_string(),
            })
        })
        .collect()
}

/// Each configured selector is a single `key=value` pair.
fn matches_any_selector(labels: &BTreeMap<String, String>, selectors: &[&str]) -> bool {
    selectors.iter().any(|selector| {
        selector.split_once('=').is_some_and(|(key, value)| {
            labels.get(key.trim()).map(String::as_str) == Some(value.trim())
        })
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn labels(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn matches_when_any_selector_matches() {
        let pod_labels = labels(&[("app", "ingestion-analytics-main"), ("team", "ingestion")]);
        let selectors = [
            "app=ingestion-analytics-async",
            "app=ingestion-analytics-main",
        ];
        assert!(matches_any_selector(&pod_labels, &selectors));
    }

    #[test]
    fn rejects_unmatched_labels_and_malformed_selectors() {
        let pod_labels = labels(&[("app", "some-other-service")]);
        assert!(!matches_any_selector(
            &pod_labels,
            &["app=ingestion-analytics-main"]
        ));
        assert!(!matches_any_selector(&pod_labels, &["no-equals"]));
    }

    #[test]
    fn parses_static_pod_entries() {
        let pods = parse_static_pods("local=127.0.0.1:3301, other=10.0.0.5:3301").unwrap();
        assert_eq!(
            pods,
            vec![
                StaticPod {
                    name: "local".to_string(),
                    address: "127.0.0.1:3301".to_string(),
                },
                StaticPod {
                    name: "other".to_string(),
                    address: "10.0.0.5:3301".to_string(),
                },
            ]
        );
    }

    #[test]
    fn rejects_malformed_static_pod_entries() {
        assert!(parse_static_pods("just-an-address:3301").is_err());
    }

    #[tokio::test]
    async fn static_discovery_lists_and_resolves_without_k8s() {
        let discovery = PodDiscovery::Static(parse_static_pods("local=127.0.0.1:3301").unwrap());
        let config = test_config();

        let pods = discovery.list_pods(&config).await.unwrap();
        assert_eq!(pods.len(), 1);
        assert_eq!(pods[0].name, "local");
        assert!(pods[0].ready);

        let target = discovery
            .resolve_proxy_target(&config, STATIC_NAMESPACE, "local")
            .await
            .unwrap();
        assert_eq!(target.as_deref(), Some("127.0.0.1:3301"));
        let missing = discovery
            .resolve_proxy_target(&config, STATIC_NAMESPACE, "unknown")
            .await
            .unwrap();
        assert_eq!(missing, None);
    }

    fn test_config() -> Config {
        // envconfig has no direct "from defaults" constructor without env;
        // init from the current environment, which applies the defaults.
        Config::init_with_defaults().expect("config defaults are valid")
    }
}
