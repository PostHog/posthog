/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Manage where warehouse sources write their synced rows.
 *
 * A destination can be attached to several sources, or to a single table on a source.
 * Credentials come from an integration, so one connection can be reused across syncs.
 */
export const externalDataDestinationsCreateBodyNameMax = 400

export const ExternalDataDestinationsCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['PostHogWarehouse', 'Redshift', 'Snowflake', 'BigQuery', 'Postgres', 'Databricks', 'AzureBlob', 'S3'])
        .describe(
            '\* `PostHogWarehouse` - PostHog warehouse\n\* `Redshift` - Redshift\n\* `Snowflake` - Snowflake\n\* `BigQuery` - BigQuery\n\* `Postgres` - Postgres\n\* `Databricks` - Databricks\n\* `AzureBlob` - Azure Blob\n\* `S3` - S3'
        )
        .describe(
            'Where synced rows are written. The PostHog warehouse is managed for you, so you cannot create one here.\n\n\* `PostHogWarehouse` - PostHog warehouse\n\* `Redshift` - Redshift\n\* `Snowflake` - Snowflake\n\* `BigQuery` - BigQuery\n\* `Postgres` - Postgres\n\* `Databricks` - Databricks\n\* `AzureBlob` - Azure Blob\n\* `S3` - S3'
        ),
    name: zod
        .string()
        .max(externalDataDestinationsCreateBodyNameMax)
        .describe('Human-readable name shown when picking destinations for a source or table.'),
    config: zod
        .unknown()
        .optional()
        .describe(
            'Settings for this destination: target database, schema or dataset, bucket and prefix, file format. Credentials are not stored here. They live on the linked integration.'
        ),
    integration: zod
        .number()
        .nullish()
        .describe(
            "Integration holding this destination's credentials. Required for every type except the PostHog warehouse."
        ),
})

/**
 * Manage where warehouse sources write their synced rows.
 *
 * A destination can be attached to several sources, or to a single table on a source.
 * Credentials come from an integration, so one connection can be reused across syncs.
 */
export const externalDataDestinationsUpdateBodyNameMax = 400

export const ExternalDataDestinationsUpdateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['PostHogWarehouse', 'Redshift', 'Snowflake', 'BigQuery', 'Postgres', 'Databricks', 'AzureBlob', 'S3'])
        .describe(
            '\* `PostHogWarehouse` - PostHog warehouse\n\* `Redshift` - Redshift\n\* `Snowflake` - Snowflake\n\* `BigQuery` - BigQuery\n\* `Postgres` - Postgres\n\* `Databricks` - Databricks\n\* `AzureBlob` - Azure Blob\n\* `S3` - S3'
        )
        .describe(
            'Where synced rows are written. The PostHog warehouse is managed for you, so you cannot create one here.\n\n\* `PostHogWarehouse` - PostHog warehouse\n\* `Redshift` - Redshift\n\* `Snowflake` - Snowflake\n\* `BigQuery` - BigQuery\n\* `Postgres` - Postgres\n\* `Databricks` - Databricks\n\* `AzureBlob` - Azure Blob\n\* `S3` - S3'
        ),
    name: zod
        .string()
        .max(externalDataDestinationsUpdateBodyNameMax)
        .describe('Human-readable name shown when picking destinations for a source or table.'),
    config: zod
        .unknown()
        .optional()
        .describe(
            'Settings for this destination: target database, schema or dataset, bucket and prefix, file format. Credentials are not stored here. They live on the linked integration.'
        ),
    integration: zod
        .number()
        .nullish()
        .describe(
            "Integration holding this destination's credentials. Required for every type except the PostHog warehouse."
        ),
})

/**
 * Manage where warehouse sources write their synced rows.
 *
 * A destination can be attached to several sources, or to a single table on a source.
 * Credentials come from an integration, so one connection can be reused across syncs.
 */
export const externalDataDestinationsPartialUpdateBodyNameMax = 400

