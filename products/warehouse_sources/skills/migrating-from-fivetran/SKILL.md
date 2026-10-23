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

| Tool                                         | Purpose                                                                                          |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `warehouse-migration-connect-link`           | Link where the user enters a read-only Fivetran API key in PostHog                               |
| `warehouse-migrations-list`                  | Find the migration the user just started, newest first                                           |
| `warehouse-migration-get`                    | Status of the read, and counts per verdict                                                       |
| `warehouse-migration-items-list`             | One item per Fivetran connection: verdict, caveats, and the planned source                       |
| `data-warehouse-source-connect-link`         | Link where the user enters the secret for one item; pass `migration_item_id` to prefill the rest |
| `data-warehouse-stored-credentials-list`     | Find the credential the user just stored                                                         |
| `external-data-sources-apply-migration-item` | Create the planned source from an item and a stored credential                                   |
| `warehouse-migration-item-skip`              | Mark an item the user does not want to move                                                      |
| `warehouse-migration-refresh`                | Read the Fivetran account again after the user changes it                                        |

Never ask the user to paste a Fivetran key or any source secret into the chat. Every secret goes through a link.

## Workflow

1. **Start the read.** Get a link with `warehouse-migration-connect-link` and share it. Tell the user to create a
   read-only key in Fivetran: a system key with read access to connections, destinations, and the account works best.
   When they confirm, find the newest migration with `warehouse-migrations-list` and poll `warehouse-migration-get`
   until `status` is `ready`. A large account takes a few minutes. If it is `failed`, read `latest_error` to the user.
2. **Report.** List the items with `warehouse-migration-items-list` and group them by verdict:
   - `as_is`: PostHog takes the connection over with the same tables and schedule.
   - `caveats`: PostHog takes it over, but read each caveat to the user. Common ones are an alpha PostHog source, a
     Fivetran table PostHog does not have, history mode, hashed columns, or a schedule PostHog rounds.
   - `unsupported`: PostHog has no source for it yet. Say so plainly and move on.

   End the report with the credentials the user needs, one line per connection.

3. **Move one connection at a time.** Ask which to start with; databases are a good first pick because the user
   already knows the password. For each item:
   - Get `data-warehouse-source-connect-link` with the item's `proposal.source_type` and `migration_item_id`. The page
     shows the host, port, database, and user from Fivetran, so the user types only the secret or clicks the OAuth
     button.
   - When the user confirms, find the credential with `data-warehouse-stored-credentials-list` and call
     `external-data-sources-apply-migration-item` with the item id and the credential id.
   - Read back the caveats the response returns. Apply can add some, for example a table the credentials cannot read.
4. **Wrap up.** Confirm the new sources with `external-data-sources-list`. Suggest the user pauses each Fivetran
   connection only after its PostHog source finished a first sync, so they are never without data.

## Judgment calls

- **Destinations.** If an item's `proposal.destination` names the user's warehouse (Snowflake, BigQuery, and so on),
  ask whether PostHog should write there too. If yes, set up the destination first and pass its id as
  `destination_ids` to apply. Use a schema other than the one Fivetran writes to while both run, or the two tools
  write into the same tables.
- **Prefix taken.** If apply fails because the prefix is in use, offer a new one and pass it as `prefix`.
- **Failed apply.** The item stays retryable. Read `error`, fix the cause with the user, and apply again with a new
  credential, since a stored credential is used up only when a source is created.
- **The user changed Fivetran mid-migration.** Call `warehouse-migration-refresh`. Applied and skipped items stay as
  they are, and the rest are planned again.
