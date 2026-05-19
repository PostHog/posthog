mod common;

use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use k8s_openapi::api::apps::v1::{Deployment, DeploymentSpec, StatefulSet, StatefulSetSpec};
use k8s_openapi::api::core::v1::{
    Container, ContainerPort, PodSpec, PodTemplateSpec, Service, ServicePort, ServiceSpec,
};
use k8s_openapi::apimachinery::pkg::apis::meta::v1::{LabelSelector, ObjectMeta};
use k8s_openapi::apimachinery::pkg::util::intstr::IntOrString;
use kube::api::{Api, ListParams, Patch, PatchParams, PostParams};
use kube::config::{KubeConfigOptions, Kubeconfig};
use kube::Client;
use serial_test::serial;
use testcontainers::runners::AsyncRunner;
use testcontainers::ImageExt;
use testcontainers_modules::k3s::{K3s, KUBE_SECURE_PORT};
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use k8s_awareness::{DepartureReason, K8sAwareness};
use personhog_coordination::coordinator::{Coordinator, CoordinatorConfig};
use personhog_coordination::error::Result;
use personhog_coordination::pod::{HandoffHandler, PodConfig, PodHandle};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::strategy::StickyBalancedStrategy;
use personhog_coordination::types::PodStatus;

use common::{start_router, test_store, wait_for_condition, HandoffEvent, POLL_INTERVAL};

const NAMESPACE: &str = "default";
const NUM_PARTITIONS: u32 = 8;
const E2E_TIMEOUT: Duration = Duration::from_secs(60);

// ── K3s helpers ──────────────────────────────────────────

async fn setup_k3s() -> (
    testcontainers::ContainerAsync<K3s>,
    Client,
    tempfile::TempDir,
) {
    drop(tracing_subscriber::fmt::try_init());

    let tmp_dir = tempfile::tempdir().expect("failed to create temp dir");
    let container = K3s::default()
        .with_conf_mount(tmp_dir.path())
        .with_privileged(true)
        .start()
        .await
        .expect("failed to start k3s container");

    let config_path = tmp_dir.path().join("k3s.yaml");
    for _ in 0..30 {
        if config_path.exists() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }

    let config_yaml = std::fs::read_to_string(&config_path).expect("failed to read k3s kubeconfig");
    let host_port = container
        .get_host_port_ipv4(KUBE_SECURE_PORT)
        .await
        .expect("failed to get host port");
    let config_yaml = config_yaml.replace("127.0.0.1:6443", &format!("127.0.0.1:{host_port}"));

    let kubeconfig = Kubeconfig::from_yaml(&config_yaml).expect("failed to parse kubeconfig YAML");
    let client_config =
        kube::Config::from_custom_kubeconfig(kubeconfig, &KubeConfigOptions::default())
            .await
            .expect("failed to build kube config");
    let client = Client::try_from(client_config).expect("failed to create kube client");

    let version = client
        .apiserver_version()
        .await
        .expect("failed to reach K8s API server");
    tracing::info!(version = %version.git_version, "connected to k3s");

    (container, client, tmp_dir)
}

fn labels(app: &str) -> BTreeMap<String, String> {
    BTreeMap::from([("app".to_string(), app.to_string())])
}

async fn create_deployment(client: &Client, name: &str, replicas: i32) {
    let deployments: Api<Deployment> = Api::namespaced(client.clone(), NAMESPACE);
    let deploy = Deployment {
        metadata: ObjectMeta {
            name: Some(name.to_string()),
            namespace: Some(NAMESPACE.to_string()),
            ..Default::default()
        },
        spec: Some(DeploymentSpec {
            replicas: Some(replicas),
            selector: LabelSelector {
                match_labels: Some(labels(name)),
                ..Default::default()
            },
            template: PodTemplateSpec {
                metadata: Some(ObjectMeta {
                    labels: Some(labels(name)),
                    ..Default::default()
                }),
                spec: Some(PodSpec {
                    containers: vec![Container {
                        name: "pause".to_string(),
                        image: Some("registry.k8s.io/pause:3.9".to_string()),
                        ..Default::default()
                    }],
                    ..Default::default()
                }),
            },
            ..Default::default()
        }),
        ..Default::default()
    };
    deployments
        .create(&PostParams::default(), &deploy)
        .await
        .expect("failed to create deployment");
}

