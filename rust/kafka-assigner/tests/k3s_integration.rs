mod common;

use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Duration;

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
use tokio::net::TcpListener;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::TcpListenerStream;
use tokio_util::sync::CancellationToken;
use tonic::transport::Server;

use k8s_awareness::{DepartureReason, K8sAwareness};
use kafka_assigner::assigner::{Assigner, AssignerConfig};
use kafka_assigner::config::Config;
use kafka_assigner::consumer_registry::ConsumerRegistry;
use kafka_assigner::grpc::relay::run_relay;
use kafka_assigner::grpc::server::KafkaAssignerService;
use kafka_assigner::store::KafkaAssignerStore;
use kafka_assigner::strategy::StickyBalancedStrategy;
use kafka_assigner_proto::kafka_assigner::v1 as proto;
use kafka_assigner_proto::kafka_assigner::v1::kafka_assigner_server::KafkaAssignerServer;

use common::{
    create_grpc_client, create_kafka_topic, set_topic_config, signal_ready, signal_released,
    test_store, wait_for_condition, POLL_INTERVAL,
};

const NAMESPACE: &str = "default";
const NUM_PARTITIONS: u32 = 8;
const E2E_TIMEOUT: Duration = Duration::from_secs(180);

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

async fn get_first_pod_name(client: &Client, label_selector: &str) -> String {
    let pods: Api<k8s_openapi::api::core::v1::Pod> = Api::namespaced(client.clone(), NAMESPACE);
    let list = pods
        .list(&ListParams::default().labels(label_selector))
        .await
        .expect("failed to list pods");

    list.items
        .first()
        .and_then(|p| p.metadata.name.clone())
        .expect("no pods found")
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
    // Trigger a rollout by adding an env var instead of changing the image.
    // Changing the image forces k3s to pull a new image inside the container,
    // which can make the k3s API server unreachable due to resource pressure.
    // Use Strategic merge so the containers array is merged by name, not replaced.
    let patch = serde_json::json!({
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "name": "pause",
                        "env": [{"name": "ROLLOUT_TRIGGER", "value": "1"}]
                    }]
                }
            }
        }
    });
    deployments
        .patch(name, &PatchParams::default(), &Patch::Strategic(&patch))
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
                        "env": [{"name": "ROLLOUT_TRIGGER", "value": "1"}]
                    }]
                }
            }
        }
    });
    statefulsets
        .patch(name, &PatchParams::default(), &Patch::Strategic(&patch))
        .await
        .expect("failed to patch statefulset");
}