export const ExternalDataDestinationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['PostHogWarehouse', 'Redshift', 'Snowflake', 'BigQuery', 'Postgres', 'Databricks', 'AzureBlob', 'S3'])
        .describe(
            '\* `PostHogWarehouse` - PostHog warehouse\n\* `Redshift` - Redshift\n\* `Snowflake` - Snowflake\n\* `BigQuery` - BigQuery\n\* `Postgres` - Postgres\n\* `Databricks` - Databricks\n\* `AzureBlob` - Azure Blob\n\* `S3` - S3'
        )
        .optional()
        .describe(
            'Where synced rows are written. The PostHog warehouse is managed for you, so you cannot create one here.\n\n\* `PostHogWarehouse` - PostHog warehouse\n\* `Redshift` - Redshift\n\* `Snowflake` - Snowflake\n\* `BigQuery` - BigQuery\n\* `Postgres` - Postgres\n\* `Databricks` - Databricks\n\* `AzureBlob` - Azure Blob\n\* `S3` - S3'
        ),
    name: zod
        .string()
        .max(externalDataDestinationsPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable name shown when picking destinations for a source or table.'),
    config: zod
        .unknown()
        .optional()
        .describe(
            'Settings for this destination: target database, schema or dataset, bucket and prefix, file format. Credentials are not stored here. They live on the linked integration.'
        ),
    integration: zod
        .number()
        .nullish()
        .describe(
            "Integration holding this destination's credentials. Required for every type except the PostHog warehouse."
        ),
})

/**
 * Manage where warehouse sources write their synced rows.
 *
 * A destination can be attached to several sources, or to a single table on a source.
 * Credentials come from an integration, so one connection can be reused across syncs.
 */
export const externalDataDestinationsAddSourcesCreateBodySourceIdsMax = 50

export const externalDataDestinationsAddSourcesCreateBodyResyncDefault = false

export const ExternalDataDestinationsAddSourcesCreateBody = /* @__PURE__ */ zod.object({
    source_ids: zod
        .array(zod.uuid())
        .max(externalDataDestinationsAddSourcesCreateBodySourceIdsMax)
        .describe('IDs of up to 50 existing sources to attach to this destination.'),
    resync: zod
        .boolean()
        .default(externalDataDestinationsAddSourcesCreateBodyResyncDefault)
        .describe('Start a full resync for each enabled table newly attached.'),
})

export const externalDataSchemasUpdateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasUpdateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const externalDataSchemasUpdateBodyFullRefreshIntervalDaysMax = 90

export const externalDataSchemasUpdateBodyApiVersionMax = 128

