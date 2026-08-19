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

## End-to-end test

`tests/e2e.rs` runs the service in-process and checks that a retried record
collapses to one canonical row in ClickHouse. It needs the local dev stack for
Kafka and ClickHouse (with migration `0301_usage_records` applied), so it is
`#[ignore]`d by default:

```sh
flox activate -- bash -c 'cd rust && cargo test -p usage-ingestion --test e2e -- --ignored'
```

Override the endpoints with `USAGE_INGESTION_E2E_KAFKA_HOSTS` (default
`localhost:9092`) and `USAGE_INGESTION_E2E_CLICKHOUSE_URL` (default
`http://localhost:8123`).

The test also pins a semantic gap: `ReplacingMergeTree(event_timestamp)` keeps
the whole winning row, so a later event timestamp replaces the first
`inserted_at` rather than preserving it. Anything that needs first-seen time has
to derive it at read time.
