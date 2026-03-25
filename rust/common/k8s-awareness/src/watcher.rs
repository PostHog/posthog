use std::collections::HashMap;
use std::sync::Arc;

use futures::StreamExt;
use k8s_openapi::api::apps::v1::{Deployment, ReplicaSet, StatefulSet};
use kube::api::{Api, ListParams};
use kube::runtime::watcher::{self, Config as WatcherConfig, Event};
use kube::Client;
use tokio::sync::RwLock;
use tokio_util::sync::CancellationToken;
use tracing::{debug, info, warn};

use crate::detection;
use crate::discovery::{self, DiscoveryError};
use crate::types::{ClusterIntent, ControllerKind, ControllerRef, DepartureReason, PodInfo};

#[derive(Debug, thiserror::Error)]
pub enum K8sAwarenessError {
    #[error("discovery failed: {0}")]
    Discovery(#[from] DiscoveryError),
    #[error("kubernetes API error: {0}")]
    Kube(#[from] kube::Error),
}

/// Manages K8s watchers for multiple controllers.
///
/// One assigner can serve consumers from N different Deployments/StatefulSets.
/// `K8sAwareness` auto-discovers each consumer's controller via ownerReferences
/// and starts a watcher for new controllers as they're discovered.
pub struct K8sAwareness {
    client: Client,
    namespace: String,
    controllers: Arc<RwLock<HashMap<ControllerRef, ClusterIntent>>>,
    watching: Arc<RwLock<HashMap<ControllerRef, CancellationToken>>>,
    cancel: CancellationToken,
}

impl K8sAwareness {
    pub fn new(client: Client, namespace: String, cancel: CancellationToken) -> Self {
        Self {
            client,
            namespace,
            controllers: Arc::new(RwLock::new(HashMap::new())),
            watching: Arc::new(RwLock::new(HashMap::new())),
            cancel,
        }
    }

    /// Discover which controller owns a pod and start watching it.
    ///
    /// Walks ownerReferences: pod → ReplicaSet → Deployment, or pod → StatefulSet.
    /// Starts a watcher for the controller if not already watching.
    pub async fn discover_controller(&self, pod_name: &str) -> Result<PodInfo, K8sAwarenessError> {
        let pod_info =
            discovery::discover_controller(&self.client, &self.namespace, pod_name).await?;

        self.ensure_watching(&pod_info.controller).await?;

        Ok(pod_info)
    }

    /// Classify why a member is departing based on its controller's current intent.
    ///
    /// Returns `DepartureReason::Unknown` if the controller isn't being watched.
    pub async fn classify_departure(
        &self,
        controller: &ControllerRef,
        generation: &str,
    ) -> DepartureReason {
        let controllers = self.controllers.read().await;
        match controllers.get(controller) {
            Some(intent) => detection::classify_departure(intent, generation),
            None => {
                warn!(
                    controller = %controller,
                    "no cluster intent available, returning Unknown"
                );
                DepartureReason::Unknown
            }
        }
    }

    /// Start watching a controller if not already watching.
    async fn ensure_watching(&self, controller: &ControllerRef) -> Result<(), K8sAwarenessError> {
        let mut watching = self.watching.write().await;
        if watching.contains_key(controller) {
            return Ok(());
        }

        let child_cancel = self.cancel.child_token();
        watching.insert(controller.clone(), child_cancel.clone());
        drop(watching);

        let controllers = Arc::clone(&self.controllers);
        let client = self.client.clone();
        let namespace = self.namespace.clone();
        let controller_ref = controller.clone();

        info!(controller = %controller_ref, "starting K8s watcher");

        tokio::spawn(async move {
            match controller_ref.kind {
                ControllerKind::Deployment => {
                    run_deployment_watcher(
                        &client,
                        &namespace,
                        &controller_ref,
                        &controllers,
                        child_cancel,
                    )
                    .await;
                }
                ControllerKind::StatefulSet => {
                    run_statefulset_watcher(
                        &client,
                        &namespace,
                        &controller_ref,
                        &controllers,
                        child_cancel,
                    )
                    .await;
                }
            }
        });

        Ok(())
    }
}

/// Watch a Deployment and update its ClusterIntent on changes.
async fn run_deployment_watcher(
    client: &Client,
    namespace: &str,
    controller: &ControllerRef,
    controllers: &Arc<RwLock<HashMap<ControllerRef, ClusterIntent>>>,
    cancel: CancellationToken,
) {
    let api: Api<Deployment> = Api::namespaced(client.clone(), namespace);
    let config = WatcherConfig::default().fields(&format!("metadata.name={}", controller.name));

    let stream = watcher::watcher(api, config);
    tokio::pin!(stream);

    loop {
        tokio::select! {
            _ = cancel.cancelled() => break,
            item = stream.next() => {
                match item {
                    Some(Ok(event)) => {
                        handle_deployment_event(
                            client,
                            namespace,
                            controller,
                            controllers,
                            event,
                        ).await;
                    }
                    Some(Err(e)) => {
                        warn!(
                            controller = %controller,
                            error = %e,
                            "deployment watcher error, stream will retry"
                        );
                    }
                    None => {
                        info!(controller = %controller, "deployment watcher stream ended");
                        break;
                    }
                }
            }
        }
    }
}

async fn handle_deployment_event(
    client: &Client,
    namespace: &str,
    controller: &ControllerRef,
    controllers: &Arc<RwLock<HashMap<ControllerRef, ClusterIntent>>>,
    event: Event<Deployment>,
) {
    let deploy = match event {
        Event::Apply(d) | Event::InitApply(d) => d,
        Event::Delete(_) => {
            info!(controller = %controller, "deployment deleted");
            let mut map = controllers.write().await;
            map.remove(controller);
            return;
        }
        Event::Init | Event::InitDone => return,
    };

    let spec = match &deploy.spec {
        Some(s) => s,
        None => return,
    };
    let status = deploy.status.as_ref();

    let desired_replicas = spec.replicas.unwrap_or(1) as u32;
    let generation = deploy.metadata.generation.unwrap_or(0);
    let observed_generation = status.and_then(|s| s.observed_generation).unwrap_or(0);
    let rollout_in_progress = generation != observed_generation;

    // Determine generations by inspecting owned ReplicaSets
    let (current_gen, target_gen) = if rollout_in_progress {
        match find_deployment_generations(client, namespace, &controller.name).await {
            Ok((current, target)) => (current, Some(target)),
            Err(e) => {
                warn!(
                    controller = %controller,
                    error = %e,
                    "failed to discover deployment generations during rollout"
                );
                (String::new(), None)
            }
        }
    } else {
        match find_active_generation(client, namespace, &controller.name).await {
            Ok(gen) => (gen, None),
            Err(e) => {
                debug!(
                    controller = %controller,
                    error = %e,
                    "failed to discover active generation"
                );
                (String::new(), None)
            }
        }
    };

    let mut map = controllers.write().await;
    // Only update previous_replicas when desired_replicas actually changes,
    // otherwise status-only events would overwrite it with the current value.
    let previous_replicas = map.get(controller).and_then(|prev| {
        if prev.desired_replicas != desired_replicas {
            Some(prev.desired_replicas)
        } else {
            prev.previous_replicas
        }
    });

    let intent = ClusterIntent {
        desired_replicas,
        previous_replicas,
        rollout_in_progress,
        current_generation: current_gen,
        target_generation: target_gen,
    };

    debug!(
        controller = %controller,
        desired_replicas = intent.desired_replicas,
        previous_replicas = ?intent.previous_replicas,
        rollout_in_progress = intent.rollout_in_progress,
        current_generation = %intent.current_generation,
        target_generation = ?intent.target_generation,
        "updated deployment cluster intent"
    );

    map.insert(controller.clone(), intent);
}

/// Find the current and target pod-template-hash during a Deployment rollout.
///
/// Lists ReplicaSets owned by the Deployment and identifies:
/// - target: the RS with the highest revision (the new one being scaled up)
/// - current: the RS with the second-highest revision that has replicas
async fn find_deployment_generations(
    client: &Client,
    namespace: &str,
    deployment_name: &str,
) -> Result<(String, String), kube::Error> {
    let rs_api: Api<ReplicaSet> = Api::namespaced(client.clone(), namespace);
    let rs_list = rs_api.list(&ListParams::default()).await?;

    // Collect (revision, pod-template-hash, replica_count) for owned RSes
    let mut owned: Vec<(u64, String, i32)> = Vec::new();

    for rs in &rs_list.items {
        let owners = rs.metadata.owner_references.as_deref().unwrap_or_default();
        if !owners
            .iter()
            .any(|o| o.kind == "Deployment" && o.name == deployment_name)
        {
            continue;
        }

        let revision = rs
            .metadata
            .annotations
            .as_ref()
            .and_then(|a| a.get("deployment.kubernetes.io/revision"))
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(0);

        let hash = rs
            .metadata
            .labels
            .as_ref()
            .and_then(|l| l.get("pod-template-hash"))
            .cloned()
            .unwrap_or_default();

        let replicas = rs.spec.as_ref().and_then(|s| s.replicas).unwrap_or(0);

        owned.push((revision, hash, replicas));
    }

    // Sort by revision descending: newest first
    owned.sort_by(|a, b| b.0.cmp(&a.0));

    let target = owned
        .first()
        .map(|(_, hash, _)| hash.clone())
        .unwrap_or_default();

    let current = owned
        .iter()
        .skip(1)
        .find(|(_, _, replicas)| *replicas > 0)
        .map(|(_, hash, _)| hash.clone())
        .unwrap_or_default();

    Ok((current, target))
}

/// Find the active pod-template-hash for a Deployment not in rollout.
async fn find_active_generation(
    client: &Client,
    namespace: &str,
    deployment_name: &str,
) -> Result<String, kube::Error> {
    let rs_api: Api<ReplicaSet> = Api::namespaced(client.clone(), namespace);
    let rs_list = rs_api.list(&ListParams::default()).await?;

    let mut best_revision = 0u64;
    let mut best_hash = String::new();

    for rs in &rs_list.items {
        let owners = rs.metadata.owner_references.as_deref().unwrap_or_default();
        if !owners
            .iter()
            .any(|o| o.kind == "Deployment" && o.name == deployment_name)
        {
            continue;
        }

        let revision = rs
            .metadata
            .annotations
            .as_ref()
            .and_then(|a| a.get("deployment.kubernetes.io/revision"))
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(0);

        if revision > best_revision {
            best_revision = revision;
            best_hash = rs
                .metadata
                .labels
                .as_ref()
                .and_then(|l| l.get("pod-template-hash"))
                .cloned()
                .unwrap_or_default();
        }
    }

    Ok(best_hash)
}

/// Watch a StatefulSet and update its ClusterIntent on changes.
async fn run_statefulset_watcher(
    client: &Client,
    namespace: &str,
    controller: &ControllerRef,
    controllers: &Arc<RwLock<HashMap<ControllerRef, ClusterIntent>>>,
    cancel: CancellationToken,
) {
    let api: Api<StatefulSet> = Api::namespaced(client.clone(), namespace);
    let config = WatcherConfig::default().fields(&format!("metadata.name={}", controller.name));

    let stream = watcher::watcher(api, config);
    tokio::pin!(stream);

    loop {
        tokio::select! {
            _ = cancel.cancelled() => break,
            item = stream.next() => {
                match item {
                    Some(Ok(event)) => {
                        handle_statefulset_event(controller, controllers, event).await;
                    }
                    Some(Err(e)) => {
                        warn!(
                            controller = %controller,
                            error = %e,
                            "statefulset watcher error, stream will retry"
                        );
                    }
                    None => {
                        info!(controller = %controller, "statefulset watcher stream ended");
                        break;
                    }
                }
            }
        }
    }
}

async fn handle_statefulset_event(
    controller: &ControllerRef,
    controllers: &Arc<RwLock<HashMap<ControllerRef, ClusterIntent>>>,
    event: Event<StatefulSet>,
) {
    let ss = match event {
        Event::Apply(s) | Event::InitApply(s) => s,
        Event::Delete(_) => {
            info!(controller = %controller, "statefulset deleted");
            let mut map = controllers.write().await;
            map.remove(controller);
            return;
        }
        Event::Init | Event::InitDone => return,
    };

    let spec = match &ss.spec {
        Some(s) => s,
        None => return,
    };
    let status = ss.status.as_ref();

    let desired_replicas = spec.replicas.unwrap_or(1) as u32;

    // StatefulSet rollout: currentRevision != updateRevision
    let current_revision = status
        .and_then(|s| s.current_revision.clone())
        .unwrap_or_default();
    let update_revision = status
        .and_then(|s| s.update_revision.clone())
        .unwrap_or_default();

    let rollout_in_progress = !current_revision.is_empty()
        && !update_revision.is_empty()
        && current_revision != update_revision;

    let target_generation = if rollout_in_progress {
        Some(update_revision.clone())
    } else {
        None
    };

    let mut map = controllers.write().await;
    let previous_replicas = map.get(controller).and_then(|prev| {
        if prev.desired_replicas != desired_replicas {
            Some(prev.desired_replicas)
        } else {
            prev.previous_replicas
        }
    });

    let intent = ClusterIntent {
        desired_replicas,
        previous_replicas,
        rollout_in_progress,
        current_generation: current_revision,
        target_generation,
    };

    debug!(
        controller = %controller,
        desired_replicas = intent.desired_replicas,
        previous_replicas = ?intent.previous_replicas,
        rollout_in_progress = intent.rollout_in_progress,
        current_generation = %intent.current_generation,
        target_generation = ?intent.target_generation,
        "updated statefulset cluster intent"
    );

    map.insert(controller.clone(), intent);
}
