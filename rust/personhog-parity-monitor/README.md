# personhog-parity-monitor

A read-only service that follows the two person CDC feeds and reports, as Prometheus metrics, whether they end in the same state.
The Node Postgres path produces `clickhouse_person_distinct_id` rows and `person_merge_events`; `personhog-publisher` produces the same two topics from the identity service's outbox.
When a lane runs in `shadow` store mode both feeds describe the same events, so every distinct id and every merge should settle identically on both.
With `NODE_PERSON_TOPIC` and `PERSONHOG_PERSON_TOPIC` set, it also compares `clickhouse_person` rows: Node's against those `personhog-changelog-relay` writes from the leaders' changelog.

The rules are `personhog_common::cdc_parity`, the ones the Kafka parity e2e (`nodejs/tests/service-e2e/personhog-kafka-parity.serial.test.ts`) and the test harness gate apply: end state, not messages.
Per distinct id only the highest-version row counts, and of it only the person uuid and the deleted flag.
Per merged person only the survivor at the end of its merge chain counts.

## How it settles

- Every partition of the four topics is assigned at the end of the log. There is no consumer group and nothing is committed: a group would split the partitions between replicas and break the cross-feed join, and the output is a rate over a window, so a restart has nothing to resume. Run one replica.
- Each distinct id topic tracks the newest message timestamp per partition. A feed's watermark is the slowest of its partitions that delivered within `PARITY_IDLE_PARTITION_SECONDS`. When both feeds are quiet the watermarks advance by the wall clock; when one feed is quiet next to a live one it has stalled, so its watermark holds, its `watermark_age_seconds` grows and nothing settles against its absence. The merge topics do not count: they are sparse and would hold the watermark an idle window behind. The global watermark is the slower feed's.
- An entry settles once its newest row is older than the global watermark minus `PARITY_GRACE_SECONDS`. The grace has to exceed the publisher's drain lag, or pairs settle one-sided before the personhog copy arrives.
- Entries older than the first watermark plus `PARITY_WARMUP_SECONDS` (the grace by default) are dropped unjudged and counted as `warmup_evictions_total`: the readers start at the end of the log at different moments, so a row's counterpart may have been produced before its reader started. A fixture whose readers start before any traffic sets it to `0`.
- Merges settle first and mappings `PARITY_MAPPING_LAG_MS` later, so a settling merge still sees the rows that named its persons and can tell a stub from a missing merge event.
- A merge agrees when both feeds name the same direct target; what became of that target is the target's own verdict. Different direct targets are followed to their survivors, because one feed may reach the same person through a stub the other never made.
- Settled entries are evicted from both feeds. `PARITY_MAX_ENTRIES` bounds the rows, merges and persons retained across both feeds, history included, so a key that keeps receiving versions cannot grow past it behind one entry. Above the cap the oldest entries are evicted down to nine tenths of it without a verdict and counted as overflow. A row or merge costs about half a kilobyte.
- Persons settle against the two person topics' own watermarks, so a lagging relay holds back only person verdicts and shows in `person_watermark_age_seconds`. Each feed keeps its newest row per person. The version only picks that row: it counts writes, which the two backends batch differently. Two deleted persons agree whatever else their death rows carry. Otherwise the properties, `is_identified` and `created_at` must match; properties compare by value, ignoring key order and reading numbers as JavaScript does (`1` equals `1.0`, integers past 2^53 round), without the keys in `PARITY_PERSON_IGNORED_PROPERTIES`. Each side holds a hash per top level property key, so a sample names the keys that differ but never their values. `last_seen_at` is not compared.
- Distinct id rows carry null keys on both sides, so their partitions are random and only the partition counts are compared. Merge events are keyed `"{team_id}:{old_person_uuid}"`; each one is checked against `murmur2(key) % partitions` of its own topic, and a merge present on both feeds is checked for landing on the same partition number while both merge topics have the same count.

## Metrics

All names start with `personhog_parity_`. Labels carry outcomes only, never a team or an id; `/debug/mismatches` holds the last `PARITY_SAMPLE_RING_SIZE` disagreements with both sides' rows and `last_update_ms`, the newest message timestamp behind each verdict.

