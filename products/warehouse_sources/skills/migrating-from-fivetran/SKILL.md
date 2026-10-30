---
name: migrating-from-fivetran
description: >
  Move a user's Fivetran connectors into PostHog data warehouse sources. Use when the user says "migrate from
  Fivetran", "import my Fivetran setup", "replace Fivetran with PostHog", or asks what of their Fivetran account
  PostHog can take over. Reads the Fivetran account with a read-only key, reports which connections move as they are,
  which move with caveats, and which PostHog cannot take yet, then creates the PostHog sources one at a time while the
  user enters only the secrets.
---

# Migrating from Fivetran

PostHog can read a Fivetran account and plan one PostHog source per Fivetran connection: the tables, the sync
schedule, the table prefix, and the destination. It cannot copy secrets. Fivetran never returns passwords, API keys,
or OAuth tokens to anyone, so the user re-enters one credential per connection. Say this early, so the user is not
surprised halfway through.

## Tools

| Tool                                     | Purpose                                                                                          |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `warehouse-migration-connect-link`       | Link where the user enters a read-only Fivetran API key in PostHog                               |
| `warehouse-migrations-list`              | Find the migration the user just started, newest first                                           |
| `warehouse-migration-get`                | Status of the read, and counts per verdict                                                       |
| `warehouse-migration-items-list`         | One item per Fivetran connection: verdict, caveats, and the planned source type                  |
| `data-warehouse-source-connect-link`     | Link where the user enters the secret for one item; pass `migration_item_id` to prefill the rest |
| `data-warehouse-stored-credentials-list` | Find the credential the user just stored                                                         |
| `warehouse-migration-item-apply`         | Create the planned source from an item and a stored credential                                   |
| `warehouse-migration-item-skip`          | Mark an item the user does not want to move                                                      |
| `warehouse-migration-items-skip`         | Skip many items at once, or all but the ones to keep (`keep_item_ids`)                           |
| `warehouse-migration-refresh`            | Read the Fivetran account again after the user changes it                                        |

Never ask the user to paste a Fivetran key or any source secret into the chat. Every secret goes through a link.

The connector notes (`references/connector-notes.md`, when this skill ships them) explain how PostHog matches Fivetran
tables and hold a note for each connector that differs. Read them before the report when they are there.

## Workflow

If `warehouse-migration-connect-link` is not among your tools, importing from Fivetran is not available for this
project yet. Tell the user that and stop.

1. **Start the read.** Get a link with `warehouse-migration-connect-link` and share it. Tell the user to create a
   read-only key in Fivetran: a system key with read access to connections, destinations, and the account works best.
   When they confirm, find the newest migration with `warehouse-migrations-list` and poll `warehouse-migration-get`
   until `status` is `ready`. A large account takes a few minutes. If it is `failed`, read `latest_error` to the user.
2. **Report.** List the items with `warehouse-migration-items-list`. Lead with what is worth moving:
   - `as_is`: PostHog takes the connection over with the same tables and schedule.
   - `caveats`: PostHog takes it over, but read each caveat to the user. Common ones are an alpha PostHog source, a
     Fivetran table PostHog does not have, history mode, hashed columns, or a schedule PostHog rounds.
   - `unsupported`: PostHog has no source for it yet. Say so plainly.

   Group the connections by destination, and name each connection under its destination. Read the destination from
   each item's `proposal.destination` (its type and settings, such as host and database). Never assume all
   connections write to one place: two Postgres destinations on different hosts are two groups.

   Up front, suggest skipping the connections that are broken or paused in Fivetran (their caveats say so) and the
   unsupported ones. When the user wants to move only some connections, skip the rest in one call with
   `warehouse-migration-items-skip`: pass `keep_item_ids` for "migrate only these", or `item_ids` for "skip these".

   For each connection the user keeps, check the tables of its `proposal`:
   - `inferred_tables`: a naming rule paired these Fivetran tables with PostHog tables. List the pairs and ask the user
     to confirm each one.
   - `unmatched_tables`: no PostHog table matched. Compare each one with `unused_posthog_tables` and propose a table
     that holds the same records, marked as your guess. When nothing fits, say the table does not move.
   - Read the connector note for any connector in the migration.

   Pass what the user decides to apply as `table_overrides`: `{vendor_table, posthog_table}` maps a table, and a null
   `posthog_table` leaves it out. `vendor_table` is a planned table's `proposal.schemas[].vendor_table` (a database
   names it `schema.table`), or a name from `unmatched_tables`. End the report with the credentials the user needs,
   one line per connection.

3. **Ask one decision at a time.** A decision that changes the result blocks the step it belongs to: where the data
   goes, which table pairs hold, which connections move. Ask one such question, wait for the answer, then ask the
   next. Never go ahead on a default for one of these.
4. **Set up the destination before apply.** When an item's `proposal.destination` is set, settle it as its own step
   before you apply that item. Recommend writing to the same destination type as Fivetran, into the schema
   `posthog_<prefix>` (the item's `proposal.prefix`), so the two tools never write into the same tables while both
   run. Wait for the answer. If the user agrees, share `external-data-destinations-connect-link` with
   `migration_item_id` set to the item, so the page fills in the connection settings from Fivetran and the user
   types only the secret. The page does not set the schema. Then create the destination with
   `external-data-destinations-create`, and pass `posthog_<prefix>` as the schema in its target config, with the
   other target values the link's `instructions` suggest. Pass the new destination's id as `destination_ids` to
   apply.
   Attached at creation, the destination gets the full history in the first sync. If those tools are not available,
   the data lands in the PostHog warehouse only.
5. **Move one connection at a time.** Ask which to start with; databases are a good first pick because the user
   already knows the password. For each item:
   - Get `data-warehouse-source-connect-link` with the item's `proposal.source_type` and `migration_item_id`. The page
     shows the host, port, database, and user from Fivetran, so the user types only the secret or clicks the OAuth
     button.
   - When the user confirms, find the credential with `data-warehouse-stored-credentials-list` and call
     `warehouse-migration-item-apply` with the item id, the credential id, the confirmed `table_overrides`, and the
     `destination_ids` from step 4.
   - Read back the caveats the response returns. Apply can add some, for example a table the credentials cannot read.
6. **Wrap up.** Confirm the new sources with `external-data-sources-list`. Suggest the user pauses each Fivetran
   connection only after its PostHog source finished a first sync, so they are never without data.

## Judgment calls

- **A destination added after apply.** It starts empty: it gets only rows synced from then on. Offer this only as a
  fallback when the user decides late, and say a resync fills it.
- **Prefix taken.** If apply fails because the prefix is in use, offer a new one and pass it as `prefix`.
- **Failed apply.** The item stays retryable. Read `error` and fix the cause with the user. A stored credential is used
  up only when a source is created, so apply again with the same `credential_id`. Send a new connect link only when
  the error says the credential was not found, expired (after 24 hours) or rejected.
- **The user changed Fivetran mid-migration.** Call `warehouse-migration-refresh`. Applied, skipped and in-progress
  items stay as they are, and the rest are planned again.
