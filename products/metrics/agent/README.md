# PostHog metrics agent

A small deployable image that scrapes the Prometheus `/metrics` endpoints you already expose and forwards them to PostHog as OTLP metrics.
Use it when you want PostHog Metrics without touching application code: no PostHog SDK, no exporter changes.

Under the hood it is the OpenTelemetry Collector (contrib distribution, pinned) with a PostHog-rendered config:
prometheus receiver → memory_limiter + batch → otlphttp exporter pointed at PostHog ingestion.
Exemplars survive the trip: counters and histograms scraped with OpenMetrics exemplars (`trace_id`/`span_id`) become clickable trace links in the PostHog Metrics UI.

## Quickstart (Docker)

```sh
docker run -d --name posthog-metrics-agent \
  -e POSTHOG_API_KEY=<your project API key> \
  -e POSTHOG_HOST=https://us.i.posthog.com \
  -e SCRAPE_TARGETS=your-app:9090,your-worker:9091 \
  posthog/metrics-agent:latest
```

EU cloud: set `POSTHOG_HOST=https://eu.i.posthog.com`.

## Environment variables

| Variable              | Required | Default                    | Meaning                                                                 |
| --------------------- | -------- | -------------------------- | ----------------------------------------------------------------------- |
| `POSTHOG_API_KEY`     | yes      | —                          | Project API key, sent as `Authorization: Bearer`                        |
| `POSTHOG_HOST`        | no       | `https://us.i.posthog.com` | PostHog ingestion origin                                                |
| `SCRAPE_TARGETS`      | yes\*    | —                          | Comma-separated `host:port` list to scrape                              |
| `SCRAPE_INTERVAL`     | no       | `15s`                      | Scrape interval                                                         |
| `SCRAPE_METRICS_PATH` | no       | `/metrics`                 | Metrics path on the targets                                             |
| `SCRAPE_JOB_NAME`     | no       | `posthog-metrics-agent`    | Prometheus job name; becomes `service_name` on every metric in PostHog  |
| `POSTHOG_DEBUG`       | no       | unset                      | `1`/`true`: also log exported batches to the container's stdout         |
| `POSTHOG_INGEST_PATH` | no       | `/i/v1/metrics`            | Advanced: override the ingest route (used by tests)                     |
| `SHARD_COUNT`         | no       | `1`                        | Size of an agent fleet; above 1 each instance scrapes only its share    |
| `SHARD_INDEX`         | no       | from hostname ordinal      | This instance's index in `0..SHARD_COUNT-1` (see Scaling out)           |
| `PERSIST_QUEUE`       | no       | unset                      | `1`/`true`: buffer undelivered batches to disk so restarts lose nothing |
| `QUEUE_DIR`           | no       | `/var/lib/posthog-agent`   | Where the persistent queue is stored                                    |

\* not required when you mount your own scrape configs, see below.

## Scaling out (sharding)

A single agent scrapes every target itself.
For a large target set, run a fleet: set `SHARD_COUNT` to the fleet size and each instance keeps only the targets whose address hashes to its `SHARD_INDEX`, so the fleet partitions the work with no coordination, no double-counting, and no gaps.

`SHARD_INDEX` defaults to the trailing ordinal of the container hostname (`agent-0` → `0`), so a Kubernetes StatefulSet gets correct indices for free; set it explicitly for other orchestrators.
This is the same target-sharding model vmagent uses.
The Helm chart wires this up automatically — set `shards: <n>` and it runs a StatefulSet fleet.

## Durability

By default the export queue is in memory: if PostHog is briefly unreachable the agent retries, but a restart during that window drops whatever was buffered.
Set `PERSIST_QUEUE=1` (and give the container a durable volume at `QUEUE_DIR`) to back the queue with disk, so samples scraped during an outage survive restarts and deliver on recovery.
The Helm chart's `persistence.enabled=true` provisions the volume for you.

## Escape hatches

Checked in this order:

1. **Full config override**: mount a complete collector config at `/etc/posthog/config.yaml`. It is used verbatim (`${env:POSTHOG_API_KEY}`-style references still resolve). This is how the Helm chart drives the image.
2. **Custom scrape configs**: mount a YAML list of Prometheus `scrape_configs` at `/etc/posthog/scrape_configs.yaml` to replace the env-generated job while keeping the PostHog exporter wiring. Tip: add `scrape_protocols: [OpenMetricsText1.0.0, OpenMetricsText0.0.1, PrometheusText0.0.4]` to each job so exemplars keep flowing.
3. Otherwise the scrape job is rendered from `SCRAPE_TARGETS`.

## Exemplars (metric ↔ trace linking)

- The agent scrapes with OpenMetrics negotiation enabled, which is the only Prometheus exposition format that carries exemplars. Exemplar `trace_id`/`span_id` labels are converted to OTLP exemplars and linked to traces in PostHog automatically.
- Exemplars exist only on counters and histogram buckets; gauges never have them.
- The agent preserves exemplars, it cannot create them: your application's Prometheus client must be configured to attach them (for example prom-client's `enableExemplars`, or a span-context supplier in Micrometer). If your endpoint only serves classic Prometheus text, metrics still flow but without trace links.

## Notes and limits

- One `service_name` per scrape job: Prometheus `job_name` maps to `service_name` in PostHog and target labels cannot override it. Run one agent (or one mounted scrape job) per logical service if you need distinct service names.
- Don't run bare replicas of one agent — they all scrape the same targets and double-count. To scale, use a sharded fleet (see Scaling out) so each instance takes a disjoint slice.
- Metrics are rate limited server side per project; keep label cardinality sane (avoid user IDs, request IDs and the like as label values).
- Health endpoint for probes: `:13133`.
- The agent exposes its own metrics (scrape success, queue depth, points sent/dropped) at `:8888/metrics` — point your monitoring at it, or scrape it with the agent itself.
- The collector version is pinned in the `Dockerfile`; bump it together with `tests/integration/docker-compose.yml`.

## Development

```sh
# Config rendering golden tests (pure sh, no docker):
tests/render/run.sh

# Helm chart render + behavior tests (needs helm):
tests/helm/run.sh

# Integration smoke test (builds the image; asserts exemplars survive scrape -> OTLP):
tests/integration/run.sh

# Durability: scrape through a simulated outage, hard-kill, assert nothing lost:
tests/durability/run.sh

# Fleet sharding at scale (synthetic target farm; completeness + disjointness):
tests/scale/run.sh

# Real-Kubernetes E2E on kind (restricted-PSS admission, discovery, sharding, exemplars):
tests/kind/run.sh
```

End-to-end against the local dev stack (requires `hogli start` with capture-logs and the metrics ingestion consumer running):

```sh
docker build -t posthog-metrics-agent:dev .
docker run --rm \
  -e POSTHOG_API_KEY=phc_local \
  -e POSTHOG_HOST=http://host.docker.internal:4320 \
  -e SCRAPE_TARGETS=host.docker.internal:6738 \
  -e SCRAPE_METRICS_PATH=/_metrics \
  -e SCRAPE_JOB_NAME=agent-e2e \
  posthog-metrics-agent:dev
```

Then observe rows arriving:

```sql
SELECT service_name, metric_name, count()
FROM posthog.metrics
WHERE service_name = 'agent-e2e'
GROUP BY 1, 2
```
