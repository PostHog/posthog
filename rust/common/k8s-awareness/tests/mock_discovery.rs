use std::pin::pin;

use http::{Request, Response};
use kube::client::Body;
use kube::Client;
use tower_test::mock;

use k8s_awareness::{discover_controller, ControllerKind, DiscoveryError};

const NAMESPACE: &str = "default";

// ── Helpers ──────────────────────────────────────────────

fn mock_client() -> (Client, mock::Handle<Request<Body>, Response<Body>>) {
    let (service, handle) = mock::pair::<Request<Body>, Response<Body>>();
    let client = Client::new(service, NAMESPACE);
    (client, handle)
}

fn json_response(body: serde_json::Value) -> Response<Body> {
    Response::builder()
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap()
}

fn not_found_response() -> Response<Body> {
    let body = serde_json::json!({
        "kind": "Status",
        "apiVersion": "v1",
        "status": "Failure",
        "message": "pods \"missing\" not found",
        "reason": "NotFound",
        "code": 404
    });
    Response::builder()
        .status(404)
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap()
}

fn pod_json(
    name: &str,
    owner_kind: &str,
    owner_name: &str,
    label_key: &str,
    label_value: &str,
) -> serde_json::Value {
    serde_json::json!({
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": NAMESPACE,
            "labels": { label_key: label_value },
            "ownerReferences": [{
                "apiVersion": "apps/v1",
                "kind": owner_kind,
                "name": owner_name,
                "uid": "fake-uid",
                "controller": true
            }]
        },
        "spec": {
            "containers": [{ "name": "test", "image": "test:latest" }]
        }
    })
}

fn replicaset_json(name: &str, deploy_name: &str) -> serde_json::Value {
    serde_json::json!({
        "apiVersion": "apps/v1",
        "kind": "ReplicaSet",
        "metadata": {
            "name": name,
            "namespace": NAMESPACE,
            "ownerReferences": [{
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "name": deploy_name,
                "uid": "fake-deploy-uid",
                "controller": true
            }]
        },
        "spec": {
            "replicas": 1,
            "selector": { "matchLabels": { "app": "test" } },
            "template": {
                "metadata": { "labels": { "app": "test" } },
                "spec": {
                    "containers": [{ "name": "test", "image": "test:latest" }]
                }
            }
        }
    })
}

// ── Tests ────────────────────────────────────────────────

#[tokio::test]
async fn deployment_discovery_walks_replicaset() {
    let (client, handle) = mock_client();

    let mock_handler = tokio::spawn(async move {
        let mut handle = pin!(handle);

        // 1. GET pod
        let (request, send) = handle.next_request().await.expect("expected pod request");
        assert_eq!(request.method(), http::Method::GET);
        assert!(request.uri().path().ends_with("/pods/my-pod"));
        send.send_response(json_response(pod_json(
            "my-pod",
            "ReplicaSet",
            "my-deploy-abc123",
            "pod-template-hash",
            "abc123",
        )));

        // 2. GET replicaset
        let (request, send) = handle.next_request().await.expect("expected RS request");
        assert_eq!(request.method(), http::Method::GET);
        assert!(request
            .uri()
            .path()
            .ends_with("/replicasets/my-deploy-abc123"));
        send.send_response(json_response(replicaset_json(
            "my-deploy-abc123",
            "my-deploy",
        )));
    });

    let info = discover_controller(&client, NAMESPACE, "my-pod")
        .await
        .expect("discovery should succeed");

    assert_eq!(info.controller.kind, ControllerKind::Deployment);
    assert_eq!(info.controller.name, "my-deploy");
    assert_eq!(info.generation, "abc123");

    mock_handler.await.unwrap();
}

#[tokio::test]
async fn statefulset_discovery_is_direct() {
    let (client, handle) = mock_client();

    let mock_handler = tokio::spawn(async move {
        let mut handle = pin!(handle);

        // Only 1 request: GET pod (no RS lookup needed)
        let (request, send) = handle.next_request().await.expect("expected pod request");
        assert_eq!(request.method(), http::Method::GET);
        assert!(request.uri().path().ends_with("/pods/my-ss-pod"));
        send.send_response(json_response(pod_json(
            "my-ss-pod",
            "StatefulSet",
            "my-statefulset",
            "controller-revision-hash",
            "my-statefulset-rev1",
        )));
    });

    let info = discover_controller(&client, NAMESPACE, "my-ss-pod")
        .await
        .expect("discovery should succeed");

    assert_eq!(info.controller.kind, ControllerKind::StatefulSet);
    assert_eq!(info.controller.name, "my-statefulset");
    assert_eq!(info.generation, "my-statefulset-rev1");

    mock_handler.await.unwrap();
}

#[tokio::test]
async fn pod_not_found_returns_error() {
    let (client, handle) = mock_client();

    let mock_handler = tokio::spawn(async move {
        let mut handle = pin!(handle);
        let (_request, send) = handle.next_request().await.expect("expected pod request");
        send.send_response(not_found_response());
    });

    let err = discover_controller(&client, NAMESPACE, "missing")
        .await
        .expect_err("should fail for missing pod");

    assert!(
        matches!(err, DiscoveryError::PodNotFound(ref name) if name == "missing"),
        "expected PodNotFound, got: {err}"
    );

    mock_handler.await.unwrap();
}