export const ExternalDataSchemasUpdateBody = /* @__PURE__ */ zod
    .object({
        should_sync: zod.boolean().optional(),
        sync_type: zod
            .union([
                zod
                    .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc', 'xmin'])
                    .describe(
                        '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc\n\* `xmin` - xmin'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Sync strategy: incremental, full_refresh, append, cdc, or xmin.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc\n\* `xmin` - xmin'
            ),
        incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
        incremental_field_type: zod
            .union([
                zod
                    .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid', 'xid'])
                    .describe(
                        '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid\n\* `xid` - xid'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid\n\* `xid` - xid'
            ),
        incremental_field_lookback_seconds: zod
            .number()
            .min(externalDataSchemasUpdateBodyIncrementalFieldLookbackSecondsMin)
            .max(externalDataSchemasUpdateBodyIncrementalFieldLookbackSecondsMax)
            .nullish()
            .describe(
                'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp\/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum(['never', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day'])
                    .describe(
                        '\* `never` - never\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'How often to sync. The fastest sync frequency is 5 minutes.\n\n\* `never` - never\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
            ),
        sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
        full_refresh_interval_days: zod
            .number()
            .min(1)
            .max(externalDataSchemasUpdateBodyFullRefreshIntervalDaysMax)
            .nullish()
            .describe(
                'Days between scheduled full refreshes, from 1 to 90, or null for none. A full refresh wipes the table and re-imports every row, so rows deleted at the source are removed. It runs on the first scheduled sync once the interval has passed, counted from when it was saved or from the last full resync (or, when full_refresh_time_of_day is set, from the slot of that time the last refresh served), and can start up to an hour early. Queries keep returning the current rows until a full refresh finishes, and workflows and destinations that run on new rows of the table run again for every row. Available for incremental, append, and xmin syncs only, and never shorter than the sync frequency.'
            ),
        full_refresh_time_of_day: zod.iso
            .time({})
            .nullish()
            .describe(
                'UTC time of day (HH:MM:SS) that scheduled full refreshes are due, for example outside working hours. The refresh runs on the first scheduled sync from up to an hour before this time, so on a table that syncs every few hours it can run hours later. Each interval counts from the slot of this time that the last refresh or save served, where a slot less than an hour away counts as served. Saving a new time restarts the clock, so the first refresh after a save can come up to a day before a full interval has passed. Null counts the interval from when it was saved or from the last full resync. Cleared when full_refresh_interval_days is null.'
            ),
        primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
        cdc_table_mode: zod
            .union([
                zod
                    .enum(['consolidated', 'cdc_only', 'both'])
                    .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'),
                zod.null(),
            ])
            .optional()
            .describe(
                'For CDC syncs: consolidated, cdc_only, or both.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
            ),
        enabled_columns: zod
            .array(zod.string())
            .nullish()
            .describe(
                'Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.'
            ),
        row_filters: zod
            .array(
                zod.object({
                    column: zod.string(),
                    operator: zod.string().describe('One of: > >= < <= = != IN \"NOT IN\".'),
                    value: zod
                        .unknown()
                        .describe(
                            "Comparison value; must match the column's type. For `IN` \/ `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`)."
                        ),
                })
            )
            .nullish()
            .describe(
                "Predicates ANDed onto the source query so only matching rows sync. Each is `{column, operator, value}`; `null`\/empty (default) syncs all rows. The operator must be one of `> >= < <= = != IN \"NOT IN\"` and the value must match the column's type (for `IN`\/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). Applied on the next sync — not retroactive to already-synced rows."
            ),
        api_version: zod
            .string()
            .max(externalDataSchemasUpdateBodyApiVersionMax)
            .nullish()
            .describe(
                "Vendor API version override for this schema. `null` (default) syncs on the source's pinned version. Must be one of the source type's supported versions. User-managed: version-migration tooling never changes it. Not available for webhook-sync schemas."
            ),
    })
    .describe('A schema of an external data source: its sync configuration and the warehouse table it syncs into.')

export const externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const externalDataSchemasPartialUpdateBodyFullRefreshIntervalDaysMax = 90

export const externalDataSchemasPartialUpdateBodyApiVersionMax = 128

export const ExternalDataSchemasPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        should_sync: zod.boolean().optional(),
        sync_type: zod
            .union([
                zod
                    .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc', 'xmin'])
                    .describe(
                        '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc\n\* `xmin` - xmin'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Sync strategy: incremental, full_refresh, append, cdc, or xmin.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc\n\* `xmin` - xmin'
            ),
        incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
        incremental_field_type: zod
            .union([
                zod
                    .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid', 'xid'])
                    .describe(
                        '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid\n\* `xid` - xid'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid\n\* `xid` - xid'
            ),
        incremental_field_lookback_seconds: zod
            .number()
            .min(externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMin)
            .max(externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMax)
            .nullish()
            .describe(
                'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp\/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum(['never', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day'])
                    .describe(
                        '\* `never` - never\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'How often to sync. The fastest sync frequency is 5 minutes.\n\n\* `never` - never\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
            ),
        sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
        full_refresh_interval_days: zod
            .number()
            .min(1)
            .max(externalDataSchemasPartialUpdateBodyFullRefreshIntervalDaysMax)
            .nullish()
            .describe(
                'Days between scheduled full refreshes, from 1 to 90, or null for none. A full refresh wipes the table and re-imports every row, so rows deleted at the source are removed. It runs on the first scheduled sync once the interval has passed, counted from when it was saved or from the last full resync (or, when full_refresh_time_of_day is set, from the slot of that time the last refresh served), and can start up to an hour early. Queries keep returning the current rows until a full refresh finishes, and workflows and destinations that run on new rows of the table run again for every row. Available for incremental, append, and xmin syncs only, and never shorter than the sync frequency.'
            ),
        full_refresh_time_of_day: zod.iso
            .time({})
            .nullish()
            .describe(
                'UTC time of day (HH:MM:SS) that scheduled full refreshes are due, for example outside working hours. The refresh runs on the first scheduled sync from up to an hour before this time, so on a table that syncs every few hours it can run hours later. Each interval counts from the slot of this time that the last refresh or save served, where a slot less than an hour away counts as served. Saving a new time restarts the clock, so the first refresh after a save can come up to a day before a full interval has passed. Null counts the interval from when it was saved or from the last full resync. Cleared when full_refresh_interval_days is null.'
            ),
        primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
        cdc_table_mode: zod
            .union([
                zod
                    .enum(['consolidated', 'cdc_only', 'both'])
                    .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'),
                zod.null(),
            ])
            .optional()
            .describe(
                'For CDC syncs: consolidated, cdc_only, or both.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
            ),
        enabled_columns: zod
            .array(zod.string())
            .nullish()
            .describe(
                'Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.'
            ),
        row_filters: zod
            .array(
                zod.object({
                    column: zod.string(),
                    operator: zod.string().describe('One of: > >= < <= = != IN \"NOT IN\".'),
                    value: zod
                        .unknown()
                        .describe(
                            "Comparison value; must match the column's type. For `IN` \/ `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`)."
                        ),
                })
            )
            .nullish()
            .describe(
                "Predicates ANDed onto the source query so only matching rows sync. Each is `{column, operator, value}`; `null`\/empty (default) syncs all rows. The operator must be one of `> >= < <= = != IN \"NOT IN\"` and the value must match the column's type (for `IN`\/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). Applied on the next sync — not retroactive to already-synced rows."
            ),
        api_version: zod
            .string()
            .max(externalDataSchemasPartialUpdateBodyApiVersionMax)
            .nullish()
            .describe(
                "Vendor API version override for this schema. `null` (default) syncs on the source's pinned version. Must be one of the source type's supported versions. User-managed: version-migration tooling never changes it. Not available for webhook-sync schemas."
            ),
    })
    .describe('A schema of an external data source: its sync configuration and the warehouse table it syncs into.')

/**
 * Read or replace this table's destination override.
 *
 * Send `destination_ids: null` to clear the override so the table follows its source again.
 */
export const ExternalDataSchemasDestinationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    destination_ids: zod
        .array(zod.uuid())
        .nullish()
        .describe(
            'Destinations to sync to. On a table, null clears the override so the table follows its source again.'
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesCreateBodyPrefixMax = 100

export const externalDataSourcesCreateBodyDescriptionMax = 400

export const externalDataSourcesCreateBodyAccessMethodDefault = `warehouse`
export const externalDataSourcesCreateBodyCreatedViaDefault = `api`
export const externalDataSourcesCreateBodyDirectQueryEnabledDefault = false

export const ExternalDataSourcesCreateBody = /* @__PURE__ */ zod.object({
    source_type: zod.string().describe("The source type (e.g. 'Postgres', 'Stripe')."),
    payload: zod
        .record(zod.string(), zod.unknown())
        .describe(
            "Connection credentials. Keys depend on source_type. Add a 'schemas' array to pick which tables sync; omit it and every discovered table syncs with default settings."
        ),
    prefix: zod
        .string()
        .max(externalDataSourcesCreateBodyPrefixMax)
        .nullish()
        .describe(
            'Prefix added to the table names PostHog creates in HogQL. Does not filter which tables are imported.'
        ),
    description: zod
        .string()
        .max(externalDataSourcesCreateBodyDescriptionMax)
        .nullish()
        .describe('Human-readable description.'),
    access_method: zod
        .enum(['warehouse', 'direct'])
        .describe('\* `warehouse` - warehouse\n\* `direct` - direct')
        .default(externalDataSourcesCreateBodyAccessMethodDefault)
        .describe(
            "Connection mode: 'warehouse' (import) or 'direct' (live query).\n\n\* `warehouse` - warehouse\n\* `direct` - direct"
        ),
    created_via: zod
        .enum(['web', 'api', 'mcp'])
        .describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp')
        .default(externalDataSourcesCreateBodyCreatedViaDefault)
        .describe(
            'Where the request came from: `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. `wizard` and `self_driving` cannot be set directly — they are derived server-side for wizard- and PostHog Desktop-driven MCP calls. Defaults to `api`.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
        ),
    direct_query_enabled: zod
        .boolean()
        .default(externalDataSourcesCreateBodyDirectQueryEnabledDefault)
        .describe(
            'Whether a synced source should also be live-queryable via direct connection. Defaults to false; ignored for pure direct-query sources.'
        ),
    destination_ids: zod
        .array(zod.uuid())
        .optional()
        .describe(
            'Destinations every table on this source writes to. Set here rather than afterwards, so the opening sync already carries them. Omit to write to the PostHog warehouse only.'
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesUpdateBodyPrefixMax = 100

export const externalDataSourcesUpdateBodyDescriptionMax = 400

export const externalDataSourcesUpdateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesUpdateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesUpdateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateBodyDescriptionMax).nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesUpdateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesUpdateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesPartialUpdateBodyDescriptionMax = 400

export const externalDataSourcesPartialUpdateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesPartialUpdateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string().optional(),
        account_id: zod.string().optional(),
        prefix: zod.string().max(externalDataSourcesPartialUpdateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesPartialUpdateBodyDescriptionMax).nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesPartialUpdateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesPartialUpdateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesBulkUpdateSchemasPartialUpdateBodySchemasItemFullRefreshIntervalDaysMax = 90

export const ExternalDataSourcesBulkUpdateSchemasPartialUpdateBody = /* @__PURE__ */ zod.object({
    schemas: zod
        .array(
            zod.object({
                id: zod.uuid().describe('Schema identifier to update.'),
                should_sync: zod.boolean().optional().describe('Whether the schema should be queryable\/synced.'),
                sync_type: zod
                    .union([
                        zod
                            .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc', 'xmin'])
                            .describe(
                                '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc\n\* `xmin` - xmin'
                            ),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'Requested sync mode for the schema (incremental, full_refresh, append, cdc, or xmin).\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc\n\* `xmin` - xmin'
                    ),
                incremental_field: zod
                    .string()
                    .nullish()
                    .describe('Incremental cursor field for incremental or append syncs.'),
                incremental_field_type: zod.string().nullish().describe('Type of the incremental cursor field.'),
                sync_frequency: zod.string().nullish().describe('Human-readable sync frequency value.'),
                sync_time_of_day: zod.iso.time({}).nullish().describe('UTC anchor time for scheduled syncs.'),
                full_refresh_interval_days: zod
                    .number()
                    .min(1)
                    .max(externalDataSourcesBulkUpdateSchemasPartialUpdateBodySchemasItemFullRefreshIntervalDaysMax)
                    .nullish()
                    .describe(
                        'Days between scheduled full refreshes, from 1 to 90, or null for none. A full refresh wipes the table and re-imports every row. Re-imported rows count toward usage, and workflows and destinations that run on new rows of the table run again for every row. Incremental, append, and xmin syncs only, and never shorter than the sync frequency.'
                    ),
                full_refresh_time_of_day: zod.iso
                    .time({})
                    .nullish()
                    .describe(
                        'UTC time of day (HH:MM:SS) that scheduled full refreshes are due, for example outside working hours. The refresh runs on the first scheduled sync from up to an hour before this time, so on a table that syncs every few hours it can run hours later. Each interval counts from the slot of this time that the last refresh or save served, where a slot less than an hour away counts as served. Saving a new time restarts the clock, so the first refresh after a save can come up to a day before a full interval has passed. Null counts the interval from when it was saved or from the last full resync. Cleared when full_refresh_interval_days is null.'
                    ),
                primary_key_columns: zod
                    .array(zod.string())
                    .nullish()
                    .describe('Column names for primary key deduplication.'),
                cdc_table_mode: zod
                    .union([
                        zod
                            .enum(['consolidated', 'cdc_only', 'both'])
                            .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'How CDC-backed tables should be exposed.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
                    ),
                enabled_columns: zod
                    .array(zod.string())
                    .nullish()
                    .describe('Columns to sync. Null means sync all columns.'),
                row_filters: zod
                    .array(
                        zod.object({
                            column: zod.string(),
                            operator: zod.string().describe('One of: > >= < <= = != IN \"NOT IN\".'),
                            value: zod
                                .unknown()
                                .describe(
                                    "Comparison value; must match the column's type. For `IN` \/ `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`)."
                                ),
                        })
                    )
                    .nullish()
                    .describe('Row-filter predicates ANDed onto the source query. Null\/empty means sync all rows.'),
                apply_sync_defaults: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When true and the schema has no sync method configured yet (and this update does not set one), discover the table on the source and fill in default sync settings: incremental sync with an auto-selected tracking column where supported, otherwise append, otherwise full refresh. Ignored for schemas that already have a sync method.'
                    ),
            })
        )
        .describe('Schema updates to apply in a single batch.'),
})

/**
 * Validate CDC prerequisites for an existing source using its stored credentials.
 *
 * The detail=False ``check_cdc_prerequisites`` action is for the creation wizard,
 * where the client still holds the raw connection config (incl. password) in the
 * form. On the Configuration page the source already exists and secret fields are
 * stripped from API responses — so the client can't supply them. This reads the
 * stored (encrypted) credentials from the DB via the adapter instead.
 *
 * Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
 * ``cdc_slot_name`` (optional), ``cdc_publication_name`` (optional).
 */
export const externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyPrefixMax = 100

export const externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyDescriptionMax = 400

export const externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesCheckCdcPrerequisitesForSourceCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyPrefixMax).nullish(),
        description: zod
            .string()
            .max(externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyDescriptionMax)
            .nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesCreateWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesCreateWebhookCreateBodyDescriptionMax = 400

export const externalDataSourcesCreateWebhookCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesCreateWebhookCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesCreateWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesCreateWebhookCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesCreateWebhookCreateBodyDescriptionMax).nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesCreateWebhookCreateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesCreateWebhookCreateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesDeleteWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesDeleteWebhookCreateBodyDescriptionMax = 400

export const externalDataSourcesDeleteWebhookCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesDeleteWebhookCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesDeleteWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyDescriptionMax).nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesDeleteWebhookCreateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesDeleteWebhookCreateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Read or replace the destinations every table on this source syncs to.
 *
 * A table with its own override ignores this set until the override is cleared.
 */
export const ExternalDataSourcesDestinationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    destination_ids: zod
        .array(zod.uuid())
        .nullish()
        .describe(
            'Destinations to sync to. On a table, null clears the override so the table follows its source again.'
        ),
})

/**
 * Disable CDC on an existing source.
 *
 * Cancels any running CDC extraction workflow, deletes the extraction schedule,
 * delegates engine-side teardown to the source's adapter (drops slot/publication
 * for Postgres; equivalent for other engines), clears ``cdc_*`` keys from
 * ``job_inputs``, soft-deletes companion CDC tables, and sets all CDC schemas to
 * ``sync_type=None``, ``should_sync=False`` so the user must pick a new sync
 * strategy before they resume.
 */
export const externalDataSourcesDisableCdcCreateBodyPrefixMax = 100

export const externalDataSourcesDisableCdcCreateBodyDescriptionMax = 400

export const externalDataSourcesDisableCdcCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesDisableCdcCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesDisableCdcCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesDisableCdcCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesDisableCdcCreateBodyDescriptionMax).nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesDisableCdcCreateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesDisableCdcCreateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Enable CDC on an existing source.
 *
 * Provisions engine-side CDC resources via the source's adapter, writes the CDC
 * config into ``source.job_inputs``, and ensures the CDC extraction schedule
 * exists. Re-runs prereq checks server-side so we never trust a stale
 * client-side check.
 *
 * Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
 * plus engine-specific identifier hints (e.g. ``cdc_slot_name``,
 * ``cdc_publication_name`` for Postgres). Universal tuning fields:
 * ``cdc_auto_drop_slot`` (optional bool), ``cdc_lag_warning_threshold_mb``
 * (optional int), ``cdc_lag_critical_threshold_mb`` (optional int).
 */
export const externalDataSourcesEnableCdcCreateBodyPrefixMax = 100

export const externalDataSourcesEnableCdcCreateBodyDescriptionMax = 400

export const externalDataSourcesEnableCdcCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesEnableCdcCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesEnableCdcCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesEnableCdcCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesEnableCdcCreateBodyDescriptionMax).nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesEnableCdcCreateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesEnableCdcCreateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync).
 */
