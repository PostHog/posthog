# pgapi — API + MCP server over the pgcollector stats database

Read-only REST API and MCP (streamable HTTP) server for the Postgres telemetry
collected by `rust/pgcollector`. One binary, one port: `/api/v1/*`, `/mcp`,
`/healthz`, `/readyz`, `/metrics`.

## Run locally

```sh
PGAPI_DEV_MODE=1 PGAPI_DEV_USER=you@posthog.com \
  cargo run -p pgapi -- --database-url postgres://.../pgcollector
curl localhost:3400/api/v1/servers
curl "localhost:3400/api/v1/servers/<id>/queries?since=1h&order=total_exec_time"
```

MCP client config (Claude Code / Desktop): `{"type": "http", "url": "http://localhost:3400/mcp"}`.
17 tools: `list_servers`, `server_overview`, `top_queries`, `query_detail`,
`wait_events`, `current_activity`, `table_stats`, `index_stats`,
`vacuum_status`, `events`, `settings`, `schema`, `log_errors`, `system_stats`,
`collector_health`, `describe_stats_schema`, `query_stats_db` (guarded raw SQL).

## Authentication

No OAuth flow in the app. Identity is established at the edge and read from
headers, in priority order (`src/auth.rs`):

1. `Tailscale-User-Login` — Tailscale ingress with `whois: true`; trusted only
   with `PGAPI_TRUST_TAILSCALE=1` **and** on a tailnet `Host`
   (`PGAPI_TAILSCALE_HOSTS`, default any `*.ts.net`), so the header is ignored
   when a request arrives through another ingress. Must be paired with a
   NetworkPolicy admitting only `tailscale.com/managed=true` proxy pods (see
   `values.example.yaml`). This is the path for MCP / CLI callers.
2. `x-amzn-oidc-data` — ALB + Cognito (`ingress.internal: true`); verified
   ES256 against `https://public-keys.auth.elb.<region>.amazonaws.com/<kid>`,
   issuer must be a Cognito pool in `PGAPI_ALB_REGION`, the token must be for
   `PGAPI_ALB_CLIENT_ID` and signed by `PGAPI_ALB_ARN` (the JOSE `signer`;
   all three required together), `email_verified` must be true.
   Browser path.
3. `X-Auth-Request-Email` — the in-cluster auth gateway, if/when adopted
   (`PGAPI_TRUST_GATEWAY=1`).
4. `PGAPI_DEV_USER` in dev mode.

Authorisation: `PGAPI_ALLOWED_DOMAINS` (default `posthog.com`) and/or
`PGAPI_ALLOWED_EMAILS`. Everything is read-only; the DB session is forced
`default_transaction_read_only`, and the raw-SQL tool runs each statement in a
read-only transaction with a 15 s timeout followed by `DISCARD ALL`, so
advisory locks or session settings cannot outlive a request, streams rows
under an 8 MiB response budget, and refuses calls
to known side-effecting functions (`pg_sleep`, advisory locks, `set_config`,
backend signalling, stats resets, file/backup functions, `dblink`). Every request is
logged with the caller's email and identity source.

This mirrors hosthog-api's dual-host pattern: humans use the Cognito-gated
`*.posthog.dev` host, agents use the tailnet host — Cognito can't
authenticate headless clients.

## Deploying

The charts app is `apps/pgapi` in PostHog/charts, onboarded through platformctl
(`service.yaml` per app; platformctl generates the Argo CD Application and the
Kargo resources). [`values.example.yaml`](values.example.yaml) shows the values:
`tailscaleIngress` with `whois`, the NetworkPolicy that makes the identity header
trustworthy, and a read-only `psql` entry for the stats database.

Outside the chart:

* `tag:pgapi` in `posthog-cloud-infra/tailnet-policy.hujson`, owned by
  `tag:k8s-operator`, with `group:engineering@posthog.com -> tag:pgapi:443`.
  That grant is the login for the tailnet host.
* The `pgapi` readonly user on the stats database, from
  `terraform/modules/pgcollector`.
* For the Cognito/ALB path, once enabled: egress to the ALB public-key endpoint
  for token verification.

## Layout

```text
src/auth.rs      identity middleware
src/queries.rs   every question the API can answer, as SQL → JSON (shared by REST + MCP)
src/api.rs       REST routes
src/mcp.rs       MCP tools
src/db.rs        read-only pool, row → JSON
```