async fn create_statefulset(client: &Client, name: &str, replicas: i32) {
    let services: Api<Service> = Api::namespaced(client.clone(), NAMESPACE);
    let svc = Service {
        metadata: ObjectMeta {
            name: Some(format!("{name}-headless")),
            namespace: Some(NAMESPACE.to_string()),
            ..Default::default()
        },
        spec: Some(ServiceSpec {
            selector: Some(labels(name)),
            cluster_ip: Some("None".to_string()),
            ports: Some(vec![ServicePort {
                port: 80,
                target_port: Some(IntOrString::Int(80)),
                ..Default::default()
            }]),
            ..Default::default()
        }),
        ..Default::default()
    };
    services
        .create(&PostParams::default(), &svc)
        .await
        .expect("failed to create headless service");

    let statefulsets: Api<StatefulSet> = Api::namespaced(client.clone(), NAMESPACE);
    let ss = StatefulSet {
        metadata: ObjectMeta {
            name: Some(name.to_string()),
            namespace: Some(NAMESPACE.to_string()),
            ..Default::default()
        },
        spec: Some(StatefulSetSpec {
            replicas: Some(replicas),
            service_name: format!("{name}-headless"),
            selector: LabelSelector {
                match_labels: Some(labels(name)),
                ..Default::default()
            },
            template: PodTemplateSpec {
                metadata: Some(ObjectMeta {
                    labels: Some(labels(name)),
                    ..Default::default()
                }),
                spec: Some(PodSpec {
                    containers: vec![Container {
                        name: "pause".to_string(),
                        image: Some("registry.k8s.io/pause:3.9".to_string()),
                        ports: Some(vec![ContainerPort {
                            container_port: 80,
                            ..Default::default()
                        }]),
                        ..Default::default()
                    }],
                    ..Default::default()
                }),
            },
            ..Default::default()
        }),
        ..Default::default()
    };
    statefulsets
        .create(&PostParams::default(), &ss)
        .await
        .expect("failed to create statefulset");
}

async fn wait_for_ready_pods(client: &Client, label_selector: &str, count: usize) {
    let pods: Api<k8s_openapi::api::core::v1::Pod> = Api::namespaced(client.clone(), NAMESPACE);
    let timeout = Duration::from_secs(120);
    let start = std::time::Instant::now();

    loop {
        let list = pods
            .list(&ListParams::default().labels(label_selector))
            .await
            .expect("failed to list pods");

        let ready_count = list
            .items
            .iter()
            .filter(|p| p.status.as_ref().and_then(|s| s.phase.as_deref()) == Some("Running"))
            .count();

        if ready_count >= count {
            return;
        }

        if start.elapsed() > timeout {
            panic!(
                "timed out waiting for {count} ready pods (selector={label_selector}), got {ready_count}"
            );
        }

        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}

async fn get_running_pod_names(client: &Client, label_selector: &str) -> Vec<String> {
    let pods: Api<k8s_openapi::api::core::v1::Pod> = Api::namespaced(client.clone(), NAMESPACE);
    let list = pods
        .list(&ListParams::default().labels(label_selector))
        .await
        .expect("failed to list pods");
    list.items
        .iter()
        .filter(|p| p.status.as_ref().and_then(|s| s.phase.as_deref()) == Some("Running"))
        .filter_map(|p| p.metadata.name.clone())
        .collect()
}

/// Wait for new pods (not in `old_names`) to reach Running state.
async fn wait_for_new_running_pods(
    client: &Client,
    label_selector: &str,
    old_names: &[String],
    count: usize,
) -> Vec<String> {
    let timeout = Duration::from_secs(120);
    let start = std::time::Instant::now();
    loop {
        let all = get_running_pod_names(client, label_selector).await;
        let new: Vec<_> = all.into_iter().filter(|n| !old_names.contains(n)).collect();
        if new.len() >= count {
            return new;
        }
        if start.elapsed() > timeout {
            panic!(
                "timed out waiting for {count} new running pods, got {}",
                new.len()
            );
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}

async fn wait_for_departure_reason(
    awareness: &K8sAwareness,
    controller: &k8s_awareness::types::ControllerRef,
    generation: &str,
    expected: DepartureReason,
) {
    for i in 0..30 {
        tokio::time::sleep(Duration::from_secs(2)).await;
        let reason = awareness.classify_departure(controller, generation).await;
        tracing::debug!(
            iteration = i,
            ?reason,
            ?expected,
            "polling departure detection"
        );
        if reason == expected {
            return;
        }
    }
    panic!("timed out waiting for {expected:?} departure reason");
}

async fn trigger_deployment_rollout(client: &Client, name: &str) {
    let deployments: Api<Deployment> = Api::namespaced(client.clone(), NAMESPACE);
    let patch = serde_json::json!({
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "name": "pause",
                        "image": "registry.k8s.io/pause:3.10"
                    }]
                }
            }
        }
    });
    deployments
        .patch(name, &PatchParams::default(), &Patch::Merge(&patch))
        .await
        .expect("failed to patch deployment");
}