export const externalDataSourcesRefreshSchemasCreateBodyPrefixMax = 100

export const externalDataSourcesRefreshSchemasCreateBodyDescriptionMax = 400

export const externalDataSourcesRefreshSchemasCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesRefreshSchemasCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesRefreshSchemasCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesRefreshSchemasCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesRefreshSchemasCreateBodyDescriptionMax).nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesRefreshSchemasCreateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesRefreshSchemasCreateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesReloadCreateBodyPrefixMax = 100

export const externalDataSourcesReloadCreateBodyDescriptionMax = 400

export const externalDataSourcesReloadCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesReloadCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesReloadCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesReloadCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesReloadCreateBodyDescriptionMax).nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesReloadCreateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesReloadCreateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyDescriptionMax = 400

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesRevenueAnalyticsConfigPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string().optional(),
        account_id: zod.string().optional(),
        prefix: zod.string().max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyPrefixMax).nullish(),
        description: zod
            .string()
            .max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyDescriptionMax)
            .nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Update CDC tuning fields without enabling/disabling.
 *
 * Lets users edit ``cdc_auto_drop_slot``, ``cdc_lag_warning_threshold_mb``, and
 * ``cdc_lag_critical_threshold_mb`` independently. These fields are universal
 * across engines. Engine-specific identifiers (slot name, management mode, …)
 * are immutable post-enable — switching them requires disable + enable.
 */
