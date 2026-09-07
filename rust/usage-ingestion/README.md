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

## Redis usage counters

Set `USAGE_INGESTION_REDIS_URL` to a dedicated Valkey Cluster endpoint to
enable the lossy hourly and daily counter projection. It is disabled when the
URL is empty, so Kafka and ClickHouse remain the only required dependencies.
When Valkey is unavailable, the flusher retries every
`USAGE_INGESTION_REDIS_FLUSH_INTERVAL_SECONDS` (default `15`) and drops the
unavailable interval's deltas. Counter timestamps are limited to seven days
behind and 24 hours ahead of the current time. Redis connections,
flush concurrency, and the per-scope/bucket series cap default to 16 and can
be tuned with `USAGE_INGESTION_REDIS_CONNECTIONS`,
`USAGE_INGESTION_REDIS_FLUSH_CONCURRENCY`, and
`USAGE_INGESTION_REDIS_MAX_SERIES_PER_BUCKET`.

The projection stores additive deltas, not usage record identities. Retrying
after an accepted response or correcting a durable record can therefore
increment its Valkey total again. ClickHouse remains the authoritative billing
source, so do not use this projection for exact billing decisions.

The dev stack runs the cluster on 6390 from both sides, so a host client uses
`redis://127.0.0.1:6390` and the service container uses
`redis://valkey-cluster:6390`. Start it and run its integration test with:

```sh
docker compose -f docker-compose.dev.yml up -d valkey-cluster
flox activate -- bash -c 'cd rust && cargo test -p usage-ingestion --test counters -- --ignored --nocapture'
```

The test writes 1,024 independent team scopes plus one organization scope,
checks the hour and day keys share a cluster slot, and proves cluster routing
still rejects an intentionally cross-slot transaction.

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

Every producer holds one long-lived HTTP/2 connection and never re-resolves the
service address, so a new pod would take no traffic until a producer restarts.
The server closes each connection after `USAGE_INGESTION_GRPC_MAX_CONNECTION_AGE_SECS`
(60 by default) to force that re-resolution, which is what makes a scale-up reach
the pods it adds.
The personhog services carry the same setting under the same name, at 300 seconds.
Without it, a scale-up leaves the new pods idle while the old ones throttle, and
only replacing every pod redistributes the load.
Set the variable to 0 to turn the behavior off, which is the escape hatch if the
reconnects ever cost more than the imbalance they fix.
A value between 1 and 9 is rejected at startup, because it would leave producers
reconnecting instead of sending.
This only spreads traffic if the Service is a ClusterIP; a headless Service hands
the client one address it can reconnect to.

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
timestamp. It also flushes the accepted requests to Valkey Cluster, then
checks the 27 hourly/daily hashes stay at four fields each and within a
64-byte–1-KiB per-key memory budget. Add a counter series only with an
intentional budget adjustment.
The throughput floor is deliberately loose: it exists to catch a lock or single
worker serializing the request path, not to pin a number to a laptop.

The printed percentiles are the other half of the point.
Raise the load to find where a machine stops scaling:

| Env var | Default | |
| --- | --- | --- |
| `USAGE_INGESTION_E2E_LOAD_REQUESTS` | 5000 | total requests, 10% of them retries, minimum 320 |
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

## Usage producers

Every producer of `billing_usage_records` counts after the last step that can
drop the billed thing, and before the row is written.

### Record identity and exact reads

`ReplacingMergeTree(inserted_at)` sorts by `(team_id, toDate(timestamp),
producer_id, usage_key, record_id)`. Records sharing those fields collapse to
one, with the later send winning. A producer's `record_id` must therefore be a
stable identity for one billed thing: retries and reprocessing reuse it, while
different work never does.

This protects against our duplication, not a sender's. If a customer sends the
same thing twice, we ingest and bill it twice. `usage_key` is already in the
key, so `record_id` does not repeat it; CDP prefixes its IDs only because its
three call sites share one `usage_key`.

`timestamp` is in the sort key as a date because billing reads filter time
ranges. Every producer stamps it from its own clock when it flushes, never from
a customer-controlled value. Deduplication is consequently scoped to a UTC
day, so a reprocess that crosses midnight leaves two rows.