async fn trigger_statefulset_rollout(client: &Client, name: &str) {
    let statefulsets: Api<StatefulSet> = Api::namespaced(client.clone(), NAMESPACE);
    let patch = serde_json::json!({
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "name": "pause",
                        "image": "registry.k8s.io/pause:3.10"
                    }]
                }
            }
        }
    });
    statefulsets
        .patch(name, &PatchParams::default(), &Patch::Merge(&patch))
        .await
        .expect("failed to patch statefulset");
}

async fn scale_deployment(client: &Client, name: &str, replicas: i32) {
    let deployments: Api<Deployment> = Api::namespaced(client.clone(), NAMESPACE);
    let patch = serde_json::json!({
        "spec": { "replicas": replicas }
    });
    deployments
        .patch(name, &PatchParams::default(), &Patch::Merge(&patch))
        .await
        .expect("failed to scale deployment");
}

// ── Component helpers (K8s-aware variants) ───────────────

struct MockHandler {
    events: Arc<Mutex<Vec<HandoffEvent>>>,
}

impl MockHandler {
    fn new() -> (Self, Arc<Mutex<Vec<HandoffEvent>>>) {
        let events = Arc::new(Mutex::new(Vec::new()));
        (
            Self {
                events: Arc::clone(&events),
            },
            events,
        )
    }
}

#[async_trait]
impl HandoffHandler for MockHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Released(partition));
        Ok(())
    }
}

fn start_pod_k8s(
    store: Arc<PersonhogStore>,
    config: PodConfig,
    k8s_awareness: Option<Arc<K8sAwareness>>,
    cancel: CancellationToken,
) -> (Arc<Mutex<Vec<HandoffEvent>>>, JoinHandle<Result<()>>) {
    let (handler, events) = MockHandler::new();
    let pod = PodHandle::new(store, config, Arc::new(handler), k8s_awareness);
    let token = cancel.child_token();
    let handle = tokio::spawn(async move { pod.run(token).await });
    (events, handle)
}

fn start_coordinator_k8s(
    store: Arc<PersonhogStore>,
    k8s_awareness: Option<Arc<K8sAwareness>>,
    cancel: CancellationToken,
) -> JoinHandle<Result<()>> {
    let coordinator = Coordinator::new(
        store,
        CoordinatorConfig {
            rebalance_debounce_interval: Duration::from_millis(100),
            ..Default::default()
        },
        Arc::new(StickyBalancedStrategy),
        k8s_awareness,
    );
    let token = cancel.child_token();
    tokio::spawn(async move { coordinator.run(token).await })
}

