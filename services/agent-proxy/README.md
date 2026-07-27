# agent-proxy

Standalone Hono / Node.js service that replaces the Python ASGI agent-proxy
(`products/tasks/backend/proxy.py`). Serves the task-run live event plane:
SSE stream reads for browsers and NDJSON event ingest from sandboxes, both
backed by the same Redis streams that Django writes.

No Postgres, no Temporal client, no Celery — the service is a pure streaming
plane. Side effects (Temporal heartbeats, awaiting-input push notifications)
are delegated to a single internal Django callback endpoint.

## Routes

| Method    | Path                   | Description                                        |
| --------- | ---------------------- | -------------------------------------------------- |
| `GET`     | `/v1/runs/:run/stream` | SSE read — streams task-run events to browsers     |
| `POST`    | `/v1/runs/:run/ingest` | NDJSON ingest — accepts events from sandbox agents |
| `GET`     | `/_health`             | Liveness probe                                     |
| `GET`     | `/_readyz`             | Readiness probe (returns 503 while shutting down)  |
| `GET`     | `/health`              | Liveness probe (alias)                             |
| `GET`     | `/_metrics`            | Prometheus metrics                                 |
| `OPTIONS` | `*`                    | CORS preflight (204)                               |

Tokens are accepted via `Authorization: Bearer <token>` on both legs. There is
no `?token=` query fallback: query strings leak into upstream infrastructure
access logs, which would expose the run-scoped JWT. The browser uses
fetch-event-source (which sets headers), not native `EventSource`.

Resume is via the `Last-Event-ID` header; `?start=latest` tails from the
newest available entry.

## Environment variables

| Variable                          | Required   | Default                   | Description                                                                                                                                                                      |
| --------------------------------- | ---------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TASKS_REDIS_URL`                 | yes (prod) | `localhost:6379`          | Redis connection URL (unencrypted local Redis by default; use a TLS URL in production)                                                                                           |
| `SANDBOX_JWT_PUBLIC_KEY`          | yes        | —                         | RS256 public key PEM (`\n` literals in env vars are normalized to real newlines before use)                                                                                      |
| `AGENT_PROXY_DJANGO_CALLBACK_URL` | yes (prod) | —                         | Base URL of the Django service for side-effect callbacks (Temporal heartbeat, awaiting-input push), e.g. `http://web:8000`                                                       |
| `AGENT_PROXY_CALLBACK_SECRET`     | no         | `''`                      | Shared secret sent as `X-Agent-Proxy-Secret` on the Django callback; Django enforces it when the same value is set on both sides, so a sandbox cannot call the callback directly |
| `TASKS_AGENT_PROXY_CORS_ORIGINS`  | no         | `''`                      | Comma-separated allowed CORS origins; `*` allows all                                                                                                                             |
| `PORT`                            | no         | `8003`                    | HTTP listen port                                                                                                                                                                 |
| `HOST`                            | no         | `0.0.0.0`                 | HTTP listen address                                                                                                                                                              |
| `SHUTDOWN_GRACE_MS`               | no         | `300000`                  | Maximum drain budget on SIGTERM before force-exit (ms)                                                                                                                           |
| `SHUTDOWN_PRESTOP_DELAY_MS`       | no         | `0`                       | Sleep before closing on SIGTERM (useful for Kubernetes preStop hooks)                                                                                                            |
| `NODE_ENV`                        | no         | —                         | `production` enables strict startup checks                                                                                                                                       |
| `AGENT_PROXY_LOG_LEVEL`           | no         | `debug` dev / `info` prod | One of `debug`, `info`, `warn`, `error`. `debug` logs every connect / read / write                                                                                               |

## Running locally (end to end)

Both stream legs (browser read + sandbox ingest) route to this service when
Django has the proxy URLs set and runs with `DEBUG=True`. Local dev disables the
analytics SDK, so the URL settings are the opt-in (no feature flag needed
locally).

All config is read from the repo-root `.env`, which flox loads into every process
(`DOTENV_FILE = ".env"` in the flox manifest) — the same place Django, the
Temporal worker, and the other services read from. There is no per-service `.env`
to manage. (The dev script will also load an optional `services/agent-proxy/.env`
override if one exists, mirroring `services/mcp`, but it is not needed.) flox
caches the dotenv, so re-activate your shell or restart `hogli` after editing
`.env`.

### 1. Point Django at the proxy

In the repo-root `.env` (read by Django web and the Temporal worker):

