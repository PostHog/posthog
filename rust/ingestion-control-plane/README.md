# Ingestion control plane

Internal web tool for the ingestion team. Single binary serving an embedded UI, with a sidebar of tools that is meant to grow over time.

> **⚠️ Purely internal service — never expose publicly.** This tool has no authentication of its own and its analysis results contain cross-customer data (team tokens, distinct_ids, event names). It must only be deployed behind the internal ingress (VPN/SSO), reachable by PostHog employees exclusively. It is an operational tool, not a product surface.

## Tools

### Lagging partitions

Discovers ingestion topics and consumer groups from the cluster by prefix (a group maps to the topics it has committed offsets on — no per-environment target config), scans committed offsets vs watermarks, and sorts by total outstanding messages. Drilling into a group shows per-partition lag; from there an analysis job reads a slice of the partition and aggregates **message headers only** (payloads are dropped, only their size is recorded):

- `head` mode starts at the group's committed offset — what the consumer is stuck on.
- `tail` mode samples the newest messages before the high watermark — what's arriving now.

Results are broken down per token (resolved to `team_id` via Postgres when `DATABASE_URL` is set), with events and distinct_ids nested under each token, plus a message-size distribution and header-flag counts. Analyses use a dedicated consumer group (`ingestion-control-plane-inspector`) and never touch the real group's offsets.

Clicking a team, event, or distinct_id in an analysis result opens the message browser: a filtered scan over the same partition (`/api/messages`) that lists individual matching messages. Filters are equality matches on the `token`, `event`, and `distinct_id` headers; a facets sidebar aggregates the loaded messages so results can be narrowed further. Each request returns up to 100 matches and a cursor, and "Load more" resumes from it; per-request scanning is bounded by a message budget, a deadline, and a byte budget so a rarely-matching filter still returns promptly. Matched messages carry their payload (truncated to 64 KB per message), shown by expanding a row, so this surface exposes raw event payloads — another reason the tool must stay behind the internal ingress.

### Consumer debug

Lists live ingestion-consumer pods and serves the consumer's routing debug UI per pod at `/pods/<namespace>/<name>/` (static pods use the `static` pseudo-namespace), backed by a proxy to the pod's debug API (`/debug/state`, `/debug/load`, SSE `/debug/events`). The UI lives here; the consumer only exposes the JSON/SSE API (gated behind `DEBUG_UI_ENABLED` on the consumer side).

### Personhog topology

Protocol-aware view of personhog's etcd coordination state (`PERSONHOG_ETCD_PREFIX`, default `/personhog/`): the whole prefix is read in one consistent snapshot and interpreted with the `personhog-coordination` types and the coordinator's own pure predicates, so the derived diagnostics cannot drift from the protocol. Shows the elected coordinator, registered pods and routers (with remaining lease TTLs), per-partition ownership, and in-flight handoffs with their phase age and what each is waiting on — distinguishing a stuck participant ("waiting on freeze acks from router-2") from a stuck coordinator ("quorum met; waiting on the coordinator to advance"). Derived issues cover stuck handoffs past their per-phase deadline, assignments owned by unregistered pods with no replanning handoff, lingering `Complete` records the coordinator hasn't cleaned up, dead new owners awaiting cancellation, unassigned partitions, stale acks from previous handoff attempts, and unparseable records. The deadline knobs (`PERSONHOG_HANDOFF_DEADLINE_SECS`, `PERSONHOG_WARMING_DEADLINE_SECS`) must match the coordinator's to agree with its cancellation decisions. Read-only: the tool never writes coordination state, and a force-reassignment must go through a handoff record, never a raw assignment write.

### Etcd explorer

Generic key browser for the same etcd cluster: keys under a prefix render as a collapsible tree (with per-key version, lease, and size; the top level and single-child chains expand automatically), and a key's detail shows its value, revisions, and remaining lease TTL, with edit, create, and delete. Operations are bounded to `ETCD_ALLOWED_PREFIXES`. Writes bypass every coordination protocol, so each one confirms first; writing a lease-backed key warns that it detaches the key from its lease, and writing a personhog `assignments/` key gets an extra warning because routers only observe ownership through handoff `Complete` events — a raw assignment write is invisible to them and leaves an unfenced old owner serving. Deletes are single-key only; there is deliberately no prefix delete.

Both etcd tools are disabled (their APIs return 503) unless `ETCD_ENDPOINTS` is set.

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
| `BROWSE_SCAN_MESSAGE_COUNT` | `25000` | Messages scanned per message-browser request |
| `BROWSE_DEADLINE_SECS` | `10` | |
| `BROWSE_MAX_FETCH_BYTES` | `268435456` | Byte budget per message-browser request |
| `BROWSE_MAX_CONCURRENT` | `3` | Concurrent browse requests; more get 429 |
| `POD_DISCOVERY_MODE` | `kubernetes` | `static` for local testing |
| `STATIC_PODS` | `local=127.0.0.1:3301` | `name=host:port` pairs for static mode |
| `POD_LABEL_SELECTORS` | `ingestion-analytics-main/app=ingestion-analytics-main,ingestion-analytics-async/app=ingestion-analytics-async` | One `namespace/key=value` per entry (each lane runs in its own namespace); bare `key=value` uses `K8S_NAMESPACE` |
| `K8S_NAMESPACE` | `posthog` | Default namespace for unqualified selector entries |
| `DEBUG_PORT` | `3301` | Consumer debug API port (kubernetes mode) |
| `ETCD_ENDPOINTS` | empty | Comma-separated etcd endpoints; empty disables the etcd explorer and personhog topology tools |
| `ETCD_ALLOWED_PREFIXES` | `/` | Comma-separated key prefixes the etcd explorer may read and write |
| `PERSONHOG_ETCD_PREFIX` | `/personhog/` | Prefix the personhog coordination state lives under; must match the personhog services' `ETCD_PREFIX` |
| `PERSONHOG_HANDOFF_DEADLINE_SECS` | `120` | Per-phase deadline for flagging stuck handoffs; must match `COORDINATOR_HANDOFF_DEADLINE_SECS` |
| `PERSONHOG_WARMING_DEADLINE_SECS` | `1800` | Warming-phase deadline; must match `COORDINATOR_WARMING_DEADLINE_SECS` |

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
- Kubernetes mode needs RBAC: `get`/`list` on `pods` in the ingestion namespace, and network egress to pod IPs on the debug port, Kafka, the Postgres replica, and (when the etcd tools are enabled) the personhog etcd cluster.
