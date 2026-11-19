# Fivetran connector notes

## Table matches

Each Fivetran table on a migration item comes with a match to a PostHog table and a confidence:

- `exact`: the names are the same apart from case and underscores, for example `balance_transaction` and `BalanceTransaction`. Use it without asking.
- `inferred`: a naming rule paired them, for example `campaign_history` with `campaigns`. List these pairs and ask the user to confirm them before you apply.
- No match: no rule found a PostHog table. Compare the Fivetran table with the source's PostHog tables and their descriptions, and propose a table when one holds the same records. Mark it as your guess and let the user decide. When nothing fits, say the table does not move.

Propose a pair only when the PostHog table holds the same kind of record. A Fivetran `campaign_report` holds daily metrics, so it is not `campaigns`.

## Per connector

Read the matching note to the user when the migration has that connector.

| Fivetran connector       | What to tell the user                                                                                                                                                                                                                         |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `github`                 | PostHog keeps a separate set of tables for each repository, for example `owner/repo.issues`. Choose the repositories when you connect the source.                                                                                             |
| `google_analytics_4`     | Fivetran custom reports do not move over. Recreate them in the Custom reports field when you connect.                                                                                                                                         |
| `google_search_console`  | PostHog's query and page tables do not break down by country and device like the Fivetran reports do. PostHog also keeps web results apart from image, video and news results, so turn on the tables for the other search types to sync them. |
| `hubspot`                | Newer Fivetran connections keep every engagement in one `engagement` table. PostHog splits engagements into the calls, emails, meetings, notes, tasks and communications tables.                                                              |
| `klaviyo`                | Fivetran keeps email and SMS campaigns in one `campaign` table. PostHog splits them into `email_campaigns` and `sms_campaigns`.                                                                                                               |
| `iterable`               | Fivetran keeps every event in one `event` table. PostHog has one table per event type, such as `email_send` and `push_open`.                                                                                                                  |
| `sql_server_hva`         | Fivetran reads this database through an agent on the user's network. PostHog connects to the database directly, so it must be reachable from PostHog or through an SSH tunnel.                                                                |
| `azure_cosmos_for_mongo` | PostHog reads Cosmos DB for MongoDB with its MongoDB source.                                                                                                                                                                                  |
