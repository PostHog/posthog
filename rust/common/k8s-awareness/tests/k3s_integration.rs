use std::collections::BTreeMap;
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
use testcontainers::runners::AsyncRunner;
use testcontainers::ImageExt;
use testcontainers_modules::k3s::{K3s, KUBE_SECURE_PORT};
use tokio_util::sync::CancellationToken;

use k8s_awareness::{discover_controller, ControllerKind, DepartureReason, K8sAwareness};

const NAMESPACE: &str = "default";

// ── Helpers ──────────────────────────────────────────────

/// Start a k3s container and return a kube::Client connected to it.
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

    // k3s writes the kubeconfig after the readiness log message;
    // give it a moment to flush the file.
    let config_path = tmp_dir.path().join("k3s.yaml");
    for _ in 0..30 {
        if config_path.exists() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }

    let config_yaml = std::fs::read_to_string(&config_path).expect("failed to read k3s kubeconfig");

    // Replace the server address with the mapped host port
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

    // Verify connectivity
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
    // StatefulSet needs a headless service
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

/// Wait until at least `count` pods matching `label_selector` are Running.
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

/// Get the name of the first pod matching a label selector.
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

// ── Tests ────────────────────────────────────────────────

#[tokio::test]
async fn discover_deployment_controller() {
    let (_container, client, _tmp) = setup_k3s().await;

    let deploy_name = "test-deploy";
    create_deployment(&client, deploy_name, 1).await;
    wait_for_ready_pods(&client, &format!("app={deploy_name}"), 1).await;

    let pod_name = get_first_pod_name(&client, &format!("app={deploy_name}")).await;
    let pod_info = discover_controller(&client, NAMESPACE, &pod_name)
        .await
        .expect("discover_controller failed");

    assert_eq!(pod_info.controller.kind, ControllerKind::Deployment);
    assert_eq!(pod_info.controller.name, deploy_name);
    assert!(
        !pod_info.generation.is_empty(),
        "generation should not be empty"
    );
}