```bash
DEBUG=1
TASKS_AGENT_PROXY_PUBLIC_URL=http://localhost:8003   # browser read leg
TASKS_AGENT_PROXY_INGEST_URL=http://localhost:8003   # sandbox ingest leg (auto-rewritten for the Docker sandbox)
```

### 2. Give this service its verify key + CORS

Same repo-root `.env`. This service is verify-only, so it needs the public half
of Django's `SANDBOX_JWT_PRIVATE_KEY`. Derive it (double-quote the value, like
the private key, so the PEM newlines survive flox's dotenv parser):

```sh
# from repo root, inside flox — prints the line to add to .env
python3 - <<'PY'
import re, pathlib
from cryptography.hazmat.primitives import serialization
priv = re.search(r'^SANDBOX_JWT_PRIVATE_KEY=(.*)$', pathlib.Path(".env").read_text(), re.M).group(1).strip().strip('"').strip("'")
key = serialization.load_pem_private_key(priv.replace("\\n", "\n").encode(), password=None)
pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
print('SANDBOX_JWT_PUBLIC_KEY="' + pub.replace(chr(10), "\\n") + '"')
PY
```

Add that line plus these to the root `.env`:

```bash
SANDBOX_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n"
TASKS_AGENT_PROXY_CORS_ORIGINS=http://localhost:8010
AGENT_PROXY_DJANGO_CALLBACK_URL=http://localhost:8000   # heartbeat + awaiting-input callbacks; omit to skip them
```

`TASKS_REDIS_URL` is optional locally — it defaults to `localhost:6379`, the
same instance Django uses (the `redis7` host maps to localhost).

### 3. Start

`hogli start` runs this service automatically when the `ai_features` intent is
enabled, listed as `agent-proxy` on :8003 (watch mode). Enable the intent with
`hogli dev:setup` if it is not already on.

```sh
hogli start                  # Redis, Django (:8000), frontend (:8010), Temporal worker, agent-proxy (:8003)
```

To run only this service standalone (for example when `ai_features` is off):

```sh
hogli start:agent-proxy      # this service on :8003 (watch mode); or: pnpm --filter @posthog/agent-proxy dev
```

The proxy must be running before you start a task run. With the URL settings
above there is no automatic failover: if the proxy is down the client fails to
connect, it does not fall back to Django.

### 4. Verify both legs

Create a run at `http://localhost:8010/project/1/tasks`, then:

- Read leg: in browser DevTools > Network the `/v1/runs/:run/stream` EventStream request
  host is `localhost:8003` (not `:8000`). The `/stream_token/` response carries
  `stream_base_url: http://localhost:8003`.
- Write leg: the proxy console logs ingest activity as the sandbox POSTs, and
  events render live in the task UI.
- Health: `curl localhost:8003/_health` and `curl localhost:8003/_metrics`.

### Rolling back to Django

Unset `TASKS_AGENT_PROXY_PUBLIC_URL` and `TASKS_AGENT_PROXY_INGEST_URL` in the
root `.env` and restart. No data migration is needed: the Redis stream format is
identical, so the Django in-process path picks up seamlessly.

## Building

```sh
# From repo root
docker build -f services/agent-proxy/Dockerfile -t posthog-agent-proxy .

# Or build the JS bundle only (no Docker)
pnpm --filter @posthog/agent-proxy build
# Output: services/agent-proxy/dist/agent-proxy-server.mjs
```

## Testing

```sh
pnpm --filter @posthog/agent-proxy test
```

## Type checking

```sh
pnpm --filter @posthog/agent-proxy typecheck
```

## Cutover note

Browsers discover the proxy URL from the `stream_base_url` field returned by
the Django `stream_token` endpoint. When `TASKS_AGENT_PROXY_PUBLIC_URL` is set
on Django (read leg) it points to this service; the write leg routes here when
`TASKS_AGENT_PROXY_INGEST_URL` is set. When unset, browsers and sandboxes use
the Django in-process path instead — no client code changes are needed for the
cutover.

The Redis stream key format (`task-run-stream:{run_id}`) and all companion
keys are byte-identical between this Node service and the Python implementation.
During the cutover window both services read and write the same streams safely.

To roll back: unset `TASKS_AGENT_PROXY_PUBLIC_URL` and `TASKS_AGENT_PROXY_INGEST_URL`
on Django. No data migration is needed because the stream format is identical.

S3 hydration on resume gap is explicitly out of scope for this version — when a
client's `Last-Event-ID` has been trimmed from Redis, the service emits a metric
and continues reading from the oldest available entry, matching the current
Python behavior exactly.