#[tokio::test]
async fn pod_without_owner_refs_returns_error() {
    let (client, handle) = mock_client();

    let mock_handler = tokio::spawn(async move {
        let mut handle = pin!(handle);
        let (_request, send) = handle.next_request().await.expect("expected pod request");
        send.send_response(json_response(serde_json::json!({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "orphan-pod",
                "namespace": NAMESPACE,
            },
            "spec": {
                "containers": [{ "name": "test", "image": "test:latest" }]
            }
        })));
    });

    let err = discover_controller(&client, NAMESPACE, "orphan-pod")
        .await
        .expect_err("should fail for pod without owners");

    assert!(
        matches!(err, DiscoveryError::NoOwnerReferences(ref name) if name == "orphan-pod"),
        "expected NoOwnerReferences, got: {err}"
    );

    mock_handler.await.unwrap();
}

#[tokio::test]
async fn unsupported_owner_kind_returns_error() {
    let (client, handle) = mock_client();

    let mock_handler = tokio::spawn(async move {
        let mut handle = pin!(handle);
        let (_request, send) = handle.next_request().await.expect("expected pod request");
        send.send_response(json_response(serde_json::json!({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "job-pod",
                "namespace": NAMESPACE,
                "ownerReferences": [{
                    "apiVersion": "batch/v1",
                    "kind": "Job",
                    "name": "my-job",
                    "uid": "fake-uid",
                    "controller": true
                }]
            },
            "spec": {
                "containers": [{ "name": "test", "image": "test:latest" }]
            }
        })));
    });

    let err = discover_controller(&client, NAMESPACE, "job-pod")
        .await
        .expect_err("should fail for unsupported owner");

    assert!(
        matches!(err, DiscoveryError::UnsupportedOwner { ref kind, .. } if kind == "Job"),
        "expected UnsupportedOwner(Job), got: {err}"
    );

    mock_handler.await.unwrap();
}

#[tokio::test]
async fn deployment_pod_missing_hash_label_returns_error() {
    let (client, handle) = mock_client();

    let mock_handler = tokio::spawn(async move {
        let mut handle = pin!(handle);

        // 1. GET pod (owned by RS but missing pod-template-hash label)
        let (_request, send) = handle.next_request().await.expect("expected pod request");
        send.send_response(json_response(serde_json::json!({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "no-hash-pod",
                "namespace": NAMESPACE,
                "ownerReferences": [{
                    "apiVersion": "apps/v1",
                    "kind": "ReplicaSet",
                    "name": "my-rs",
                    "uid": "fake-uid",
                    "controller": true
                }]
            },
            "spec": {
                "containers": [{ "name": "test", "image": "test:latest" }]
            }
        })));

        // 2. GET replicaset (discovery fetches the RS before checking labels)
        let (_request, send) = handle.next_request().await.expect("expected RS request");
        send.send_response(json_response(replicaset_json("my-rs", "my-deploy")));
    });

    let err = discover_controller(&client, NAMESPACE, "no-hash-pod")
        .await
        .expect_err("should fail for missing hash label");

    assert!(
        matches!(err, DiscoveryError::MissingGenerationLabel(ref name) if name == "no-hash-pod"),
        "expected MissingGenerationLabel, got: {err}"
    );

    mock_handler.await.unwrap();
}

#[tokio::test]
async fn replicaset_without_deployment_owner_returns_error() {
    let (client, handle) = mock_client();

    let mock_handler = tokio::spawn(async move {
        let mut handle = pin!(handle);

        // 1. GET pod (owned by RS, has hash label)
        let (_request, send) = handle.next_request().await.expect("expected pod request");
        send.send_response(json_response(pod_json(
            "orphan-rs-pod",
            "ReplicaSet",
            "standalone-rs",
            "pod-template-hash",
            "abc123",
        )));

        // 2. GET replicaset (no Deployment owner)
        let (_request, send) = handle.next_request().await.expect("expected RS request");
        send.send_response(json_response(serde_json::json!({
            "apiVersion": "apps/v1",
            "kind": "ReplicaSet",
            "metadata": {
                "name": "standalone-rs",
                "namespace": NAMESPACE,
            },
            "spec": {
                "replicas": 1,
                "selector": { "matchLabels": { "app": "test" } },
                "template": {
                    "metadata": { "labels": { "app": "test" } },
                    "spec": {
                        "containers": [{ "name": "test", "image": "test:latest" }]
                    }
                }
            }
        })));
    });

    let err = discover_controller(&client, NAMESPACE, "orphan-rs-pod")
        .await
        .expect_err("should fail for RS without deploy owner");

    assert!(
        matches!(err, DiscoveryError::ReplicaSetNoDeploymentOwner(ref name) if name == "standalone-rs"),
        "expected ReplicaSetNoDeploymentOwner, got: {err}"
    );

    mock_handler.await.unwrap();
}
