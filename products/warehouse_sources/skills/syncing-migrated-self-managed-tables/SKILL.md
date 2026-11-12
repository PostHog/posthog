---
name: syncing-migrated-self-managed-tables
description: >
  Turn on syncing for warehouse tables that PostHog moved from self-managed tables to managed sources (Amazon S3,
  Google Cloud Storage, Azure Blob, Cloudflare R2 or File upload). Use when the user asks "what happened to my
  self-managed tables", "how do I sync my migrated bucket tables", "why does my table say it is waiting for its first
  sync", "will I be billed for these tables", or when a migrated table fails its first sync with access denied, "No
  files are available for table", or "PostHog did not replace the self-managed table".
---

# Syncing migrated self-managed tables

PostHog no longer links tables that read a bucket directly. Eligible existing self-managed tables now have a managed
source and a schema that is turned off. The table keeps working and keeps its name. It costs nothing until someone turns
syncing on. Turning syncing on starts billing, so the user must agree first.

## What happened

- PostHog made one source for each bucket and key prefix. Tables that need different access rules get different
  sources.
- Each table got one schema with `should_sync` set to `false`. The schema reads the same files that the table read.
- The table keeps its id and name. Queries, views and insights that use it keep working.
- Until the first sync, ClickHouse still reads the user's bucket on every query. There is no charge for this.
- The first successful sync "adopts" the table. PostHog copies the data into its own storage and points the same table
  row at the copy. After that, the table is a normal imported table and is billed like one.
- Source descriptions show the origin: "Self-managed tables in <bucket>" for bucket sources and "Uploaded file for
  <name>" for file upload sources.

## Available tools

| Tool                                              | Purpose                                                      |
| ------------------------------------------------- | ------------------------------------------------------------ |
| `external-data-sources-list`                      | Find the migrated sources by description                     |
| `external-data-schemas-list`                      | Find schemas with `pending_self_managed_table` set to `true` |
| `external-data-schemas-retrieve`                  | Read one schema: sync config, status, `latest_error`         |
| `external-data-schemas-partial-update`            | Turn syncing on, and set `sync_type` and `sync_frequency`    |
| `external-data-sources-bulk-update-schemas`       | Do the same for many schemas of one source in one request    |
| `external-data-schemas-incremental-fields-create` | See which sync methods the table supports                    |
| `external-data-schemas-reload`                    | Start a sync now, only if none started on its own            |
| `external-data-schemas-cancel`                    | Stop a sync that is running                                  |

## Workflow

### Step 1 - Find the tables

Call `external-data-schemas-list`. A table that waits for its first sync has `pending_self_managed_table: true`.
You can also look for sources with `external-data-sources-list` and read their descriptions.

A table that is still listed as self-managed in the warehouse tables was not migrated. See "Tables that were not
migrated".

### Step 2 - Ask the user before you change anything

Turning syncing on starts billing. Rows that a sync imports count toward data warehouse usage, like any other import.
Tell the user which tables you plan to sync, and how often. Wait for a clear yes. Do not turn syncing on for tables the
user did not name.

A table that the user does not want to import can stay as it is. It keeps reading the bucket for free.

### Step 3 - Pick the sync method

Call `external-data-schemas-incremental-fields-create` for the schema to see what the table supports.

- `full_refresh` is the default and the safe choice. Each sync reads all files again and replaces the table.
- `incremental` and `append` for file tables use the file modification time (`_file_modified_at`). A sync reads only
  files that changed since the last sync.
  - `incremental` replaces the rows of a file that was rewritten and drops the rows of a file that was deleted. Use it
    when a writer updates existing files.
  - `append` only adds rows. A rewritten file is imported again on top of its old rows, so the table keeps stale rows
    and duplicates. Use `append` only when every file is written once and never changed.
- An `incremental` Delta table reads only the data files that changed since the last sync. When the writer deletes,
  updates or rewrites data, the sync replaces the rows of the removed files and reads the new files. It reads the
  whole table again only when the table was made again (a new Delta table id), its version went back, or the
  stored version can no longer be read.
- A table that a writer replaces on each run (for example a dlt `replace` write) is always read in full. Use
  `full_refresh` for it.

Do not change `sync_type` on a table that is already running. Wait for the sync to end, or cancel it first.

### Step 4 - Turn syncing on

For one schema, call `external-data-schemas-partial-update` with only the fields that change:

```json
{ "should_sync": true, "sync_type": "full_refresh", "sync_frequency": "24hour" }
```

For `incremental` or `append`, also send the cursor. Migrated schemas have no stored cursor, so the update is rejected
without it. Take `field` and `field_type` from the `incremental_fields` entry that
`external-data-schemas-incremental-fields-create` returned (`_file_modified_at` for file tables, `_delta_version` for
Delta tables):

```json
{
  "should_sync": true,
  "sync_type": "incremental",
  "incremental_field": "<field>",
  "incremental_field_type": "<field_type>",
  "sync_frequency": "24hour"
}
```

For many schemas of one source, use `external-data-sources-bulk-update-schemas` with one entry per schema.