export const externalDataSourcesUpdateCdcSettingsCreateBodyPrefixMax = 100

export const externalDataSourcesUpdateCdcSettingsCreateBodyDescriptionMax = 400

export const externalDataSourcesUpdateCdcSettingsCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesUpdateCdcSettingsCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesUpdateCdcSettingsCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateCdcSettingsCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateCdcSettingsCreateBodyDescriptionMax).nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesUpdateCdcSettingsCreateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesUpdateCdcSettingsCreateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax = 100

export const externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax = 400

export const externalDataSourcesUpdateWebhookInputsCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesUpdateWebhookInputsCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesUpdateWebhookInputsCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax).nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesUpdateWebhookInputsCreateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesUpdateWebhookInputsCreateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * List the accounts a source's typed-in credentials can reach, in the shared
 * IntegrationAccount shape.
 *
 * The OAuth twin takes an integration id because the token already lives on the server. Here
 * the credentials are still in the form, so they arrive in the body — POST, not GET, to keep a
 * private key out of the URL and out of anything that logs one. Nothing is cached for the same
 * reason: the cache key would have to include the credentials.
 */
export const ExternalDataSourcesCredentialAccountsCreateBody = /* @__PURE__ */ zod
    .object({
        source_type: zod
            .string()
            .describe("The data warehouse source type whose picker is asking (e.g. 'AppleSearchAds')."),
        credentials: zod
            .record(zod.string(), zod.string())
            .describe(
                "Values of the sibling fields named by the picker's `credentialFields`. Any other key is rejected."
            ),
        api_version: zod
            .string()
            .nullish()
            .describe("Vendor API version the source is pinned to. Defaults to the source's current default."),
    })
    .describe('Body for listing accounts from credentials the user has typed but not yet submitted.')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDatabaseSchemaCreateBody = /* @__PURE__ */ zod
    .object({
        source_type: zod.string().describe('The source type to validate against.'),
    })
    .describe(
        'Validate credentials and preview available tables from a remote database.\n\nThe request body contains source_type plus flat source-specific credential fields\n(e.g. host, port, database, user, password, schema for Postgres). The credential\nfields vary per source_type and are validated dynamically by the source registry.\n\nFor source_type \"Custom\" (a user-defined REST API) the body carries `manifest_json`\n(a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the\ncredential for the manifest\'s declared auth type — `auth_token` (bearer), `auth_api_key`\n(api_key), or `auth_password` (http_basic); keep secrets in these auth_\* keys, never\ninline in manifest_json. The returned tables mirror the manifest\'s resources, with\ndetected primary keys and incremental cursors.'
    )

