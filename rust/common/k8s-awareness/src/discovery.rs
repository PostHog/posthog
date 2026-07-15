use std::collections::BTreeMap;

use k8s_openapi::api::apps::v1::ReplicaSet;
use k8s_openapi::api::core::v1::Pod;
use kube::api::{Api, ListParams};
use kube::Client;
use serde::Serialize;

use crate::types::{ControllerKind, ControllerRef, PodInfo};

#[derive(Debug, thiserror::Error)]
pub enum DiscoveryError {
    #[error("pod {0} not found")]
    PodNotFound(String),
    #[error("pod {0} has no owner references")]
    NoOwnerReferences(String),
    #[error("unsupported owner kind for pod {pod}: {kind}")]
    UnsupportedOwner { pod: String, kind: String },
    #[error("replicaset {0} has no Deployment owner")]
    ReplicaSetNoDeploymentOwner(String),
    #[error("pod {0} missing generation label")]
    MissingGenerationLabel(String),
    #[error("kubernetes API error: {0}")]
    Kube(#[from] kube::Error),
}

/// Discover which controller owns a pod by walking ownerReferences.
///
/// For Deployments: pod → ReplicaSet → Deployment
/// For StatefulSets: pod → StatefulSet (direct)
///
/// Returns the controller reference and the pod's generation hash.
pub async fn discover_controller(
    client: &Client,
    namespace: &str,
    pod_name: &str,
) -> Result<PodInfo, DiscoveryError> {
    let pods: Api<Pod> = Api::namespaced(client.clone(), namespace);
    let pod = pods.get(pod_name).await.map_err(|e| {
        if is_not_found(&e) {
            DiscoveryError::PodNotFound(pod_name.to_string())
        } else {
            DiscoveryError::Kube(e)
        }
    })?;

    let owner_refs = pod.metadata.owner_references.as_deref().unwrap_or_default();

    if owner_refs.is_empty() {
        return Err(DiscoveryError::NoOwnerReferences(pod_name.to_string()));
    }

    let labels = pod.metadata.labels.as_ref();

    // StatefulSet: direct ownership
    if let Some(ss_owner) = owner_refs.iter().find(|r| r.kind == "StatefulSet") {
        let generation = labels
            .and_then(|l| l.get("controller-revision-hash"))
            .cloned()
            .ok_or_else(|| DiscoveryError::MissingGenerationLabel(pod_name.to_string()))?;

        return Ok(PodInfo {
            controller: ControllerRef {
                kind: ControllerKind::StatefulSet,
                name: ss_owner.name.clone(),
            },
            generation,
        });
    }

    // ReplicaSet → Deployment
    if let Some(rs_owner) = owner_refs.iter().find(|r| r.kind == "ReplicaSet") {
        let rs_api: Api<ReplicaSet> = Api::namespaced(client.clone(), namespace);
        let rs = rs_api.get(&rs_owner.name).await?;

        let rs_owners = rs.metadata.owner_references.as_deref().unwrap_or_default();

        let deploy_owner = rs_owners
            .iter()
            .find(|r| r.kind == "Deployment")
            .ok_or_else(|| DiscoveryError::ReplicaSetNoDeploymentOwner(rs_owner.name.clone()))?;

        let generation = labels
            .and_then(|l| l.get("pod-template-hash"))
            .cloned()
            .ok_or_else(|| DiscoveryError::MissingGenerationLabel(pod_name.to_string()))?;

        return Ok(PodInfo {
            controller: ControllerRef {
                kind: ControllerKind::Deployment,
                name: deploy_owner.name.clone(),
            },
            generation,
        });
    }

    let kind = owner_refs
        .first()
        .map(|r| r.kind.clone())
        .unwrap_or_else(|| "unknown".to_string());
    Err(DiscoveryError::UnsupportedOwner {
        pod: pod_name.to_string(),
        kind,
    })
}

fn is_not_found(e: &kube::Error) -> bool {
    matches!(e, kube::Error::Api(resp) if resp.code == 404)
}

/// A pod matched by a label selector, with the metadata an operator-facing
/// tool cares about.
#[derive(Debug, Clone, Serialize)]
pub struct DiscoveredPod {
    pub name: String,
    pub namespace: String,
    pub ip: Option<String>,
    pub node: Option<String>,
    pub phase: Option<String>,
    pub ready: bool,
    pub started_at: Option<String>,
    pub restarts: i32,
    pub labels: BTreeMap<String, String>,
}

impl From<Pod> for DiscoveredPod {
    fn from(pod: Pod) -> Self {
        let status = pod.status.unwrap_or_default();
        let ready = status
            .conditions
            .as_deref()
            .unwrap_or_default()
            .iter()
            .any(|c| c.type_ == "Ready" && c.status == "True");
        let restarts = status
            .container_statuses
            .as_deref()
            .unwrap_or_default()
            .iter()
            .map(|c| c.restart_count)
            .sum();
        Self {
            name: pod.metadata.name.unwrap_or_default(),
            namespace: pod.metadata.namespace.unwrap_or_default(),
            ip: status.pod_ip,
            node: pod.spec.and_then(|s| s.node_name),
            phase: status.phase,
            ready,
            started_at: status.start_time.map(|t| t.0.to_rfc3339()),
            restarts,
            labels: pod.metadata.labels.unwrap_or_default(),
        }
    }
}

/// List pods in a namespace matching a label selector (e.g. `app=my-service`).
pub async fn list_pods_by_selector(
    client: &Client,
    namespace: &str,
    selector: &str,
) -> Result<Vec<DiscoveredPod>, kube::Error> {
    let pods: Api<Pod> = Api::namespaced(client.clone(), namespace);
    let list = pods.list(&ListParams::default().labels(selector)).await?;
    Ok(list.items.into_iter().map(DiscoveredPod::from).collect())
}

/// Fetch a single pod by name, returning `None` when it doesn't exist.
pub async fn get_pod(
    client: &Client,
    namespace: &str,
    name: &str,
) -> Result<Option<DiscoveredPod>, kube::Error> {
    let pods: Api<Pod> = Api::namespaced(client.clone(), namespace);
    match pods.get(name).await {
        Ok(pod) => Ok(Some(DiscoveredPod::from(pod))),
        Err(e) if is_not_found(&e) => Ok(None),
        Err(e) => Err(e),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_pod_fields_to_discovered_pod() {
        let pod: Pod = serde_json::from_value(serde_json::json!({
            "metadata": {
                "name": "consumer-abc",
                "namespace": "ingestion-analytics-main",
                "labels": {"app": "ingestion-analytics-main", "pod-template-hash": "x1"}
            },
            "spec": {"nodeName": "node-1", "containers": []},
            "status": {
                "phase": "Running",
                "podIP": "10.0.0.7",
                "startTime": "2026-07-14T08:00:00Z",
                "conditions": [{"type": "Ready", "status": "True"}],
                "containerStatuses": [
                    {"name": "c", "restartCount": 3, "ready": true, "image": "i", "imageID": "",
                     "state": {}, "lastState": {}}
                ]
            }
        }))
        .expect("valid pod fixture");

        let discovered = DiscoveredPod::from(pod);
        assert_eq!(discovered.name, "consumer-abc");
        assert_eq!(discovered.namespace, "ingestion-analytics-main");
        assert_eq!(discovered.ip.as_deref(), Some("10.0.0.7"));
        assert_eq!(discovered.node.as_deref(), Some("node-1"));
        assert_eq!(discovered.phase.as_deref(), Some("Running"));
        assert!(discovered.ready);
        assert_eq!(discovered.restarts, 3);
        assert_eq!(
            discovered.labels.get("app").map(String::as_str),
            Some("ingestion-analytics-main")
        );
        assert!(discovered.started_at.is_some());
    }

    #[test]
    fn missing_status_yields_not_ready_pod() {
        let pod: Pod = serde_json::from_value(serde_json::json!({
            "metadata": {"name": "pending-pod"}
        }))
        .expect("valid pod fixture");

        let discovered = DiscoveredPod::from(pod);
        assert_eq!(discovered.name, "pending-pod");
        assert!(!discovered.ready);
        assert_eq!(discovered.ip, None);
        assert_eq!(discovered.restarts, 0);
    }
}