#[tokio::test]
async fn discover_statefulset_controller() {
    let (_container, client, _tmp) = setup_k3s().await;

    let ss_name = "test-ss";
    create_statefulset(&client, ss_name, 1).await;
    wait_for_ready_pods(&client, &format!("app={ss_name}"), 1).await;

    let pod_name = get_first_pod_name(&client, &format!("app={ss_name}")).await;
    let pod_info = discover_controller(&client, NAMESPACE, &pod_name)
        .await
        .expect("discover_controller failed");

    assert_eq!(pod_info.controller.kind, ControllerKind::StatefulSet);
    assert_eq!(pod_info.controller.name, ss_name);
    assert!(
        !pod_info.generation.is_empty(),
        "generation should not be empty"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn watcher_detects_deployment_rollout() {
    let (_container, client, _tmp) = setup_k3s().await;

    let deploy_name = "test-rollout";
    create_deployment(&client, deploy_name, 2).await;
    wait_for_ready_pods(&client, &format!("app={deploy_name}"), 2).await;

    let cancel = CancellationToken::new();
    let awareness = K8sAwareness::new(client.clone(), NAMESPACE.to_string(), cancel.clone());

    // Discover the controller (starts a watcher)
    let pod_name = get_first_pod_name(&client, &format!("app={deploy_name}")).await;
    let pod_info = awareness
        .discover_controller(&pod_name)
        .await
        .expect("discover failed");
    let old_generation = pod_info.generation.clone();

    // Give the watcher time to receive the initial state
    tokio::time::sleep(Duration::from_secs(3)).await;

    // Before rollout: departure should be Crash (steady state)
    let reason = awareness
        .classify_departure(&pod_info.controller, &old_generation)
        .await;
    assert_eq!(
        reason,
        DepartureReason::Crash,
        "steady state departure should be Crash"
    );

    // Trigger a rollout by changing the container image
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
        .patch(deploy_name, &PatchParams::default(), &Patch::Merge(&patch))
        .await
        .expect("failed to patch deployment");

    // Wait for the watcher to detect the rollout
    let mut detected = false;
    for i in 0..30 {
        tokio::time::sleep(Duration::from_secs(2)).await;
        let reason = awareness
            .classify_departure(&pod_info.controller, &old_generation)
            .await;
        tracing::debug!(iteration = i, ?reason, gen = %old_generation, "polling rollout detection");
        if reason == DepartureReason::Rollout {
            detected = true;
            break;
        }
    }

    cancel.cancel();
    assert!(detected, "watcher should detect rollout for old-gen pods");
}

#[tokio::test(flavor = "multi_thread")]
async fn watcher_detects_deployment_downscale() {
    let (_container, client, _tmp) = setup_k3s().await;

    let deploy_name = "test-downscale";
    create_deployment(&client, deploy_name, 3).await;
    wait_for_ready_pods(&client, &format!("app={deploy_name}"), 3).await;

    let cancel = CancellationToken::new();
    let awareness = K8sAwareness::new(client.clone(), NAMESPACE.to_string(), cancel.clone());

    // Discover and let watcher initialize
    let pod_name = get_first_pod_name(&client, &format!("app={deploy_name}")).await;
    let pod_info = awareness
        .discover_controller(&pod_name)
        .await
        .expect("discover failed");

    // Wait for initial state
    tokio::time::sleep(Duration::from_secs(3)).await;

    // Scale down from 3 to 1
    let deployments: Api<Deployment> = Api::namespaced(client.clone(), NAMESPACE);
    let patch = serde_json::json!({ "spec": { "replicas": 1 } });
    deployments
        .patch(deploy_name, &PatchParams::default(), &Patch::Merge(&patch))
        .await
        .expect("failed to scale down deployment");

    // Wait for the watcher to detect the downscale
    let mut detected = false;
    for i in 0..30 {
        tokio::time::sleep(Duration::from_secs(2)).await;
        let reason = awareness
            .classify_departure(&pod_info.controller, &pod_info.generation)
            .await;
        tracing::debug!(iteration = i, ?reason, "polling downscale detection");
        if reason == DepartureReason::Downscale {
            detected = true;
            break;
        }
    }

    cancel.cancel();
    assert!(detected, "watcher should detect downscale");
}

#[tokio::test(flavor = "multi_thread")]
async fn watcher_detects_statefulset_rollout() {
    let (_container, client, _tmp) = setup_k3s().await;

    let ss_name = "test-ss-rollout";
    create_statefulset(&client, ss_name, 2).await;
    wait_for_ready_pods(&client, &format!("app={ss_name}"), 2).await;

    let cancel = CancellationToken::new();
    let awareness = K8sAwareness::new(client.clone(), NAMESPACE.to_string(), cancel.clone());

    // Discover the controller (starts a watcher)
    let pod_name = get_first_pod_name(&client, &format!("app={ss_name}")).await;
    let pod_info = awareness
        .discover_controller(&pod_name)
        .await
        .expect("discover failed");
    let old_generation = pod_info.generation.clone();

    // Give the watcher time to receive the initial state
    tokio::time::sleep(Duration::from_secs(3)).await;

    // Before rollout: departure should be Crash (steady state)
    let reason = awareness
        .classify_departure(&pod_info.controller, &old_generation)
        .await;
    assert_eq!(
        reason,
        DepartureReason::Crash,
        "steady state departure should be Crash"
    );

    // Trigger a rollout by changing the container image
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
        .patch(ss_name, &PatchParams::default(), &Patch::Merge(&patch))
        .await
        .expect("failed to patch statefulset");

    // Wait for the watcher to detect the rollout
    let mut detected = false;
    for i in 0..30 {
        tokio::time::sleep(Duration::from_secs(2)).await;
        let reason = awareness
            .classify_departure(&pod_info.controller, &old_generation)
            .await;
        tracing::debug!(iteration = i, ?reason, gen = %old_generation, "polling ss rollout detection");
        if reason == DepartureReason::Rollout {
            detected = true;
            break;
        }
    }

    cancel.cancel();
    assert!(
        detected,
        "watcher should detect statefulset rollout for old-gen pods"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn watcher_detects_statefulset_downscale() {
    let (_container, client, _tmp) = setup_k3s().await;

    let ss_name = "test-ss-downscale";
    create_statefulset(&client, ss_name, 3).await;
    wait_for_ready_pods(&client, &format!("app={ss_name}"), 3).await;

    let cancel = CancellationToken::new();
    let awareness = K8sAwareness::new(client.clone(), NAMESPACE.to_string(), cancel.clone());

    // Discover and let watcher initialize
    let pod_name = get_first_pod_name(&client, &format!("app={ss_name}")).await;
    let pod_info = awareness
        .discover_controller(&pod_name)
        .await
        .expect("discover failed");

    // Wait for initial state
    tokio::time::sleep(Duration::from_secs(3)).await;

    // Scale down from 3 to 1
    let statefulsets: Api<StatefulSet> = Api::namespaced(client.clone(), NAMESPACE);
    let patch = serde_json::json!({ "spec": { "replicas": 1 } });
    statefulsets
        .patch(ss_name, &PatchParams::default(), &Patch::Merge(&patch))
        .await
        .expect("failed to scale down statefulset");

    // Wait for the watcher to detect the downscale
    let mut detected = false;
    for i in 0..30 {
        tokio::time::sleep(Duration::from_secs(2)).await;
        let reason = awareness
            .classify_departure(&pod_info.controller, &pod_info.generation)
            .await;
        tracing::debug!(iteration = i, ?reason, "polling ss downscale detection");
        if reason == DepartureReason::Downscale {
            detected = true;
            break;
        }
    }

    cancel.cancel();
    assert!(detected, "watcher should detect statefulset downscale");
}
