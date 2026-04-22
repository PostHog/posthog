# k8s-awareness

Classifies why a Kubernetes pod is departing by watching its owning controller (Deployment or StatefulSet). Consumers of this library can use the departure reason to choose the right response: drain gracefully on rollout, redistribute permanently on downscale, or reassign quickly on crash.

## How it works

```text
Pod departs
    │
    ▼
┌─────────────────────┐
│  discover_controller │  Walk ownerReferences:
│                      │  pod → ReplicaSet → Deployment
│                      │  pod → StatefulSet (direct)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   K8sAwareness       │  Watch the controller for changes.
│   (watcher)          │  Track ClusterIntent per controller:
│                      │  replicas, generation hashes, rollout state
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  classify_departure  │  Compare pod's generation + replica counts
│                      │  → Rollout | Downscale | Crash | Unknown
└─────────────────────┘
```

### Departure classification

| Signal | Result |
|---|---|
| Pod's generation hash differs from controller's current/target generation | **Rollout** |
| Desired replicas < previous replicas | **Downscale** |
| Generation matches, replicas stable | **Crash** |
| Controller not watched | **Unknown** |

### Generation tracking

Deployments and StatefulSets use different mechanisms:

- **Deployment**: each ReplicaSet gets a `pod-template-hash` label. During a rollout, a new RS is created with a new hash. The watcher lists RSes to find `current_generation` (active hash) and `target_generation` (new hash during rollout).
- **StatefulSet**: uses `controller-revision-hash` on pods and `status.currentRevision` / `status.updateRevision` on the StatefulSet itself.

## Usage

```rust
use k8s_awareness::{K8sAwareness, DepartureReason};
use tokio_util::sync::CancellationToken;

let cancel = CancellationToken::new();
let awareness = K8sAwareness::new(client, "default".into(), cancel);

// On member join: discover its controller and start watching
let pod_info = awareness.discover_controller("my-pod-abc123-xyz").await?;

// On member departure: classify why
let reason = awareness
    .classify_departure(&pod_info.controller, &pod_info.generation)
    .await;

match reason {
    DepartureReason::Rollout => { /* drain gracefully, replacement coming */ }
    DepartureReason::Downscale => { /* redistribute permanently */ }
    DepartureReason::Crash => { /* fast reassignment, pod will restart */ }
    DepartureReason::Unknown => { /* fall back to default behavior */ }
}
```

## Testing

Mock tests (no Docker required):

```bash
cargo test -p k8s-awareness --test mock_discovery
```

Integration tests against a real k3s cluster via testcontainers (requires Docker):

```bash
cargo test -p k8s-awareness --test k3s_integration
```
