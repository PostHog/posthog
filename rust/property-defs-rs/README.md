# Event and property definitions generator (propdefs for short)

This consumes events from Kafka, introspects on their names and properties, and writes definition metadata to postgres for the read-side filters in the product.
It filters DB updates to avoid duplicate writes, because writes are idempotent but writing every property definition on every event would be far too much DB load.

Three tables are written: `posthog_eventdefinition`, `posthog_propertydefinition`, and `posthog_eventproperty`.

Hoglets should check out [the runbook](https://runbooks.posthog.com/services/ingestion/concepts/property-defs-rs) for a detailed breakdown of how it's tuned for our current scale, and what metrics to look at and levers to pull if responding to an incident.

## Topic

Production consumes `team_event_partitioned_events_json`, set via `KAFKA_CONSUMER_TOPIC`.
That topic is produced by a WarpStream Bento pipeline that repartitions `clickhouse_events_json` by team, under the separate `property-defs-rs-ws` consumer group.
The in-code default is `clickhouse_events_json`, which is what a local run gets.

## Dependencies worth knowing about

- **personhog** resolves group names to group type indexes over gRPC. With `PERSONHOG_ADDR` unset there is no client, resolution fails, and every group property definition is dropped before the write. Definitions for events and non-group properties are unaffected.
- **`FILTERED_TEAMS` and `FILTER_MODE`** are the first lever to reach for in an incident. `FILTER_MODE` picks whether the team list is an allow-list (`opt_in`) or a block-list (`opt_out`).

## Tests

Tests use sqlx for database interactions. The `.sqlx` offline cache covers the whole crate, so regenerate it after changing any `sqlx::query!` in `src/` or `tests/`:

```bash
cargo sqlx prepare -- --tests
```

Then you can run tests using:

```bash
cargo test
```
