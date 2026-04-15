use k8s_openapi::api::apps::v1::ReplicaSet;
use k8s_openapi::api::core::v1::Pod;
use kube::api::Api;
use kube::Client;

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
