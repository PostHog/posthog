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

## End-to-end tests

Both tests run the service in-process and need the local dev stack for Kafka and
ClickHouse (with migration `0302_usage_records` applied), so both are
`#[ignore]`d by default.
`ci-rust.yml` runs them with `--run-ignored only` against the Django test
schema, so they gate PRs that touch this crate.

| Env var | Default |
| --- | --- |
| `USAGE_INGESTION_E2E_KAFKA_HOSTS` | `localhost:9092` |
| `USAGE_INGESTION_E2E_CLICKHOUSE_URL` | `http://localhost:8123` |
| `USAGE_INGESTION_E2E_CLICKHOUSE_DATABASE` | `posthog` (CI: `posthog_test`) |
| `USAGE_INGESTION_E2E_TOPIC` | `clickhouse_usage_records` (CI: `clickhouse_usage_records_test`) |

A Django test environment suffixes both the ClickHouse database and the Kafka
topic, which is why the last two exist.
The service reads the same topic from `USAGE_INGESTION_TOPIC`.

```sh
flox activate -- bash -c 'cd rust && cargo test -p usage-ingestion -- --ignored --nocapture'
```

`tests/e2e.rs` checks that a retried record collapses to one canonical row.
It also pins a semantic gap: `ReplacingMergeTree(event_timestamp)` keeps the
whole winning row, so a later event timestamp replaces the first `inserted_at`
rather than preserving it.
Anything that needs first-seen time has to derive it at read time.

### Load test

`tests/load.rs` fires thousands of concurrent single-record requests across
varied teams, organizations, usage keys and modes, a tenth of them retries of an
earlier record shuffled so they can arrive before the original.

```sh
flox activate -- bash -c 'cd rust && cargo test -p usage-ingestion --test load -- --ignored --nocapture'
```

It asserts that every request succeeds, that concurrent throughput is at least
5x the sequential baseline measured on the same machine, and that ClickHouse
ends with exactly one row per record with every retry winning on event
timestamp.
The throughput floor is deliberately loose: it exists to catch a lock or single
worker serializing the request path, not to pin a number to a laptop.

The printed percentiles are the other half of the point.
Raise the load to find where a machine stops scaling:

| Env var | Default | |
| --- | --- | --- |
| `USAGE_INGESTION_E2E_LOAD_REQUESTS` | 5000 | total requests, 10% of them retries |
| `USAGE_INGESTION_E2E_LOAD_CONCURRENCY` | 128 | requests in flight |
| `USAGE_INGESTION_E2E_LOAD_CHANNELS` | 8 | gRPC connections the load spreads over |

On an M-series laptop against the dev stack, p50 stays pinned to the Kafka
producer's 20ms linger until concurrency passes ~512, where it starts climbing:

| Concurrency | Throughput | p50 | p99 |
| --- | --- | --- | --- |
| 32 | 1.4k req/s | 23ms | 30ms |
| 128 | 5.0k req/s | 25ms | 37ms |
| 512 | 18.8k req/s | 26ms | 45ms |
| 1024 | 22.7k req/s | 43ms | 71ms |

A large run leaves its rows in `posthog.sharded_usage_records`; every query
filters on a per-run record ID prefix, so runs never interfere, but
`TRUNCATE TABLE posthog.sharded_usage_records` clears a dev instance.