Choose a `sync_frequency` that matches how often the bucket changes. A less frequent schedule bills fewer rows.
Turning syncing on usually starts the first sync by itself. Do not call `external-data-schemas-reload` right away: a
reload after a sync that already ran imports and bills every row again. Call `external-data-schemas-retrieve` first,
and call the reload only if, after a minute or two, no sync has started (`status` is still empty and there is no
`last_synced_at`). In the web app, turning syncing on shows a
confirmation dialog for these tables.

### Step 5 - Check the first sync

Call `external-data-schemas-retrieve` a few times, a minute or more apart, until `status` is no longer `Running`. A
large table can take a long time; if it is still running after about 15 minutes, stop polling and tell the user to
check back later.

- `Completed`: report `last_synced_at`.
- `Failed`: read `latest_error` and see "Troubleshooting".
- `BillingLimitReached` or `BillingLimitTooLow`: the sync stopped because of the data warehouse billing limit. Stop
  polling and tell the user. The sync can run only after they raise the limit or the billing period resets.

## What changes after the first sync

- The table is adopted. The id and the name stay the same, so existing queries keep working.
- The table no longer reads the bucket live. It changes only when a sync runs, on the sync schedule.
- Nested columns (Array, Map, Tuple, JSON) become JSON text. Read them with `JSONExtract(col, '<type>')`, where
  `<type>` is the ClickHouse type that the column had before.
- Old queries can need small changes for nested columns. Tell the user about this before the first sync when the table
  has such columns.

## Uploaded files

A table that came from an uploaded file has a File upload source that reads one file. It does not sync on a schedule.
To change the data, the user replaces the file with the "Replace file" action on the table in the web app (the
`replace_file` endpoint). The replacement syncs the new file and bills its rows. The old file is deleted only after the
new sync succeeds. No MCP tool uploads or replaces a file, so ask the user to do this step in the app.

## Troubleshooting

Find the text in `latest_error` on the schema. These are the exact messages from the code. Some errors turn syncing
off (`should_sync` becomes `false`), and `latest_error` then shows a shorter message, given below. After the user
fixes the cause, turn syncing on again with `external-data-schemas-partial-update` (`{"should_sync": true}`); waiting
alone does not resume the sync. Turning a failed schema back on only resumes its schedule and does not start a sync,
and the schema keeps its old `Failed` status. So call `external-data-schemas-reload` to retry now; the last sync
failed, so this does not import the rows twice. Then check the sync as in step 5.

- `The storage provider denied access to the bucket '<location>'. Check the access key and secret, and that the key can
list and read objects in this bucket.` The key from the old table is no longer valid, or it cannot list and read the
  table's folder. For a Delta table the message reads `... denied access to the bucket for the Delta table '<name>'.
Check that the key can read its folder.` The key must list and read the table's whole path. This error turns syncing
  off and can show as `The storage provider rejected these credentials. ...`. Ask the user to fix the key's access in
  their storage provider, or reconnect the source with new credentials through a connect link, as in scenario B of
  `diagnosing-failed-warehouse-syncs`. Do not ask for keys in the chat or send them through a tool. Then turn syncing
  on again.
- `No files are available for table '<name>'. No file in the bucket matches '<pattern>'.` No file matches the table's
  pattern now. The files may have been moved, renamed or removed. A variant says `The files it was discovered from may
have been renamed, moved, or removed from the bucket.` Ask the user to check the bucket.
- `No files are available for table '<name>'. The Delta table is no longer at its folder in the bucket.` A writer
  replaced the table and its folder is missing. Within one sync, PostHog waits and retries a few times, because the
  table often comes back by itself.
- Both `No files are available` errors turn syncing off when they fail the sync, and can show as
  `The files behind this table are no longer in the bucket. ...`. Ask the user to restore the files or the Delta
  folder, then turn syncing on again.
- `PostHog did not replace the self-managed table '<name>', because <reason>. The table still reads its own files. To
continue, an organization admin must make the access rules of this source the same as the rules of the table, then
turn syncing on again. PostHog support can help with this.` Access rules changed after the move. The sync fails once
  and stops on purpose, and the table keeps reading the bucket. An organization admin must match the rules of the
  source to the rules of the table. Then turn syncing on again.

### Tables that were not migrated

A table that was not migrated stays self-managed and keeps reading its bucket. PostHog skips a table when:

- the URL is not a storage host that a managed source reads (it must be Amazon S3, Google Cloud Storage, Azure Blob or
  Cloudflare R2),
- an S3 URL does not name the bucket's region and S3 does not return it,
- the table needs access rules that a source cannot carry (the table has its own rules, the project has rules for
  sources or for the warehouse, or the rules name too many roles),
- the file format or a column type has no import equivalent, or a column has the name of a column that the import adds.

PostHog does not create new self-managed tables any more. For these tables, tell the user to add the bucket as a new
managed source, or to contact PostHog support.

## Important notes

- Ask before you turn syncing on. It starts billing.
- Do not guess field names or errors. Read the schema first with `external-data-schemas-retrieve`.
- Do not run `external-data-schemas-resync` or `external-data-schemas-delete-data` on a migrated table that has not
  synced yet. They are not needed and they can remove data.
