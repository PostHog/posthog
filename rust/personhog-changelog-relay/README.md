# personhog-changelog-relay

Relays the personhog changelog to the ClickHouse person topic. It consumes `personhog.types.v1.Person` records from the changelog on MSK and produces each as the JSON row Node's `generateKafkaPersonUpdateMessage` writes, unkeyed and without headers, to `OUTPUT_TOPIC` (`clickhouse_person`) on the output cluster.

## Following the changelog

`config/changelog` must list the relay's group in `retire_groups`, added from the control plane's changelog panel, or the relay refuses to start. Retire then waits for this group as well as the writer's to read a generation to the end, so a lagging relay never loses an old topic's tail: the relay writes a drain report once it proves its group has, and the coordinator retires on the reports of every named group.

The subscription follows `config/changelog` through the same follower as the writer: the oldest draining generation its group has not read to the end, then the live topic. Every topic starts from its first record when the group has no commit on it, so a migration's new topic is read from the flip.

## Delivery

A batch is up to `BATCH_SIZE` records or what arrives within `BATCH_TIMEOUT_MS`. Every record in it is produced and acked before the group commits past it, so delivery is at least once; ClickHouse keeps the highest version of each person, so a repeated row changes nothing. A failed produce retries until the broker acks and never advances the offset.

A record that can never become a row goes to `DLQ_TOPIC` with its original bytes and the `source_topic`, `source_partition`, `source_offset`, `reason` and `error` headers: no payload, not a `Person` proto, a uuid that does not parse, properties that are not UTF-8, or a timestamp out of range. A row the output rejects as too large goes there too, as its changelog record. That copy fits because the output producer's `KAFKA_PRODUCER_MESSAGE_MAX_BYTES` defaults to 64 MB, well above the changelog topic's limit; keep any override above it as well.

## Configuration

| Variable | Default | |
| --- | --- | --- |
| `KAFKA_HOSTS`, `KAFKA_TLS` | | The changelog's cluster; the `KAFKA_PRODUCER_*` settings tune the output producer |
| `KAFKA_CONSUMER_GROUP` | `personhog-changelog-relay` | |
| `OUTPUT_KAFKA_HOSTS`, `OUTPUT_KAFKA_TLS` | | The output cluster |
| `OUTPUT_TOPIC` | `clickhouse_person` | |
| `DLQ_TOPIC` | `personhog_changelog_relay_dlq` | On the output cluster |
| `BATCH_SIZE`, `BATCH_TIMEOUT_MS` | `1000`, `500` | |
| `ETCD_ENDPOINTS`, `ETCD_PREFIX` | `http://localhost:2379`, `/personhog/` | |
| `METRICS_PORT` | `9106` | |

## Metrics

- `personhog_changelog_relay_records_total{outcome="relayed"|"dlq", reason}`
- `personhog_changelog_relay_produce_retries_total{topic}`
- `personhog_changelog_relay_lag_seconds`: the age of the oldest record in the last batch, or 0 when caught up. It climbs while a delivery retries, and after a failed read it shows the age of the last record relayed. Alert on it together with the rate of `personhog_changelog_relay_produce_retries_total`; the relay keeps reporting healthy during an outage, since a restart would not fix one
- `personhog_changelog_relay_batch_duration_ms`, `personhog_changelog_relay_batch_records`
- `personhog_changelog_relay_draining`: 1 while the subscription reads a sealed generation
- `personhog_changelog_relay_commit_errors_total`, `personhog_changelog_relay_consumer_errors_total`
- `personhog_changelog_relay_resubscriptions_total`