| Metric | Labels | Meaning |
| --- | --- | --- |
| `settled_mappings_total` | `outcome`: `agree`, `person_mismatch`, `deleted_mismatch`, `node_only`, `personhog_only` | One per settled distinct id |
| `settled_merges_total` | `outcome`: `agree`, `survivor_mismatch`, `node_only`, `personhog_only`, `node_stub`, `personhog_stub`, `loop` | One per settled merged person. `*_stub`: the merging feed created the person inside the window and the other feed never named it, its own path to the result. `*_only`: the other feed named the person, or the person predates the window, and no merge for it arrived |
| `settled_persons_total` | `outcome`: `agree`, `deleted_mismatch`, `properties_mismatch`, `identified_mismatch`, `created_at_mismatch`, `node_only`, `personhog_only` | One per settled person, when the person topics are set |
| `merge_partition_total` | `outcome`: `same`, `different` | Merges present on both feeds, by partition number; only counted while both merge topics have the same partition count |
| `merge_placement_total` | `feed`, `outcome`: `expected`, `unexpected` | Arrival partition against the key's murmur2 partition |
| `version_ties_total`, `merge_conflicts_total` | `feed` | A feed contradicting itself |
| `messages_total`, `decode_failures_total`, `read_errors_total`, `metadata_errors_total`, `filtered_total`, `sampled_out_total` | `feed`, `topic` | Reader counters |
| `topic_partitions` | `feed`, `topic` | Partition counts from metadata, re-read every `PARITY_METADATA_POLL_SECONDS` |
| `topic_pair_partitions_equal` | `topic` | Whether the two feeds' topics of that kind have the same count |
| `pending_entries` | `kind` | Entries waiting to settle |
| `watermark_age_seconds` | `feed` | Wall clock minus the feed's watermark; a stalled feed shows here |
| `person_watermark_age_seconds` | `feed` | The same for the person topics, which persons settle against |
| `overflow_evictions_total` | | Entries dropped by the cap, so the outcome counters are degraded while this moves |
| `warmup_evictions_total` | | Entries dropped during the first grace after start |

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `NODE_KAFKA_HOSTS`, `NODE_KAFKA_TLS` | `localhost:9092`, `false` | The Node feed's cluster |
| `NODE_DISTINCT_ID_TOPIC`, `NODE_MERGE_EVENTS_TOPIC` | `clickhouse_person_distinct_id`, `person_merge_events` | The Node feed's topics |
| `PERSONHOG_KAFKA_HOSTS`, `PERSONHOG_KAFKA_TLS` | `localhost:9092`, `false` | The personhog feed's cluster |
| `PERSONHOG_DISTINCT_ID_TOPIC`, `PERSONHOG_MERGE_EVENTS_TOPIC` | required | The publisher's topics |
| `NODE_PERSON_TOPIC`, `PERSONHOG_PERSON_TOPIC` | unset | Node's and the relay's `clickhouse_person` topics; persons are compared only when both are set |
| `PARITY_PERSON_IGNORED_PROPERTIES` | `$creator_event_uuid` | Comma separated top level property keys the person comparison leaves out; their values depend on the order each backend applied a merge's writes in |
| `PARITY_PERSON_SAMPLE_PERCENT` | `100` | The share of persons compared, 1 to 100. Both feeds keep the persons whose key hashes into the sample, so every kept person gets a full verdict; a row outside it is read no further than its key and still moves the watermark. Distinct ids and merges are never sampled: a merge's verdict follows other merges and the rows naming its persons |
| `PARITY_GRACE_SECONDS` | `60` | How long an entry waits for the other feed |
| `PARITY_IDLE_PARTITION_SECONDS` | `30` | When a quiet partition stops holding the watermark |
| `PARITY_MAPPING_LAG_MS` | `2000` | How much longer than merges the mappings wait |
| `PARITY_WARMUP_SECONDS` | the grace | How long after the first watermark entries are dropped unjudged; `0` for a fixture whose readers start before any traffic |
| `PARITY_MAX_ENTRIES` | `1000000` | The cap on retained rows, merges and persons across both feeds, about half a gigabyte; a person with many properties holds a hash per key |
| `PARITY_TEAMS` | empty, every team | Comma separated team ids; set it to the merge events allowlist when that is a subset |
| `PARITY_SAMPLE_RING_SIZE` | `500` | Disagreements kept for `/debug/mismatches` |
| `PARITY_SWEEP_INTERVAL_MS` | `1000` | How often entries are settled |
| `PARITY_METADATA_POLL_SECONDS` | `30` | How often each topic's partition list is re-read; partitions a repartition added are assigned from their beginning, and the placement check uses the new count |
| `DEBUG_API_SECRET` | unset, endpoint off | Required in the `x-debug-api-secret` header to read `/debug/mismatches`, which carries distinct ids |
| `BIND_HOST`, `BIND_PORT` | `0.0.0.0`, `3301` | `/metrics`, `/_readiness`, `/_liveness`, `/debug/mismatches` |

## Running it locally

The harness `stack --publish` brings up identity and the publishers with per-run topics, and a Node ingestion API worker in `PERSONS_STORE_MODE=shadow` fed by the Rust ingestion consumer writes the Node side; the Kafka parity e2e shows the worker's environment.

```bash
target/debug/personhog-test-harness stack --publish --ready-file /tmp/personhog-stack.json

NODE_DISTINCT_ID_TOPIC=<the worker's INGESTION_OUTPUT_PERSON_DISTINCT_IDS_TOPIC> \
NODE_MERGE_EVENTS_TOPIC=<the worker's INGESTION_OUTPUT_PERSON_MERGE_EVENTS_TOPIC> \
PERSONHOG_DISTINCT_ID_TOPIC=$(jq -r .distinct_ids_topic /tmp/personhog-stack.json) \
PERSONHOG_MERGE_EVENTS_TOPIC=$(jq -r .merge_events_topic /tmp/personhog-stack.json) \
PARITY_GRACE_SECONDS=10 DEBUG_API_SECRET=local \
target/debug/personhog-parity-monitor

curl -s localhost:3301/metrics | grep personhog_parity_settled
curl -s -H 'x-debug-api-secret: local' localhost:3301/debug/mismatches
```