/**
 * Draft a Custom REST source manifest from API documentation using an LLM.
 *
 * Reads the docs (a URL fetched server-side, or pasted text / OpenAPI spec), asks the model to
 * author a RESTAPIConfig manifest, and validates it against the create-path checks — repairing
 * against validation errors up to a small budget. Returns the manifest for the user to review
 * and tweak in the builder before creating the source; it does NOT create anything. Gated by the
 * `dwh-custom-source-ai-builder` flag, and requires the org to have approved AI data processing,
 * since the docs are sent to the LLM gateway.
 */
export const externalDataSourcesDraftCustomManifestCreateBodySourceNameDefault = ``
export const externalDataSourcesDraftCustomManifestCreateBodyDocsUrlTwoMax = 0

export const ExternalDataSourcesDraftCustomManifestCreateBody = /* @__PURE__ */ zod.object({
    source_name: zod
        .string()
        .default(externalDataSourcesDraftCustomManifestCreateBodySourceNameDefault)
        .describe("Optional human name of the API being connected (e.g. 'Acme CRM'). Used only to orient the model."),
    docs_url: zod
        .union([zod.url(), zod.string().max(externalDataSourcesDraftCustomManifestCreateBodyDocsUrlTwoMax)])
        .optional()
        .describe(
            'URL of the API documentation to read. Provide this or docs_text; fetched server-side via the egress proxy.'
        ),
    docs_text: zod
        .string()
        .optional()
        .describe('Raw API documentation or an OpenAPI\/Swagger spec, pasted directly. Provide this or docs_url.'),
})