// ── Tests ────────────────────────────────────────────────
//
// Tests run sequentially via `#[serial]` — each spins up its own k3s
// container which is dropped (and cleaned up by Docker) when the test ends.
// This avoids running multiple k3s clusters in parallel which exhausts
// Docker memory.

/// Full Deployment rollout lifecycle with K8s-aware coordinator.
///
/// In a real Deployment rollout, K8s creates new-gen pods and terminates
/// old-gen pods. The coordinator, using K8sAwareness, proactively excludes
/// old-gen pods from the active list so partitions move to new-gen pods
/// via handoff BEFORE old pods are terminated.
///
/// Flow:
/// 1. Two old-gen pods share partitions
/// 2. Trigger rollout in k3s → coordinator detects old generation is departing
/// 3. Two new-gen pods register → coordinator rebalances, excluding old-gen
/// 4. Handoffs move all partitions to new-gen pods
/// 5. Old pods are terminated (SIGTERM) — they have no partitions, drain is instant
/// 6. Final: only new-gen pods own partitions
#[tokio::test(flavor = "multi_thread")]
#[serial]
async fn deployment_rollout_reassigns_partitions() {
    let (_container, k8s_client, _tmp) = setup_k3s().await;

    let deploy_name = "test-coord-deploy";
    create_deployment(&k8s_client, deploy_name, 2).await;
    wait_for_ready_pods(&k8s_client, &format!("app={deploy_name}"), 2).await;

    let k8s_cancel = CancellationToken::new();
    let awareness = Arc::new(K8sAwareness::new(
        k8s_client.clone(),
        NAMESPACE.to_string(),
        k8s_cancel.clone(),
    ));

    // Discover controller info from a real pod so we can detect rollout later
    let old_names = get_running_pod_names(&k8s_client, &format!("app={deploy_name}")).await;
    assert_eq!(old_names.len(), 2, "expected 2 running pods");
    let pod_info = awareness
        .discover_controller(&old_names[0])
        .await
        .expect("discover failed");
    let old_generation = pod_info.generation.clone();

    tokio::time::sleep(Duration::from_secs(3)).await;

    // Set up etcd store and coordination
    let store = test_store("deploy-rollout-k3s").await;
    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let cancel = CancellationToken::new();
    let _coord = start_coordinator_k8s(
        Arc::clone(&store),
        Some(Arc::clone(&awareness)),
        cancel.clone(),
    );
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Start two old-gen pods
    let old_config = |name: &str| PodConfig {
        pod_name: name.to_string(),
        generation: old_generation.clone(),
        controller: Some(pod_info.controller.clone()),
        lease_ttl: 10,
        heartbeat_interval: Duration::from_secs(3),
        ..Default::default()
    };
    let old0_cancel = CancellationToken::new();
    let old1_cancel = CancellationToken::new();
    let (_old0_events, _old0_handle) = start_pod_k8s(
        Arc::clone(&store),
        old_config("old-0"),
        None,
        old0_cancel.clone(),
    );
    let (_old1_events, _old1_handle) = start_pod_k8s(
        Arc::clone(&store),
        old_config("old-1"),
        None,
        old1_cancel.clone(),
    );

    // Wait for initial assignment across both pods
    let check_store = Arc::clone(&store);
    wait_for_condition(E2E_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let a = store.list_assignments().await.unwrap_or_default();
            let r = store.list_routers().await.unwrap_or_default();
            let h = store.list_handoffs().await.unwrap_or_default();
            a.len() == NUM_PARTITIONS as usize
                && r.len() == 1
                && h.is_empty()
                && a.iter().any(|x| x.owner == "old-0")
                && a.iter().any(|x| x.owner == "old-1")
        }
    })
    .await;

    // Trigger rollout in k3s — K8sAwareness detects old generation is departing
    trigger_deployment_rollout(&k8s_client, deploy_name).await;
    wait_for_departure_reason(
        &awareness,
        &pod_info.controller,
        &old_generation,
        DepartureReason::Rollout,
    )
    .await;

    // Wait for new K8s pods (created by the rollout) and discover the real
    // new generation. We must use the actual pod-template-hash from K8s
    // because classify_departure compares against it — a fake generation
    // would be incorrectly classified as old-gen and excluded.
    let new_k8s_names =
        wait_for_new_running_pods(&k8s_client, &format!("app={deploy_name}"), &old_names, 2).await;
    let new_pod_info = awareness
        .discover_controller(&new_k8s_names[0])
        .await
        .expect("discover new pod failed");
    let new_generation = new_pod_info.generation;

    // New-gen pods register (simulating K8s creating replacements).
    // The coordinator now excludes old-gen from active list, so all
    // partitions get handed off to new-gen pods.
    let new_config = |name: &str| PodConfig {
        pod_name: name.to_string(),
        generation: new_generation.clone(),
        controller: Some(pod_info.controller.clone()),
        lease_ttl: 10,
        heartbeat_interval: Duration::from_secs(3),
        ..Default::default()
    };
    let (_new0_events, _new0_handle) = start_pod_k8s(
        Arc::clone(&store),
        new_config("new-0"),
        None,
        cancel.clone(),
    );
    let (_new1_events, _new1_handle) = start_pod_k8s(
        Arc::clone(&store),
        new_config("new-1"),
        None,
        cancel.clone(),
    );

    // Wait for all partitions to move to new-gen pods
    let check_store = Arc::clone(&store);
    wait_for_condition(E2E_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let a = store.list_assignments().await.unwrap_or_default();
            let h = store.list_handoffs().await.unwrap_or_default();
            a.len() == NUM_PARTITIONS as usize
                && h.is_empty()
                && a.iter().all(|x| x.owner == "new-0" || x.owner == "new-1")
        }
    })
    .await;

    // Terminate old pods (simulating K8s SIGTERM after rollout completes).
    // They have no partitions left, so drain is instant.
    old0_cancel.cancel();
    old1_cancel.cancel();

    // Verify old pods are gone from etcd
    let check_store = Arc::clone(&store);
    wait_for_condition(E2E_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let pods = store.list_pods().await.unwrap_or_default();
            !pods
                .iter()
                .any(|p| p.pod_name == "old-0" || p.pod_name == "old-1")
        }
    })
    .await;

    // Final: only new-gen pods with all partitions
    let assignments = store.list_assignments().await.unwrap();
    assert_eq!(assignments.len(), NUM_PARTITIONS as usize);
    for a in &assignments {
        assert!(
            a.owner == "new-0" || a.owner == "new-1",
            "partition {} owned by '{}', expected new-0 or new-1",
            a.partition,
            a.owner,
        );
    }

    cancel.cancel();
    k8s_cancel.cancel();
}

