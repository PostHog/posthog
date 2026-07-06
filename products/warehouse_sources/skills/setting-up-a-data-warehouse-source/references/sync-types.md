# Sync type decision guide

Every table in a data warehouse source needs a `sync_type`. The choice determines how data flows on every sync, how
much it costs, how fresh the data is, and what shape it has after import.

## The five sync types

| Sync type      | What it does                                             | Requires                                       | Good for                                             |
| -------------- | -------------------------------------------------------- | ---------------------------------------------- | ---------------------------------------------------- |
| `full_refresh` | Drops everything, re-imports the whole table each sync   | Nothing                                        | Small tables, dimension tables, when in doubt        |
| `incremental`  | Imports only rows where `incremental_field > last_value` | `incremental_field` + `incremental_field_type` | Large tables with an `updated_at` / `modified_at`    |
| `append`       | Like incremental but keeps prior versions of rows        | `incremental_field` + `incremental_field_type` | Immutable or append-only tables (events, logs)       |
| `cdc`          | Streams changes via Postgres logical replication         | Postgres, primary keys, wal_level=logical      | Near-real-time, large Postgres tables                |
| `webhook`      | Real-time push ingestion via source-side webhook         | Source must implement `WebhookSource`          | Near-real-time from sources that support it (Stripe) |

Not every source supports every type — the `db-schema` response surfaces which are available per-table via
`incremental_available`, `append_available`, `cdc_available`, `supports_webhooks`.

## How to choose

**Small table, no obvious ordering column** → `full_refresh`.
Anything under ~50k rows is cheap enough to full-refresh daily. If you can't find a clean `updated_at`, don't try to
fake incremental sync.

**Large table with `updated_at` or `modified_at`** → `incremental` with that field.
This is the common case. Each sync pulls only changed rows since the high-water mark. Much cheaper.

**Large table but only `created_at`** → `incremental` with `created_at`, but warn the user.
`created_at` only catches new rows. Updates to existing rows will be missed. Fine for immutable records; wrong for
mutable ones.

**Large table with no good timestamp but a monotonic integer id** → `incremental` with the id (type `integer`).
Works the same way — new rows have higher ids.

**Immutable events / logs table** → `append` if available, else `incremental`.
Append preserves every version. Useful when the source updates records and you want to track the history rather than
latest-state only.

**Postgres, you need sub-minute freshness** → `cdc`.
CDC streams WAL changes instead of polling. Requires primary keys on each table and Postgres logical replication
setup. Run `external-data-sources-check-cdc-prerequisites-create` first — unmet prerequisites cause the sync to fail
immediately on first run.

**Stripe (or any source where `supports_webhooks: true`)** → consider `webhook` for real-time push.
Set `sync_type: "webhook"` on the tables that support it. Note that a webhook-type schema _still_ does an initial
bulk load before switching to push mode, and keeps a `sync_frequency` for periodic reconciliation. You also need to
call `external-data-sources-create-webhook-create` after source creation — setting the sync_type is necessary but
not sufficient. Tables on the same source that don't support webhooks need a normal bulk `sync_type` alongside.

## Picking an `incremental_field`

Must be present in the `incremental_fields` list returned by `db-schema`. Not every column qualifies — the source
only surfaces timestamp/integer/ObjectID columns that it can filter cheaply.

Priority order:

1. `updated_at` / `modified_at` / `last_modified` / `hs_lastmodifieddate` — catches both inserts and updates.
2. `created_at` / `inserted_at` — catches inserts only, not updates. Only use when you know the table is immutable.
3. A monotonically increasing integer primary key (`id`, `sequence_number`) — same tradeoff as `created_at`.
4. MongoDB `_id` (ObjectId) — sortable by creation time, natural fit for Mongo.

## `incremental_field_type` values

Must match the chosen field:

- `datetime` — `TIMESTAMP`, `DATETIME`, `TIMESTAMP WITH TIME ZONE`
- `date` — `DATE`
- `timestamp` — unix-epoch integer timestamps
- `integer` — `INT`, `BIGINT`, `SERIAL`
- `numeric` — `NUMERIC`, `DECIMAL` where the values are monotonically increasing
- `objectid` — MongoDB ObjectId

If the chosen field and the declared type don't match, the first sync will fail with a type coercion error.

## `primary_key_columns`

Required for `cdc`. Strongly recommended for `incremental` on tables that can have updates, because it's used for
upsert deduplication.

- Use `detected_primary_keys` from db-schema when available.
- If the source didn't detect one but you know the table has a natural key, pass it explicitly.
- If the table genuinely has no unique key, avoid `cdc` — it will fail with "Primary key required for incremental
  syncs" or "primary keys for this table are not unique".

## `cdc_table_mode` (CDC only)

For CDC schemas, `cdc_table_mode` decides what the synced table looks like:

- `consolidated` (default) — the table reflects the current state of each row. Old versions are overwritten.
  Best for operational queries.
- `cdc_only` — the table is an append-only log of every change event (insert / update / delete). No current-state
  view.
- `both` — keep a consolidated current-state table _and_ a separate CDC log table. Most flexible, doubles storage.

## Webhooks are a two-step setup

Unlike the other sync types, `webhook` needs a second API call after source creation:

1. Create the source with `sync_type: "webhook"` on webhook-eligible tables.
2. `external-data-sources-create-webhook-create({id})` to register the webhook with the external service and create
   the HogFunction that processes incoming events.

If step 2 is skipped, webhook-type schemas sit there with no data flowing. If the external service doesn't allow
PostHog to auto-register (usually because the stored API key lacks webhook permissions), fall back to manual setup:
register the webhook in the source's dashboard, then submit the signing secret via
`external-data-sources-update-webhook-inputs-create`.

Only source types that implement `WebhookSource` in the codebase support `sync_type: "webhook"`. Today that's Stripe.
The `supports_webhooks` flag on each table in the db-schema response is the source of truth for what's available.

## Sync frequency

`sync_frequency` is a per-schema option that's orthogonal to `sync_type`. Valid values are (smallest to largest):
`"1min"`, `"5min"`, `"15min"`, `"30min"`, `"1hour"`, `"6hour"`, `"12hour"`, `"24hour"`, `"7day"`, `"30day"`, and
`"never"`.

- For `full_refresh` on anything non-trivial: default to `24hour` — it re-imports everything each run. Sub-hour
  frequencies are usually wasteful for full refresh.
- For `incremental` / `append`: `1hour` or `6hour` is a reasonable default on reasonably sized tables. Sub-minute
  frequencies (`1min`, `5min`) exist but are rarely needed — if the user wants real-time, prefer `cdc` or `webhook`.
- For `cdc`: frequency doesn't really apply — CDC streams continuously.
- For cold archive tables: `7day` or `30day` keeps the schedule alive without wasting runs.

The `never` value freezes the schema — it won't sync automatically, but can still be triggered manually via
`external-data-schemas-reload`.
