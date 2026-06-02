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

Through the dev stack:

```bash
hogli start-go-service prom-compat
```

Or directly:

```bash
cd services/prom-compat && go run .
```

## Configuration

| Env var | Default   | Required | Purpose          |
| ------- | --------- | -------- | ---------------- |
| `HOST`  | `0.0.0.0` | no       | Bind address     |
| `PORT`  | `9090`    | no       | HTTP listen port |

(Additional config arrives in subsequent PRs — ClickHouse, Redis, Postgres, auth, etc.)

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
