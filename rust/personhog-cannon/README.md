# personhog-cannon

Load testing and validation harness for the personhog person properties service.
Sends property updates through the router's gRPC API, reads them back, and verifies consistency while collecting latency stats.

Designed to run as a pod in the same k8s namespace as the personhog stack, so it has direct access to services and can use kubectl for chaos operations.

## Deployment

The image is built automatically by CI (`.github/workflows/rust-docker-build.yml`) using `rust/Dockerfile.personhog-cannon` and pushed to `ghcr.io/posthog/posthog/personhog-cannon`.
It follows the same pipeline as all other Rust services, with the one difference being a custom Dockerfile that adds kubectl to the runtime image for chaos operations.

### Deploy to dev

Apply the k8s manifest (creates ServiceAccount, Role, RoleBinding, and the cannon pod):

```bash
kubectl apply -f rust/personhog-cannon/k8s/cannon.yaml
```

The pod starts with `sleep infinity` — shell in and run commands interactively:

```bash
kubectl exec -it personhog-cannon -n posthog -- bash
```

Environment variables (`ROUTER_URL`, `ETCD_ENDPOINTS`, `ETCD_PREFIX`, `NAMESPACE`) are set in the manifest.
Override them or pass CLI flags as needed.

## Subcommands

### `discover`

Find persons in a team to use as test targets.

```bash
# By distinct ID
personhog-cannon discover --team-id 1 --distinct-ids user1,user2,user3

# By person ID
personhog-cannon discover --team-id 1 --person-ids 42,43,44
```

Prints a table of matching persons (id, uuid, version, property count) and a copy-pasteable `--person-ids` string for use with `blast` or `consistency`.

### `blast`

High-throughput concurrent property updates with optional read-back verification.

```bash
# Discover targets by distinct ID, then blast for 30 seconds
personhog-cannon blast \
  --team-id 1 \
  --discover-distinct-ids user1,user2 \
  --concurrency 50 \
  --duration 30s

# Use known person IDs, skip verification
personhog-cannon blast \
  --team-id 1 \
  --person-ids 42,43,44,45 \
  --concurrency 100 \
  --duration 2m \
  --verify false
```

Each worker picks a random person from the target set and sends an `UpdatePersonProperties` request with a generated `$set` property.
After the blast phase, if `--verify` is enabled (default), reads back each person with STRONG consistency and checks that written properties match.

| Flag | Default | Description |
|------|---------|-------------|
| `--concurrency` | 10 | Number of concurrent workers |
| `--duration` | required | How long to run (e.g. `30s`, `2m`) |
| `--property-prefix` | `cannon_` | Prefix for generated property keys |
| `--verify` | true | Read-back verification after writes |
| `--person-ids` | - | Explicit person IDs to target |
| `--discover-distinct-ids` | - | Discover persons by distinct ID first |

### `consistency`

Focused write-then-read consistency validation.
Each worker writes a unique property, then immediately reads it back with STRONG consistency and asserts the value matches.

```bash
personhog-cannon consistency \
  --team-id 1 \
  --person-ids 42,43 \
  --concurrency 5 \
  --iterations 100

# With a read delay to test slightly stale reads
personhog-cannon consistency \
  --team-id 1 \
  --discover-distinct-ids user1 \
  --iterations 500 \
  --read-delay 10ms
```

| Flag | Default | Description |
|------|---------|-------------|
| `--concurrency` | 5 | Number of concurrent workers |
| `--iterations` | 100 | Write-then-read cycles per worker |
| `--read-delay` | 0ms | Delay between write and read-back |

## Output

Both `blast` and `consistency` print a summary table:

```text
=== personhog-cannon blast results ===
  Duration: 30.02s | Team: 1 | Persons: 4

  Operation  Total   Success  Failed  p50     p95     p99     RPS
  writes     15000   14998    2       1.2ms   3.4ms   8.1ms   499.8
  reads      4       4        0       0.8ms   2.1ms   5.3ms   -

  Consistency violations: 0
```

The process exits with a non-zero status if any consistency violations are detected.

### `chaos`

Chaos testing — inspect coordination state, kill/restart leaders, scale the StatefulSet, and run blasts under disruption.
All chaos commands use kubectl and require the cannon pod's ServiceAccount to have the appropriate RBAC permissions (provided by the k8s manifest).

#### `chaos status`

Show the current etcd coordination state: pods, partition assignments, handoffs, routers.

```bash
personhog-cannon chaos status
```

#### `chaos kill`

Force-delete a leader pod (simulates crash). With `--fast`, also revokes the etcd lease for instant coordinator detection (otherwise the 30s lease TTL must expire).

```bash
# Force-delete + lease revoke for instant detection
personhog-cannon chaos kill --pod-name personhog-leader-0 --fast

# Just force-delete (coordinator detects after lease TTL)
personhog-cannon chaos kill --pod-name personhog-leader-0

# Auto-pick a running leader pod
personhog-cannon chaos kill --fast
```

#### `chaos shutdown`

Gracefully delete a leader pod. The pod receives SIGTERM, sets its status to Draining, the coordinator creates handoffs, and the pod exits after all partitions are transferred.

```bash
personhog-cannon chaos shutdown --pod-name personhog-leader-0

# Auto-pick a running leader pod
personhog-cannon chaos shutdown
```

#### `chaos scale-up`

Scale the leader StatefulSet up. If `--replicas` is not set, increments by 1.

```bash
# Add one more replica
personhog-cannon chaos scale-up

# Scale to a specific count
personhog-cannon chaos scale-up --replicas 3
```

Waits for the new pod to become Ready and register in etcd.

#### `chaos run`

The integrated scenario — runs a blast while scheduling disruptions mid-test.

```bash
# Kill a leader 15s into a 60s blast, then scale up at 30s
personhog-cannon chaos run \
  --team-id 1 --person-ids 42,43 \
  --duration 60s --concurrency 20 \
  --kill-after 15s \
  --scale-up-after 30s

# Kill + graceful shutdown cycle
personhog-cannon chaos run \
  --team-id 1 --discover-distinct-ids user1 \
  --duration 90s --concurrency 10 \
  --kill-after 20s \
  --scale-up-after 40s \
  --shutdown-after 70s --shutdown-pod-name personhog-leader-1
```

Prints initial and post-chaos coordination state, blast stats with latency histograms, and consistency verification results.

| Disruption flag | Description |
|----------------|-------------|
| `--kill-after` | Force-delete a leader pod + revoke etcd lease |
| `--scale-up-after` | Scale the StatefulSet up by 1 |
| `--shutdown-after` | Gracefully delete a leader pod |

## Global options

| Flag | Env var | Default | Description |
|------|---------|---------|-------------|
| `--router-url` | `ROUTER_URL` | `http://localhost:50052` | gRPC address of the personhog router |
| `--namespace` | `NAMESPACE` | `posthog` | k8s namespace for chaos commands |
| `--etcd-endpoints` | `ETCD_ENDPOINTS` | `http://localhost:2379` | etcd cluster endpoints |
| `--etcd-prefix` | `ETCD_PREFIX` | `/personhog/` | etcd key prefix |

When deployed via the k8s manifest, these are pre-configured as environment variables.

Set `RUST_LOG=personhog_cannon=debug` for verbose logging of individual request outcomes.
