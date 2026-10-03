# Event and property definitions generator (propdefs for short)

This consumes events from Kafka, introspects on their names and properties, and writes definition metadata to postgres for the read-side filters in the product.
It filters DB updates to avoid duplicate writes, because writes are idempotent but writing every property definition on every event would be far too much DB load.

Three tables are written: `posthog_eventdefinition`, `posthog_propertydefinition`, and `posthog_eventproperty`.

Hoglets should check out [the runbook](https://runbooks.posthog.com/services/ingestion/concepts/property-defs-rs) for a detailed breakdown of how it's tuned for our current scale, and what metrics to look at and levers to pull if responding to an incident.

## Topic

Production consumes `team_event_partitioned_events_json`, set via `KAFKA_CONSUMER_TOPIC`.
That topic is produced by a WarpStream Bento pipeline that repartitions `clickhouse_events_json` by team, under the separate `property-defs-rs-ws` consumer group.
The in-code default is `clickhouse_events_json`, which is what a local run gets.

AI ingestion removes heavy properties such as `$ai_input` from the shared events output.
Definition discovery must also consume the full `clickhouse_ai_events_json` output, either through the same repartitioning pipeline or through another instance of this service with its own consumer group.
The payload uses the same event format and creates the same canonical event-property definitions.
The writer's conflict keys and caches deduplicate ordinary properties received from both streams and preserve existing definition IDs and access rules.
Never send the full AI payload back to the shared ClickHouse events input to repair discovery.

The local process configuration and Docker Compose configurations run `property-defs-ai` alongside `property-defs-rs`.
It uses `KAFKA_CONSUMER_TOPIC=clickhouse_ai_events_json` and `KAFKA_CONSUMER_GROUP=property-defs-ai`.
Hosted installations must include the AI output in their definition-discovery input configuration too; deploying application code alone does not change that configuration.

Enabling the AI input fixes discovery for subsequent events.
It does not backfill definitions from past events.

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
