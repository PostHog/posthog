# Kafka manager (prototype)

Observe-only control-plane prototype for Kafka producer health.
Capture pods push periodic health reports (delivery outcome counts, producer queue pressure, broker connectivity);
this service aggregates them into a live fleet view.
It is the first step toward the Kafka circuit breaker: gather the signals, watch them fleet-wide, tune trip conditions in shadow — before any component acts on them.

**This service makes no decisions and sends nothing back to its reporters.**
Clients treat it as a fire-and-forget telemetry target and must behave identically when it is down (see `capture`'s `manager_reporter` module).
Losing this service loses telemetry, nothing else.

> **⚠️ Purely internal service — never expose publicly.** No authentication of its own; deploy only behind the internal ingress.

## API

- `POST /v1/health-reports` — one `HealthReport` (see `kafka-manager-types`) per pod per interval. Counters are cumulative since process start; the manager derives interval rates and detects restarts from counter resets.
- `GET /v1/fleet` — JSON snapshot: per deployment, per pod — staleness, queue fill ratio, brokers down, last-interval failure ratio and throughput.
  The ingestion-control-plane's "Kafka fleet" tool renders this snapshot (set `KAFKA_MANAGER_URL` there).
- `/metrics`, `/_liveness`, `/_readiness`.

## Metrics

Per `deployment` label, refreshed every sweep:

- `kafka_manager_pods_reporting` — pods with a live (non-expired) report. `0` means the fleet went silent; the other gauges are meaningless then.
- `kafka_manager_queue_fill_ratio_max` — worst pod's producer queue fill (the leading stall indicator).
- `kafka_manager_brokers_down_max` — worst pod's count of non-UP brokers.
- `kafka_manager_delivery_failure_ratio_max` — worst pod's failures / attempts over its last report interval (excludes permanent per-message errors).
- `kafka_manager_delivery_acks_per_second` — fleet-wide delivery attempt throughput.
- `kafka_manager_reports_received_total`, `kafka_manager_pods_expired_total`.

## Configuration

| Env var | Default | Notes |
| --- | --- | --- |
| `BIND_HOST` / `BIND_PORT` | `0.0.0.0` / `3308` | Single listener: API, `/_liveness`, `/_readiness`, `/metrics` |
| `POD_TTL_SECONDS` | `60` | Reports older than this evict the pod from fleet state |
| `SWEEP_INTERVAL_SECONDS` | `5` | Eviction + gauge refresh cadence |

## Local development

```sh
cargo run -p kafka-manager

# Point a local capture at it:
CAPTURE_KAFKA_MANAGER_URL=http://127.0.0.1:3308 cargo run -p capture

# Watch the fleet view:
curl -s http://127.0.0.1:3308/v1/fleet | jq .
```

## Deployment notes

- Single replica is fine: state is in-memory and rebuilt from the report stream within one report interval.
- Needs a matrix entry in `.github/workflows/rust-docker-build.yml` plus a charts-repo app to deploy (not wired up yet — prototype).
