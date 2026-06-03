# prom-compat

PostHog metrics exposed via the Prometheus HTTP API for compatibility with Grafana, alertmanager, promtool, and the rest of the Prometheus ecosystem.

## What this is

A Go service that will eventually:

- Listen on `:9090` (configurable via `PORT`)
- Serve `/api/v1/query`, `/query_range`, `/labels`, `/label/{name}/values`, `/series`, `/metadata`
- Read from the `metrics1` ClickHouse table on the logs cluster
- Authenticate via PostHog personal API keys (`Authorization: Bearer phx_...`)
- Resolve a tenant per request via `/p/{project_id}/...` URL prefix

This is an **ecosystem adapter**, not a replacement for the native metrics UI (`products/metrics/`). Both planes read the same storage.

## Design doc

See [`docs/internal/prom-compat/design.md`](../../docs/internal/prom-compat/design.md) for the full architectural plan and rationale.

## Running locally

From the repo root, via the shared Go dev runner (sets `HOST`/`PORT` and `cd`s into the service):

```bash
bin/start-go-service prom-compat
```

Or directly:

```bash
cd services/prom-compat && go run .
```

## Configuration

| Env var                            | Default   | Required | Purpose                            |
| ---------------------------------- | --------- | -------- | ---------------------------------- |
| `HOST`                             | `0.0.0.0` | no       | Bind address                       |
| `PORT`                             | `9090`    | no       | HTTP listen port                   |
| `CLICKHOUSE_LOGS_CLUSTER_HOST`     | —         | yes      | ClickHouse hostname (logs cluster) |
| `CLICKHOUSE_LOGS_CLUSTER_PORT`     | `9000`    | no       | ClickHouse native protocol port    |
| `CLICKHOUSE_LOGS_CLUSTER_USER`     | —         | yes      | ClickHouse user (prefer read-only) |
| `CLICKHOUSE_LOGS_CLUSTER_PASSWORD` | —         | no       | ClickHouse password                |
| `CLICKHOUSE_LOGS_CLUSTER_DATABASE` | —         | yes      | ClickHouse database                |
| `CH_MAX_OPEN_CONNS`                | `32`      | no       | Connection pool max open           |
| `CH_MAX_IDLE_CONNS`                | `8`       | no       | Connection pool max idle           |
| `CH_MAX_LIFETIME`                  | `1h`      | no       | Pooled connection max lifetime     |
| `CH_DIAL_TIMEOUT`                  | `5s`      | no       | TCP dial timeout                   |
| `CH_READ_TIMEOUT`                  | `30s`     | no       | Query read timeout                 |

`bin/start-go-service prom-compat` sets the ClickHouse vars to the local hogli dev stack defaults; override any of them via env to point elsewhere.

(Additional config arrives in subsequent PRs — Redis, Postgres, auth, etc.)

## Endpoints

PR 1 ships only health + self-metrics:

- `GET /_readiness` — 200 when the service can serve traffic.
- `GET /_liveness` — 200 when the process is alive.
- `GET /metrics` — Prometheus-format self-metrics.

The PromQL HTTP API arrives in PR 5; auth + tenant routing in PR 4.

## Testing

```bash
cd services/prom-compat && go test ./...
```