/// StatefulSet rollout: pod skips drain and exits immediately.
///
/// In a StatefulSet rolling update, K8s terminates pods one at a time and
/// recreates them with the same name but a new revision. Since the same
/// pod name returns, there's no point draining — the replacement will
/// reclaim the same identity and partitions.
///
/// When K8s sends SIGTERM (simulated by cancelling the token), the pod's
/// drain logic checks K8sAwareness. If it's a StatefulSet rollout, drain
/// is skipped entirely: the pod exits immediately, letting K8s restart it.
///
/// Flow:
/// 1. Pod gets all partitions
/// 2. Trigger rollout in k3s → K8sAwareness detects rollout
/// 3. K8s sends SIGTERM (cancel token) → pod skips drain, exits fast
/// 4. Verify: pod exits within seconds (not waiting drain_timeout)
/// 5. Verify: pod never set status to Draining in etcd
#[tokio::test(flavor = "multi_thread")]
#[serial]
async fn statefulset_rollout_pod_skips_drain() {
    let (_container, k8s_client, _tmp) = setup_k3s().await;

    let ss_name = "test-drain-ss";
    create_statefulset(&k8s_client, ss_name, 2).await;
    wait_for_ready_pods(&k8s_client, &format!("app={ss_name}"), 2).await;

    let k8s_cancel = CancellationToken::new();
    let awareness = Arc::new(K8sAwareness::new(
        k8s_client.clone(),
        NAMESPACE.to_string(),
        k8s_cancel.clone(),
    ));

    let pod_names = get_running_pod_names(&k8s_client, &format!("app={ss_name}")).await;
    let pod_info = awareness
        .discover_controller(&pod_names[0])
        .await
        .expect("discover failed");
    let old_generation = pod_info.generation.clone();

    tokio::time::sleep(Duration::from_secs(3)).await;

    let store = test_store("ss-drain-skip-k3s").await;
    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let coord_cancel = CancellationToken::new();
    let _coord = start_coordinator_k8s(Arc::clone(&store), None, coord_cancel.clone());
    let _router = start_router(Arc::clone(&store), "router-0", coord_cancel.clone());

    // Start pod with K8sAwareness and long drain_timeout.
    // If drain is NOT skipped, the pod would block for up to 30s.
    let pod_cancel = CancellationToken::new();
    let pod_config = PodConfig {
        pod_name: "ss-writer-0".to_string(),
        generation: old_generation.clone(),
        controller: Some(pod_info.controller.clone()),
        lease_ttl: 10,
        heartbeat_interval: Duration::from_secs(3),
        drain_timeout: Duration::from_secs(30),
    };
    let (_pod_events, pod_handle) = start_pod_k8s(
        Arc::clone(&store),
        pod_config,
        Some(Arc::clone(&awareness)),
        pod_cancel.clone(),
    );

    // Wait for pod to have all partitions
    let check_store = Arc::clone(&store);
    wait_for_condition(E2E_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let a = store.list_assignments().await.unwrap_or_default();
            let r = store.list_routers().await.unwrap_or_default();
            a.len() == NUM_PARTITIONS as usize
                && a.iter().all(|x| x.owner == "ss-writer-0")
                && r.len() == 1
        }
    })
    .await;

    // Trigger rollout and wait for detection
    trigger_statefulset_rollout(&k8s_client, ss_name).await;
    wait_for_departure_reason(
        &awareness,
        &pod_info.controller,
        &old_generation,
        DepartureReason::Rollout,
    )
    .await;

    // K8s sends SIGTERM — pod should skip drain and exit almost immediately
    pod_cancel.cancel();

    // Check status *before* awaiting pod_handle — once the pod exits it
    // revokes its lease and list_pods() returns empty, making any post-exit
    // assertion vacuously true.
    let pods = store.list_pods().await.unwrap_or_default();
    let pod_status = pods
        .iter()
        .find(|p| p.pod_name == "ss-writer-0")
        .map(|p| p.status);
    assert_ne!(
        pod_status,
        Some(PodStatus::Draining),
        "pod should skip drain entirely during StatefulSet rollout"
    );

    // If drain was NOT skipped, this would timeout (drain_timeout = 30s).
    // With drain skip, the pod exits in ~1s.
    let exit_timeout = Duration::from_secs(10);
    let result = tokio::time::timeout(exit_timeout, pod_handle).await;
    assert!(
        result.is_ok(),
        "pod should exit quickly when drain is skipped during StatefulSet rollout"
    );

    coord_cancel.cancel();
    k8s_cancel.cancel();
}