`inserted_at` is the engine version column but is absent from the HogQL schema.
`timestamp` is monotonic per resend, so an exact, tightly-scoped read groups by
the sorting key and uses `argMax(quantity, timestamp)`. A plain `sum(quantity)`
can count unmerged duplicates and is suitable only for an approximate read.

| producer_id | usage_key | unit | record_id | deployment |
| --- | --- | --- | --- | --- |
| `ingestion` | `events`, `ai_events` | events | `{day}:{sha256 of event, distinct_id, uuid}` | ingestion consumers, ingestion API |
| `ai-ingestion` | `ai_events` | events | `{day}:{sha256 of event, distinct_id, uuid}` | AI ingestion consumer |
| `error-tracking` | `exceptions` | events | `{day}:{sha256 of event, distinct_id, uuid}` | error tracking server |
| `cdp` | `cdp_billable_invocations` | invocations | `event:{eventUuid}` / `flow:{invocationId}:{actionStepCount}:{kind}` / `webhook:{invocationId}` | CDP consumers |
| `feature-flags` | `feature_flag_requests`, `feature_flag_local_evaluation_requests` | requests | fresh UUIDv7 per flush | feature flags service |
| `ingestion` | `survey_responses` | events | `{day}:{sha256 of event, distinct_id, uuid}` | ingestion consumers, ingestion API |
| `warehouse-sources` | `warehouse_rows_synced` | rows | the ExternalDataJob ID | warehouse sources worker |
| `batch-exports` | `batch_export_rows` | rows | the BatchExportRun ID | batch exports worker |
| `replay-vision` | `replay_vision_credits` | credits | the observation ID | replay vision worker |
| `logs` | `logs_bytes`, `logs_records` | bytes, records | fresh UUIDv7 per flush | logs ingestion server |
| `apm-traces` | `apm_traces_bytes`, `apm_traces_spans` | bytes, records | fresh UUIDv7 per flush | traces ingestion server |
| `session-replay` | `session_replay_recordings`, `mobile_replay_recordings` | recordings | the session ID | session replay consumer |
| `ingestion` | `enhanced_person_events` | events | `{day}:{sha256 of event, distinct_id, uuid}` | ingestion consumers, ingestion API |

Every producer reads the following environment variables. Since every producer
is its own deployment, the same name rolls out per producer from that service's
configuration.

| Env var | Default | Meaning |
| --- | --- | --- |
| `USAGE_INGESTION_REPORT_TEAMS` | `''` | `''` reports nothing, `*` every team, `1,2` those teams. |
| `USAGE_INGESTION_ADDR` | `''` outside dev | Gateway `host:port`. Empty also reports nothing. |
| `USAGE_INGESTION_TLS` | `false` | Plaintext in-cluster. Feature flags rejects `true` because its tonic build has no TLS. |
| `USAGE_INGESTION_TIMEOUT_MS` | `5000` | Per attempt, not per batch. Feature flags retries transient failure three times. |

There is deliberately no percentage option: sampling a share of a team's
events would bill that team a fraction of its usage.

### Aggregate producers

Most records carry quantity 1 and name one billed thing, so their aggregate
lives in ClickHouse rather than in the producer. Feature flags, logs, and APM
instead send per-flush aggregates. They have no replayable item identity, so
each flush mints a fresh UUIDv7. This is retry-safe but not replay-safe: a
replayed delta is new usage. Deriving IDs from a clock could collapse two pods'
real flushes.

### Analytics ingestion

Analytics usage is counted after group processing and before event creation.
That is the last point where the event has its team, name, and Kafka message;
all drop paths are upstream. `resolveAnalyticsUsageKey` selects the product key
from the event name. The non-billable names return no key, and the list mirrors
`BILLABLE_EVENT_EXCLUDED_EVENTS` in `posthog/tasks/usage_report.py` so the
collector and nightly report agree.

Overflow is not a drop: the overflow consumer reports on its own topic and
partition, so a redirected event is counted once.

The identity is `{day}:{sha256 of event, distinct_id, uuid}` rather than a
consumer offset range because Kafka does not preserve batch boundaries on
replay. The event identity travels with the event and matches the tuple the
nightly report counts. It is hashed because customer-supplied event names and
distinct IDs could otherwise exceed the service's 512-byte identifier limit.