/**
 * Read a bounded sample of rows for one resource of a Custom REST source.
 *
 * Lets a manifest author verify `data_selector`, `primary_key`, and the incremental
 * `cursor_path` against live data before creating the source. Only `source_type: "Custom"`
 * is supported — other source types return 400. The read is bounded (single page per
 * resource, capped row count, short timeouts, no redirects). Manifest, validation, and SSRF
 * problems return 400; a live fetch failure returns 200 with `error` set and empty `rows`.
 */
export const externalDataSourcesPreviewResourceCreateBodyLimitDefault = 10
export const externalDataSourcesPreviewResourceCreateBodyLimitMax = 50

export const ExternalDataSourcesPreviewResourceCreateBody = /* @__PURE__ */ zod.object({
    source_type: zod
        .string()
        .describe("The source type to preview. Only 'Custom' (a user-defined REST API) is supported today."),
    payload: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Source config as flat keys. For source_type 'Custom': 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the manifest's declared auth type — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic). Secrets stay in these auth_\* keys, never inline in the manifest."
        ),
    resource_name: zod
        .string()
        .describe(
            'Which manifest resource (table) to read a sample from — one of the resource names in manifest_json.'
        ),
    limit: zod
        .number()
        .min(1)
        .max(externalDataSourcesPreviewResourceCreateBodyLimitMax)
        .default(externalDataSourcesPreviewResourceCreateBodyLimitDefault)
        .describe('Maximum sample rows to return (1–50). Defaults to 10.'),
})

