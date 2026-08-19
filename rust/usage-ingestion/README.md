# Usage ingestion service

`usage-ingestion` is the internal gRPC gateway for durable usage records. It
validates records, resolves an omitted organization ID from the dedicated
team-to-organization HyperCache (with PostgreSQL fallback), and publishes
JSONEachRow messages to `clickhouse_usage_records`.

Run it in the local Docker stack with:

```sh
docker compose -f docker-compose.dev.yml up usage-ingestion
```

The gRPC endpoint listens on port 7143 and metrics/readiness on port 7144.
The Django publisher must have warmed the `usage_ingestion/organization_id.json`
HyperCache before relying on cache hits; PostgreSQL remains the source of truth
for cold or stale mappings.