Counting is before Kafka produce, which is not awaited. An event that fails to
emit with `message_size_too_large` is counted but never lands in
`clickhouse_events_json`; moving the count to the acknowledgement would miss it
after the accumulator clears. Five emit retries bound this residue to the one
non-retried failure, which also raises an ingestion warning.

### AI ingestion and error tracking

AI ingestion has its own lane. Its allow step DLQs non-AI events, so every
event reaching its counter is billable as `ai_events`. It writes to both
`clickhouse_events_json` and `clickhouse_ai_events_json`; counting before that
split bills once.

Error tracking counts after Cymbal, the Rust symbolication service. Cymbal can
suppress an exception, so a suppressed exception is never billed. Token
restriction and parse failures are likewise upstream of the counter.

### CDP

`CdpUsageReporterService` owns CDP batching and its flush timer independently
of the `billable_invocation` app metric. It reports when an event triggers at
least one destination (`event:{eventUuid}`), when a non-skipped workflow action
executes (`flow:{invocationId}:{actionStepCount}:{kind}`), and when a webhook
creates a workflow trigger (`webhook:{invocationId}`). The action step count
deduplicates a retry but bills a loop revisit. `CdpBaseConsumer.stop()` flushes
the reporter, so a graceful deploy loses nothing; an ungraceful exit can lose
one interval per pod.

### Feature flags

The feature-flags billing aggregator counts requests in memory per `(team,
request_type, library, bucket)` and flushes to Redis on a tick. It emits usage
records after a chunk is credited to Redis, so a Redis retry cannot bill twice.
A bounded queue drained by one owned task sends records; shutdown closes and
awaits it within the aggregator flush timeout. A full queue drops and counts
the drop rather than growing, while Redis retains the authoritative count.

The raw `feature_flag_requests` and
`feature_flag_local_evaluation_requests` keys stay separate because the report
prices them differently. Remote-config requests bill on neither side.

### Trying it locally

The compose entry sits behind the `ingestion` profile and builds from source,
so run it from Cargo instead:

```sh
docker compose -f docker-compose.dev.yml up -d db redis7 kafka clickhouse
DEBUG=1 python manage.py migrate_clickhouse
cd rust && USAGE_INGESTION_DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog \\
  cargo run -p usage-ingestion
```

Then point a producer at it and turn on its team matcher:

```sh
USAGE_INGESTION_ADDR=localhost:7143 USAGE_INGESTION_REPORT_TEAMS='*' ./bin/start
USAGE_INGESTION_ADDR=localhost:7143 USAGE_INGESTION_REPORT_TEAMS='*' cargo run -p feature-flags
```

Records land within one flush interval:

```sql
SELECT producer_id, usage_key, sum(quantity), count()
FROM billing_usage_records GROUP BY 1, 2 ORDER BY 1, 2
```

Local development exposes `billing_usage_records` for every organization. Set
`BILLING_USAGE_RECORDS_HOGQL_ORGANIZATION_IDS` to a comma-separated list of
organization UUIDs in other deployments before enabling the real-time usage
feature flag; the table stays hidden for every other organization.

### Coverage gaps

All current collectors mirror usage into `usage-ingestion`. Existing billing
still reads the nightly usage report.

| usage_key | the report counts | the collector counts | effect |
| --- | --- | --- | --- |
| `survey_responses` | one response per `$survey_submission_id` per survey, excluding product-tour surveys | every `survey sent` event | over-bills repeat submissions and product tours |
| `warehouse_rows_synced` | nothing for a source created within seven days of the period end or during the warehouse free period | every completed billable job | over-bills a source's first week |
| `feature_flag_local_evaluation_requests` | every local evaluation request | only ones served by the Rust service | Django's endpoint writes no record |

The feature-flags gap is routing, not counting: the Rust service records both
billable request types, but Django still serves
`/api/feature_flag/local_evaluation` and increments the report counter without
writing a usage record. Session replay is also counted before later deletion,
so it can bill a recording the report subsequently drops as `is_deleted`.
