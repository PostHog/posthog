# Ingestion control plane

Internal web tool for the ingestion team. Single binary serving an embedded UI, with a sidebar of tools that is meant to grow over time.

> **⚠️ Purely internal service — never expose publicly.** This tool has no authentication of its own and its analysis results contain cross-customer data (team tokens, distinct_ids, event names). It must only be deployed behind the internal ingress (VPN/SSO), reachable by PostHog employees exclusively. It is an operational tool, not a product surface.

## Tools

### Lagging partitions

Discovers ingestion topics and consumer groups from the cluster by prefix (a group maps to the topics it has committed offsets on — no per-environment target config), scans committed offsets vs watermarks, and sorts by total outstanding messages. Drilling into a group shows per-partition lag; from there an analysis job reads a slice of the partition and aggregates **message headers only** (payloads are dropped, only their size is recorded):

- `head` mode starts at the group's committed offset — what the consumer is stuck on.
- `tail` mode samples the newest messages before the high watermark — what's arriving now.

Results are broken down per token (resolved to `team_id` via Postgres when `DATABASE_URL` is set), with events and distinct_ids nested under each token, plus a message-size distribution and header-flag counts. Analyses use a dedicated consumer group (`ingestion-control-plane-inspector`) and never touch the real group's offsets.

### Consumer debug

Lists live ingestion-consumer pods and serves the consumer's routing debug UI per pod at `/pods/<namespace>/<name>/` (static pods use the `static` pseudo-namespace), backed by a proxy to the pod's debug API (`/debug/state`, `/debug/load`, SSE `/debug/events`). The UI lives here; the consumer only exposes the JSON/SSE API (gated behind `DEBUG_UI_ENABLED` on the consumer side).

## Configuration

| Env var | Default | Notes |
| --- | --- | --- |
| `BIND_HOST` / `BIND_PORT` | `0.0.0.0` / `3305` | Single listener: UI, API, `/_liveness`, `/_readiness`, `/metrics` |
| `KAFKA_HOSTS` | `localhost:19092` | |
| `KAFKA_TLS` | `false` | |
| `TOPIC_PREFIX` | `ingestion-` | Topics are discovered from cluster metadata by prefix |
| `GROUP_PREFIX` | `ingestion-` | Consumer groups are discovered by prefix; a group maps to the topics it has committed offsets on |
| `DISCOVERY_CACHE_TTL_SECS` | `300` | Discovered targets are cached; topology changes rarely |
| `OVERVIEW_CACHE_TTL_SECS` | `15` | Overview scans are cached with single-flight refresh, bounding broker load from repeated requests |
| `DATABASE_URL` | empty | Read replica; empty disables token → team resolution |
| `ANALYSIS_MESSAGE_COUNT` | `10000` | Messages per analysis |
| `ANALYSIS_DEADLINE_SECS` | `120` | |
| `ANALYSIS_MAX_FETCH_BYTES` | `536870912` | Kafka transfers full records even for header-only analysis |
| `POD_DISCOVERY_MODE` | `kubernetes` | `static` for local testing |
| `STATIC_PODS` | `local=127.0.0.1:3301` | `name=host:port` pairs for static mode |
| `POD_LABEL_SELECTORS` | `ingestion-analytics-main/app=ingestion-analytics-main,ingestion-analytics-async/app=ingestion-analytics-async` | One `namespace/key=value` per entry (each lane runs in its own namespace); bare `key=value` uses `K8S_NAMESPACE` |
| `K8S_NAMESPACE` | `posthog` | Default namespace for unqualified selector entries |
| `DEBUG_PORT` | `3301` | Consumer debug API port (kubernetes mode) |

## Local development

```sh
# Seed a lagging-partition scenario (one dominant team on partition 0):
DATABASE_URL=postgres://posthog:posthog@db:5432/posthog \
    KAFKA_HOSTS=localhost:9092 \
    cargo run -p ingestion-control-plane --example seed_lag

# Run the service against it, with a locally running ingestion-consumer on :3401.
# The seeded ingestion-lag-demo topic/group are picked up by the default
# `ingestion-` discovery prefixes:
BIND_PORT=3305 KAFKA_HOSTS=localhost:9092 \
    DATABASE_URL=postgres://posthog:posthog@db:5432/posthog \
    POD_DISCOVERY_MODE=static STATIC_PODS="local-consumer=127.0.0.1:3401" \
    cargo run -p ingestion-control-plane
```

Then open `http://localhost:3305/`.

## Deployment notes

- Image `ingestion-control-plane` is built via `.github/rust-images.yml`; a deploy needs a matrix entry in `rust-docker-build.yml` plus a charts-repo app.
- Kubernetes mode needs RBAC: `get`/`list` on `pods` in the ingestion namespace, and network egress to pod IPs on the debug port, Kafka, and the Postgres replica.