/// Scale-down: pod drains normally (does NOT skip drain).
///
/// When K8s scales down a Deployment (reduces replicas), K8sAwareness
/// classifies the departure as Downscale. Unlike a StatefulSet rollout,
/// the pod should drain normally — set status to Draining, wait for
/// partition handoffs, then exit.
///
/// This test confirms Downscale doesn't accidentally trigger the
/// drain-skip optimization (which is reserved for StatefulSet rollouts).
///
/// Flow:
/// 1. Two pods share partitions
/// 2. Scale down deployment in k3s (2 → 1 replicas)
/// 3. K8sAwareness detects Downscale
/// 4. K8s sends SIGTERM to excess pod → pod drains normally
/// 5. Partitions transfer to surviving pod via handoff protocol
/// 6. Final: single pod owns all partitions
#[tokio::test(flavor = "multi_thread")]
#[serial]
async fn scale_down_pod_drains_normally() {
    let (_container, k8s_client, _tmp) = setup_k3s().await;

    let deploy_name = "test-scale-deploy";
    create_deployment(&k8s_client, deploy_name, 2).await;
    wait_for_ready_pods(&k8s_client, &format!("app={deploy_name}"), 2).await;

    let k8s_cancel = CancellationToken::new();
    let awareness = Arc::new(K8sAwareness::new(
        k8s_client.clone(),
        NAMESPACE.to_string(),
        k8s_cancel.clone(),
    ));

    let pod_names = get_running_pod_names(&k8s_client, &format!("app={deploy_name}")).await;
    let pod_info = awareness
        .discover_controller(&pod_names[0])
        .await
        .expect("discover failed");
    let generation = pod_info.generation.clone();

    tokio::time::sleep(Duration::from_secs(3)).await;

    let store = test_store("scale-down-k3s").await;
    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let cancel = CancellationToken::new();
    let _coord = start_coordinator_k8s(
        Arc::clone(&store),
        Some(Arc::clone(&awareness)),
        cancel.clone(),
    );
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Start two pods — both with the same generation (no rollout)
    let pod_config = |name: &str| PodConfig {
        pod_name: name.to_string(),
        generation: generation.clone(),
        controller: Some(pod_info.controller.clone()),
        lease_ttl: 10,
        heartbeat_interval: Duration::from_secs(3),
        ..Default::default()
    };
    let victim_cancel = CancellationToken::new();
    let (victim_events, _victim_handle) = start_pod_k8s(
        Arc::clone(&store),
        pod_config("writer-0"),
        Some(Arc::clone(&awareness)),
        victim_cancel.clone(),
    );
    let (_survivor_events, _survivor_handle) = start_pod_k8s(
        Arc::clone(&store),
        pod_config("writer-1"),
        None,
        cancel.clone(),
    );

    // Wait for both pods to have partitions
    let check_store = Arc::clone(&store);
    wait_for_condition(E2E_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let a = store.list_assignments().await.unwrap_or_default();
            let r = store.list_routers().await.unwrap_or_default();
            let h = store.list_handoffs().await.unwrap_or_default();
            a.len() == NUM_PARTITIONS as usize
                && r.len() == 1
                && h.is_empty()
                && a.iter().any(|x| x.owner == "writer-0")
                && a.iter().any(|x| x.owner == "writer-1")
        }
    })
    .await;

    // Scale down: reduce replicas from 2 to 1
    scale_deployment(&k8s_client, deploy_name, 1).await;

    // Wait for K8sAwareness to detect Downscale
    wait_for_departure_reason(
        &awareness,
        &pod_info.controller,
        &generation,
        DepartureReason::Downscale,
    )
    .await;

    // K8s terminates the excess pod — it should drain NORMALLY
    // (not skip drain like StatefulSet rollout)
    victim_cancel.cancel();

    // Verify the pod entered Draining (proving drain was NOT skipped)
    let check_store = Arc::clone(&store);
    wait_for_condition(E2E_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let pods = store.list_pods().await.unwrap_or_default();
            pods.iter()
                .any(|p| p.pod_name == "writer-0" && p.status == PodStatus::Draining)
        }
    })
    .await;

    // Wait for all partitions to end up on the survivor
    let check_store = Arc::clone(&store);
    wait_for_condition(E2E_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let a = store.list_assignments().await.unwrap_or_default();
            let h = store.list_handoffs().await.unwrap_or_default();
            a.len() == NUM_PARTITIONS as usize
                && a.iter().all(|x| x.owner == "writer-1")
                && h.is_empty()
        }
    })
    .await;

    // Verify the victim pod released its partitions via handoff
    let events = victim_events.lock().await;
    let released: Vec<_> = events
        .iter()
        .filter(|e| matches!(e, HandoffEvent::Released(_)))
        .collect();
    assert!(
        !released.is_empty(),
        "pod should have released partitions during normal drain"
    );

    cancel.cancel();
    k8s_cancel.cancel();
}