/// Wait for the k3s API server to become reachable again after a rollout.
/// The API server can crash under resource pressure in the single-node
/// testcontainer; this avoids burning the `wait_for_condition` budget on
/// Connect errors.
async fn wait_for_k3s_api_ready(client: &Client, timeout_dur: Duration) {
    let start = std::time::Instant::now();
    let pods: Api<k8s_openapi::api::core::v1::Pod> = Api::namespaced(client.clone(), NAMESPACE);
    loop {
        if tokio::time::timeout(Duration::from_secs(5), pods.list(&ListParams::default()))
            .await
            .map(|r| r.is_ok())
            .unwrap_or(false)
        {
            return;
        }
        if start.elapsed() > timeout_dur {
            panic!("k3s API server did not recover within {timeout_dur:?}");
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
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

// ── K8s-aware component helpers ──────────────────────────

struct K8sGrpcServer {
    addr: std::net::SocketAddr,
    _server_task: JoinHandle<()>,
    _relay_task: JoinHandle<()>,
}

async fn start_grpc_server_k8s(
    store: Arc<KafkaAssignerStore>,
    k8s_awareness: Option<Arc<K8sAwareness>>,
    cancel: CancellationToken,
) -> K8sGrpcServer {
    let registry = Arc::new(ConsumerRegistry::new());
    let mut config = Config::init_with_defaults().expect("default config should parse");
    config.consumer_lease_ttl_secs = 5;
    config.consumer_keepalive_interval_secs = 1;
    let service = KafkaAssignerService::from_config(
        Arc::clone(&store),
        Arc::clone(&registry),
        &config,
        k8s_awareness,
    );

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let server_task = tokio::spawn(async move {
        Server::builder()
            .add_service(KafkaAssignerServer::new(service))
            .serve_with_incoming(TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    let relay_store = Arc::clone(&store);
    let relay_registry = Arc::clone(&registry);
    let relay_cancel = cancel.child_token();
    let relay_task = tokio::spawn(async move {
        if let Err(e) = run_relay(relay_store, relay_registry, relay_cancel).await {
            tracing::warn!(error = %e, "relay exited with error");
        }
    });

    tokio::time::sleep(Duration::from_millis(50)).await;

    K8sGrpcServer {
        addr,
        _server_task: server_task,
        _relay_task: relay_task,
    }
}

fn start_assigner_k8s(
    store: Arc<KafkaAssignerStore>,
    k8s_awareness: Option<Arc<K8sAwareness>>,
    cancel: CancellationToken,
) -> JoinHandle<kafka_assigner::error::Result<()>> {
    let strategy = Arc::new(StickyBalancedStrategy);
    let assigner = Assigner::new(store, AssignerConfig::default(), strategy, k8s_awareness);
    let token = cancel.child_token();
    tokio::spawn(async move { assigner.run(token).await })
}

// ── Tests ────────────────────────────────────────────────
//
// Tests run sequentially via `#[serial]` — each spins up its own k3s
// container which is dropped (and cleaned up by Docker) when the test ends.
// This avoids running multiple k3s clusters in parallel which exhausts
// Docker memory.

/// Full Deployment rollout lifecycle with K8s-aware assigner + gRPC.
///
/// Uses k3s for real K8s API, local etcd, and local Kafka. Consumers
/// register via gRPC (which discovers their K8s controller and generation).
/// The assigner uses K8sAwareness to proactively exclude old-gen consumers
/// during a rollout, moving partitions to new-gen via handoff.
///
/// Flow:
/// 1. Two old-gen consumers share partitions (registered with real k3s pod names)
/// 2. Trigger rollout in k3s → K8sAwareness detects old generation is departing
/// 3. New k3s pods created → register new-gen consumers via gRPC
/// 4. Assigner excludes old-gen, creates handoffs to new-gen
/// 5. Drive handoffs to completion → all partitions on new-gen
#[tokio::test(flavor = "multi_thread")]
#[serial]
async fn deployment_rollout_reassigns_partitions() {
    let (_container, k8s_client, _tmp) = setup_k3s().await;

    let deploy_name = "test-ka-e2e-deploy";
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

    // Let watcher establish baseline
    tokio::time::sleep(Duration::from_secs(3)).await;

    // Set up etcd store and topic config
    let store = test_store("deploy-rollout-e2e").await;
    let topic = format!("test-deploy-rollout-{}", uuid::Uuid::new_v4());
    create_kafka_topic(&topic, NUM_PARTITIONS as i32).await;
    set_topic_config(&store, &topic, NUM_PARTITIONS).await;

    let cancel = CancellationToken::new();

    // Start K8s-aware gRPC server and assigner
    let grpc_server = start_grpc_server_k8s(
        Arc::clone(&store),
        Some(Arc::clone(&awareness)),
        cancel.clone(),
    )
    .await;
    let _assigner = start_assigner_k8s(
        Arc::clone(&store),
        Some(Arc::clone(&awareness)),
        cancel.clone(),
    );

    // Register old-gen consumers via gRPC using real k3s pod names.
    // The Register RPC discovers controller info from k3s.
    let mut client_a = create_grpc_client(grpc_server.addr).await;
    let _stream_a = client_a
        .register(proto::RegisterRequest {
            consumer_name: old_names[0].clone(),
            topic: topic.clone(),
        })
        .await
        .expect("register old-0 failed")
        .into_inner();

    let mut client_b = create_grpc_client(grpc_server.addr).await;
    let _stream_b = client_b
        .register(proto::RegisterRequest {
            consumer_name: old_names[1].clone(),
            topic: topic.clone(),
        })
        .await
        .expect("register old-1 failed")
        .into_inner();

    // Wait for initial assignment across both consumers
    let check_store = Arc::clone(&store);
    let check_names = old_names.clone();
    wait_for_condition(E2E_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        let names = check_names.clone();
        async move {
            let a = store.list_assignments().await.unwrap_or_default();
            let h = store.list_handoffs().await.unwrap_or_default();
            a.len() == NUM_PARTITIONS as usize
                && h.is_empty()
                && a.iter().any(|x| x.owner == names[0])
                && a.iter().any(|x| x.owner == names[1])
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

    // Wait for the k3s API server to recover — it can crash under resource
    // pressure during the rollout in the single-node testcontainer.
    wait_for_k3s_api_ready(&k8s_client, E2E_TIMEOUT).await;

    // Wait for new k3s pods (created by the rollout)
    let new_names =
        wait_for_new_running_pods(&k8s_client, &format!("app={deploy_name}"), &old_names, 2).await;

    // Register new-gen consumers via gRPC (discovers new generation from k3s)
    let mut client_c = create_grpc_client(grpc_server.addr).await;
    let _stream_c = client_c
        .register(proto::RegisterRequest {
            consumer_name: new_names[0].clone(),
            topic: topic.clone(),
        })
        .await
        .expect("register new-0 failed")
        .into_inner();

    let mut client_d = create_grpc_client(grpc_server.addr).await;
    let _stream_d = client_d
        .register(proto::RegisterRequest {
            consumer_name: new_names[1].clone(),
            topic: topic.clone(),
        })
        .await
        .expect("register new-1 failed")
        .into_inner();

    // Drive handoffs to completion while waiting for all partitions to move
    // to new-gen consumers. We combine driving handoffs with checking the end
    // state because the assigner may not have rebalanced yet when we start
    // (the consumer watcher has a 1-second debounce).
    let drive_store = Arc::clone(&store);
    let expected_owners = new_names.clone();
    wait_for_condition(E2E_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&drive_store);
        let owners = expected_owners.clone();
        async move {
            // Advance any in-flight handoffs
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            for h in &handoffs {
                match h.phase {
                    kafka_assigner::types::HandoffPhase::Warming => {
                        signal_ready(&store, &h.topic_partition()).await;
                    }
                    kafka_assigner::types::HandoffPhase::Complete => {
                        signal_released(&store, &h.topic_partition()).await;
                    }
                    kafka_assigner::types::HandoffPhase::Ready => {}
                }
            }

            // Check desired end state: all partitions on new-gen consumers
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| owners.contains(&a.owner))
        }
    })
    .await;

    cancel.cancel();
    k8s_cancel.cancel();
}

/// StatefulSet rollout: Deregister returns ShutdownNow.
///
/// In a StatefulSet rolling update, K8s terminates pods one at a time and
/// recreates them with the same name. The Deregister RPC classifies this
/// as StatefulSet + Rollout and returns ShutdownNow, telling the consumer
/// to exit immediately without draining.
///
/// Flow:
/// 1. Consumer registers via gRPC (discovers StatefulSet controller info)
/// 2. Trigger rollout in k3s → K8sAwareness detects rollout
/// 3. Consumer calls Deregister → action = ShutdownNow
#[tokio::test(flavor = "multi_thread")]
#[serial]
async fn statefulset_rollout_deregister_returns_shutdown_now() {
    let (_container, k8s_client, _tmp) = setup_k3s().await;

    let ss_name = "test-ka-e2e-ss";
    create_statefulset(&k8s_client, ss_name, 2).await;
    wait_for_ready_pods(&k8s_client, &format!("app={ss_name}"), 2).await;

    let k8s_cancel = CancellationToken::new();
    let awareness = Arc::new(K8sAwareness::new(
        k8s_client.clone(),
        NAMESPACE.to_string(),
        k8s_cancel.clone(),
    ));

    let pod_name = get_first_pod_name(&k8s_client, &format!("app={ss_name}")).await;
    let pod_info = awareness
        .discover_controller(&pod_name)
        .await
        .expect("discover failed");
    let old_generation = pod_info.generation.clone();

    // Let watcher establish baseline
    tokio::time::sleep(Duration::from_secs(3)).await;

    let store = test_store("ss-deregister-e2e").await;
    let cancel = CancellationToken::new();

    let grpc_server = start_grpc_server_k8s(
        Arc::clone(&store),
        Some(Arc::clone(&awareness)),
        cancel.clone(),
    )
    .await;

    // Register consumer via gRPC (discovers StatefulSet controller)
    let mut client = create_grpc_client(grpc_server.addr).await;
    let _stream = client
        .register(proto::RegisterRequest {
            consumer_name: pod_name.clone(),
            topic: String::new(),
        })
        .await
        .expect("register failed")
        .into_inner();

    // Trigger rollout and wait for detection
    trigger_statefulset_rollout(&k8s_client, ss_name).await;
    wait_for_departure_reason(
        &awareness,
        &pod_info.controller,
        &old_generation,
        DepartureReason::Rollout,
    )
    .await;

    // Deregister: should return ShutdownNow (StatefulSet + Rollout)
    let response = client
        .deregister(proto::DeregisterRequest {
            consumer_name: pod_name.clone(),
        })
        .await
        .expect("deregister failed")
        .into_inner();

    assert_eq!(
        response.action,
        proto::DeregisterAction::ShutdownNow as i32,
        "StatefulSet rollout should return ShutdownNow"
    );

    cancel.cancel();
    k8s_cancel.cancel();
}

/// Scale-down: Deregister returns WaitForDrain.
///
/// When K8s scales down a Deployment (reduces replicas), K8sAwareness
/// classifies the departure as Downscale. The Deregister RPC returns
/// WaitForDrain, telling the consumer to keep its gRPC stream open and
/// wait for all partitions to be drained before exiting.
///
/// Flow:
/// 1. Consumer registers via gRPC (discovers Deployment controller info)
/// 2. Scale down in k3s → K8sAwareness detects Downscale
/// 3. Consumer calls Deregister → action = WaitForDrain
#[tokio::test(flavor = "multi_thread")]
#[serial]
async fn scale_down_deregister_returns_wait_for_drain() {
    let (_container, k8s_client, _tmp) = setup_k3s().await;

    let deploy_name = "test-ka-e2e-scale";
    create_deployment(&k8s_client, deploy_name, 2).await;
    wait_for_ready_pods(&k8s_client, &format!("app={deploy_name}"), 2).await;

    let k8s_cancel = CancellationToken::new();
    let awareness = Arc::new(K8sAwareness::new(
        k8s_client.clone(),
        NAMESPACE.to_string(),
        k8s_cancel.clone(),
    ));

    let pod_name = get_first_pod_name(&k8s_client, &format!("app={deploy_name}")).await;
    let pod_info = awareness
        .discover_controller(&pod_name)
        .await
        .expect("discover failed");
    let generation = pod_info.generation.clone();

    // Let watcher establish baseline
    tokio::time::sleep(Duration::from_secs(3)).await;

    let store = test_store("scale-down-deregister-e2e").await;
    let cancel = CancellationToken::new();

    let grpc_server = start_grpc_server_k8s(
        Arc::clone(&store),
        Some(Arc::clone(&awareness)),
        cancel.clone(),
    )
    .await;

    // Register consumer via gRPC (discovers Deployment controller)
    let mut client = create_grpc_client(grpc_server.addr).await;
    let _stream = client
        .register(proto::RegisterRequest {
            consumer_name: pod_name.clone(),
            topic: String::new(),
        })
        .await
        .expect("register failed")
        .into_inner();

    // Scale down and wait for detection
    scale_deployment(&k8s_client, deploy_name, 1).await;
    wait_for_departure_reason(
        &awareness,
        &pod_info.controller,
        &generation,
        DepartureReason::Downscale,
    )
    .await;

    // Deregister: should return WaitForDrain (Deployment + Downscale)
    let response = client
        .deregister(proto::DeregisterRequest {
            consumer_name: pod_name.clone(),
        })
        .await
        .expect("deregister failed")
        .into_inner();

    assert_eq!(
        response.action,
        proto::DeregisterAction::WaitForDrain as i32,
        "Deployment scale-down should return WaitForDrain"
    );

    cancel.cancel();
    k8s_cancel.cancel();
}
