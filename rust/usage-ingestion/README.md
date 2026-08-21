# Usage ingestion service

`usage-ingestion` is the internal gRPC gateway for durable usage records. It
validates records, resolves an omitted organization ID from core PostgreSQL,
caches successful lookups in memory for five minutes, and publishes
JSONEachRow messages to `clickhouse_billing_usage_records`.

The service is the shared gateway for every usage stream; `IngestBillingUsage`
is the tenant-billing stream, which is exact, idempotent, and retained
indefinitely. Cost and resource metering gets its own RPC, topic, and table
rather than sharing these — see `.context/usage-ingestion-implementation-plan.md`.

The RPC acknowledges only after Kafka confirms every record. Producers must call
it asynchronously, outside request-critical paths, and retry an unavailable response
with the same record identity and event timestamp.
The service validates the complete batch before producing, so validation failure accepts
no records. Kafka may have delivered part of a batch before an unavailable response, but
retrying the complete batch is safe because records are idempotent.

Run it in the local Docker stack with:

```sh
docker compose -f docker-compose.dev.yml up usage-ingestion
```

The gRPC endpoint listens on port 7143 and metrics/readiness on port 7144.
PostgreSQL is the source of truth. The service retains successful team-to-
organization lookups in its process-local cache for five minutes.

When `DEBUG` is set, the service writes readable, colorized logs for local
development. It uses structured JSON logs otherwise.

## Where it runs

| Resource | Placement |
| --- | --- |
| Kafka cluster | `warpstream-shared` |
| Topic | `clickhouse_billing_usage_records`, 8 partitions, 7-day retention |
| ClickHouse Kafka table and MV | `NodeRole.INGESTION_SMALL` |
| ClickHouse storage and read tables | `NodeRole.DATA` |
| Reachability | in-cluster only; no external proxy and no request authentication |
| Owning team | `team-ingestion` |

`warpstream-shared` carries the low-volume topics that do not justify a cluster
of their own, which is what usage records are.
The alternative was `warpstream-ingestion`, where `usage_report_events_preagg`
lives, but that cluster carries the event hot path.
Usage records come from a standalone gateway rather than the event pipeline, so
putting them there would couple billing data to the noisiest cluster for no gain.
The producer and the ClickHouse Kafka engine table must name the same cluster:
the table takes it from `CLICKHOUSE_KAFKA_WARPSTREAM_SHARED_NAMED_COLLECTION`,
and the service takes its topic from `USAGE_INGESTION_TOPIC`.

The endpoint relies on an in-cluster network boundary while it is being validated.
Before it is exposed beyond trusted callers, it must authenticate the calling service.

Partition count can be raised later without risk, which is not true of an
ordered stream.
ClickHouse deduplicates by record identity and picks a winner by
`event_timestamp`, so a key that moves to a different partition after a
repartition cannot change the result.

## End-to-end tests

Both tests run the service in-process and need the local dev stack for Kafka and
ClickHouse (with migration `0303_billing_usage_records` applied), so both are
`#[ignore]`d by default.
`ci-rust.yml` runs them with `--run-ignored only` against the Django test
schema, so they gate PRs that touch this crate.

| Env var | Default |
| --- | --- |
| `USAGE_INGESTION_E2E_KAFKA_HOSTS` | `localhost:9092` |
| `USAGE_INGESTION_E2E_CLICKHOUSE_URL` | `http://localhost:8123` |
| `USAGE_INGESTION_E2E_CLICKHOUSE_DATABASE` | `posthog` (CI: `posthog_test`) |
| `USAGE_INGESTION_E2E_TOPIC` | `clickhouse_billing_usage_records` (CI: `clickhouse_billing_usage_records_test`) |

A Django test environment suffixes both the ClickHouse database and the Kafka
topic, which is why the last two exist.
The service reads the same topic from `USAGE_INGESTION_TOPIC`.

```sh
flox activate -- bash -c 'cd rust && cargo test -p usage-ingestion -- --ignored --nocapture'
```

`tests/e2e.rs` checks that a retry with the original event timestamp collapses
to one canonical row. A correction must use a new version, and any correction
that moves event time becomes a distinct billable row.

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
producer's 20ms linger until concurrency passes 512, measured at 20000 requests:

| Concurrency | Throughput | p50 | p99 |
| --- | --- | --- | --- |
| 32 | 1.4k req/s | 23ms | 30ms |
| 256 | 9.6k req/s | 26ms | 40ms |
| 512 | 18.8k req/s | 26ms | 45ms |
| 1024 | 22.7k req/s | 43ms | 71ms |

A large run leaves its rows in `posthog.sharded_billing_usage_records`; every query
filters on a per-run record ID prefix, so runs never interfere, but
`TRUNCATE TABLE posthog.sharded_billing_usage_records` clears a dev instance.
