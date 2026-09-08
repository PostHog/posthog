# HogQL language service prototype

This prototype keeps multiple immutable, permission-filtered catalogs in memory and provides local SQL completion.
It uses `github.com/orian/clickhouse-sql-parser` to recover table and alias context from the query. Django remains the
authority for deciding which schema and properties belong in each catalog.

For local development, start the service on its loopback listener:

```bash
.codex/with-flox go -C services/hogql-language-service run ./cmd/server
```

Publish a permission-filtered catalog through the multitenant endpoint below before making language requests. The Go
service does not hold a personal API key or fetch schema from PostHog directly.

```bash
curl -sS http://localhost:8091/health
curl -sS -X POST http://localhost:8091/teams/2/users/1/autocomplete \
  -H 'Content-Type: application/json' \
  -d '{"query":"SELECT o. FROM orders AS o","position":9}'
```

Validate syntax and catalog-backed table and field references:

```bash
curl -sS -X POST http://localhost:8091/teams/2/users/1/validate \
  -H 'Content-Type: application/json' \
  -d '{"query":"SELECT amuont FROM warehouse_0420"}'
```

Diagnostics contain byte offsets and up to five visible typo suggestions ranked by case-insensitive Levenshtein
distance. Dynamic properties use the same cached namespaces as autocomplete.

```bash
curl -sS -X POST http://localhost:8091/teams/2/users/1/autocomplete \
  -H 'Content-Type: application/json' \
  -d '{"query":"SELECT events.properties.$geo"}'

curl -sS -X POST http://localhost:8091/teams/2/users/1/validate \
  -H 'Content-Type: application/json' \
  -d '{"query":"SELECT events.properties.$geo_cty FROM events"}'
```

`position` is an optional UTF-8 byte offset and defaults to the end of the query. `durationMicros` covers only the
in-memory completion path; network and JSON decoding are intentionally excluded. Responses contain at most 25
suggestions, the total match count, and an opaque `nextCursor` when another page exists. Send the same query and
position with `"cursor":"<nextCursor>"` to retrieve it. The HTTP `Content-Length` is the encoded response size.

The parser currently accepts ClickHouse's `database.table` identifiers but not HogQL's three-part synced-table names.
Completion retains the parser error for diagnostics and uses a catalog-aware table-reference fallback for those names.
Validation normalizes those table references before parsing while preserving byte offsets.

## Multitenant catalogs

Django can publish a complete catalog for one team and user without restarting the service:

```bash
curl -sS -X PUT http://localhost:8091/teams/2/users/17/catalog \
  -H 'Content-Type: application/json' \
  -d '{
    "revision": "schema-42:permissions-9",
    "catalog": {
      "tables": {
        "events": {"name": "events", "type": "posthog", "fields": {}}
      },
      "properties": {"event": [{"name": "$geo_city", "property_type": "String"}]}
    }
  }'
```

Every protected route requires positive `teamId` and `userId` path parameters. The response includes
`catalogRevision`, allowing Django and the editor to detect a stale response. An unknown, expired, or evicted pair
returns `404`; the service never falls back to another team or user.

`DELETE /teams/{teamId}/users/{userId}/catalog` removes that entry.

Catalogs expire `CATALOG_TTL` (default `30m`) after publication so active projects periodically refresh their schema.
When `MAX_CATALOGS` (default `1024`) is reached, the least recently used catalog is evicted. Publishing a new revision
replaces the old immutable catalog atomically.

Loopback listeners allow unauthenticated requests for local development. A non-loopback listener refuses to start
unless `HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS` contains one or more comma-separated HMAC keys. Django must send a
short-lived HS256 JWT as `Authorization: Bearer …` with these claims:

```json
{
  "aud": "hogql-language-service",
  "team_id": 2,
  "user_id": 17,
  "operations": ["publish", "complete", "validate", "delete"],
  "nbf": 1788750000,
  "exp": 1788750060
}
```

Tokens are valid only for the exact team, user, and operation. List the current signing key first and old keys
afterward during rotation. Do not expose the service directly to browsers; Django should mint tokens and proxy
requests after resolving the user's membership and permissions for that team.

## Django integration

Django proxies eligible `HogQLAutocomplete` and `HogQLMetadata` query nodes to the service. Debug builds enable the
proxy by default. Production requires the `hogql-language-service` feature flag and both settings below:

- `HOGQL_LANGUAGE_SERVICE_URL` points to the service's internal URL.
- `HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS` lists the current signing key first, followed by keys being rotated out.

On a catalog miss, Django builds the schema visible to that exact team and user, adds their visible event, person,
session, and group properties, publishes it, and retries once. Unsupported query options and service failures use
the existing in-process implementation. Prometheus records Django-to-service latency and response size by operation.

## Rate limiting

Protected requests pass through two bounded in-memory token buckets before the handler reads JSON:

1. The pre-authentication bucket keys requests by the direct peer IP address.
2. The principal bucket keys authenticated requests by `teamId:userId`.

The JWT must match the path before a request consumes principal capacity. The service does not trust forwarded-IP
headers. Deployments should configure the pre-authentication allowance for the expected number of Django callers.

| Setting                                  | Default |
| ---------------------------------------- | ------- |
| `PRE_AUTH_RATE_LIMIT_CAPACITY`           | `300`   |
| `PRE_AUTH_RATE_LIMIT_REFILL_PER_SECOND`  | `100`   |
| `PRINCIPAL_RATE_LIMIT_CAPACITY`          | `120`   |
| `PRINCIPAL_RATE_LIMIT_REFILL_PER_SECOND` | `60`    |
| `RATE_LIMIT_MAX_KEYS`                    | `10000` |
| `RATE_LIMIT_IDLE_TTL`                    | `10m`   |

Limited requests return `429` and a `Retry-After` header. The entry bound prevents attacker-controlled path values
from growing limiter memory without limit.

## Container image

Build the image from the service directory:

```bash
docker build \
  --build-arg COMMIT_HASH="$(git rev-parse HEAD)" \
  --tag hogql-language-service:local \
  services/hogql-language-service
```

The image runs as a non-root user and listens on port `8091`. Because the container binds to all interfaces, it
requires `HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS`:

```bash
docker run --rm \
  --publish 127.0.0.1:8091:8091 \
  --env HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS=local-development-key \
  hogql-language-service:local
```

The production binary is compiled with Go 1.27.1 and `go build -trimpath`. The runtime image contains only the static
service binary, the commit identifier, and CA certificates. BuildKit's `TARGETOS` and `TARGETARCH` arguments allow
native `linux/amd64` and `linux/arm64` builds.