/**
 * One-shot data warehouse source setup.
 *
 * Validate credentials, discover available tables, enable them all with sensible sync defaults
 * (incremental where supported, else append, else full refresh), and create the source in a single
 * call — the caller never has to assemble a `schemas` array. For sources that support webhooks
 * (e.g. Stripe), a webhook is auto-registered after creation: on success webhook-capable tables
 * switch to real-time webhook sync (unlocking webhook-only tables); on failure the polling
 * defaults stay in place. For fine-grained table/sync control, use the lower-level
 * `database_schema` + `create` flow instead.
 */
export const externalDataSourcesSetupCreateBodyPrefixMax = 100

export const externalDataSourcesSetupCreateBodyDescriptionMax = 400

export const externalDataSourcesSetupCreateBodyDirectQueryEnabledDefault = false

export const ExternalDataSourcesSetupCreateBody = /* @__PURE__ */ zod.object({
    source_type: zod.string().describe("The source type to set up (e.g. 'Stripe', 'Postgres', 'Hubspot')."),
    payload: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Connection details as flat keys for the source_type (discover required fields with the wizard tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection details the user stored via the connect-link page (discover ids with the stored_credentials endpoint) — they are merged in server-side and deleted once consumed. An already-connected OAuth integration can be passed via its id key instead (e.g. {'hubspot_integration_id': 123}). For source_type 'Custom' (a user-defined REST API) the keys are 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the auth type the manifest declares — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic); keep secrets in these auth_\* keys, never inline in the manifest. A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible sync defaults."
        ),
    prefix: zod
        .string()
        .max(externalDataSourcesSetupCreateBodyPrefixMax)
        .nullish()
        .describe(
            "Prefix added to the table names PostHog creates in HogQL, e.g. 'stripe' produces stripe_charges. Does not filter which tables are imported. Defaults to the source type."
        ),
    description: zod
        .string()
        .max(externalDataSourcesSetupCreateBodyDescriptionMax)
        .nullish()
        .describe('Human-readable description.'),
    direct_query_enabled: zod
        .boolean()
        .default(externalDataSourcesSetupCreateBodyDirectQueryEnabledDefault)
        .describe(
            'Whether a synced source should also be live-queryable via direct connection. Defaults to false; ignored for pure direct-query sources.'
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesSourcePrefixCreateBodyPrefixMax = 100

export const externalDataSourcesSourcePrefixCreateBodyDescriptionMax = 400

export const externalDataSourcesSourcePrefixCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesSourcePrefixCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesSourcePrefixCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod
                    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
                    .describe(
                        '\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving"
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesSourcePrefixCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesSourcePrefixCreateBodyDescriptionMax).nullish(),
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources.'
            ),
        auto_sync_new_schemas: zod
            .boolean()
            .optional()
            .describe(
                'Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources.'
            ),
        auto_sync_schema_patterns: zod
            .array(
                zod
                    .string()
                    .max(externalDataSourcesSourcePrefixCreateBodyAutoSyncSchemaPatternsItemMax)
                    .describe('An fnmatch-style glob pattern, e.g. `raw_\*`.')
            )
            .max(externalDataSourcesSourcePrefixCreateBodyAutoSyncSchemaPatternsMax)
            .nullish()
            .describe(
                'Optional fnmatch-style globs (`\*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.'
            ),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Validate and store credentials for a data warehouse source without creating the source.
 *
 * Backs the source connect page: the user enters credentials directly in PostHog, they are
 * checked against a live connection, then stashed encrypted in a temporary store. The returned
 * credential id can be passed to `setup` as {'credential_id': <id>} to create the source — so
 * secrets never travel through an agent conversation. The stash is single-use: it is deleted
 * as soon as `setup` consumes it, and expires after 24 hours if never consumed.
 */
export const ExternalDataSourcesStoreCredentialsCreateBody = /* @__PURE__ */ zod.object({
    source_type: zod.string().describe("The source type these credentials are for (e.g. 'Stripe', 'Postgres')."),
    payload: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'Connection details as flat keys for the source_type — the same fields the create flow accepts (host, port, password, API key, …). Checked against a live connection before being stored.'
        ),
})
