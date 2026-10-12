/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 31 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Manage where warehouse sources write their synced rows.
 *
 * A destination can be attached to several sources, or to a single table on a source.
 * Credentials come from an integration, so one connection can be reused across syncs.
 */
export const ExternalDataDestinationsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataDestinationsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Manage where warehouse sources write their synced rows.
 *
 * A destination can be attached to several sources, or to a single table on a source.
 * Credentials come from an integration, so one connection can be reused across syncs.
 */
export const ExternalDataDestinationsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data destination.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSchemasListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSchemasListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

export const ExternalDataSchemasRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSchemasPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const externalDataSchemasPartialUpdateBodyFullRefreshIntervalDaysMax = 90

export const externalDataSchemasPartialUpdateBodyApiVersionMax = 128

export const ExternalDataSchemasPartialUpdateBody = () => zod
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

export const ExternalDataSchemasCancelCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSchemasDeleteDataDestroyParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Read or replace this table's destination override.
 *
 * Send `destination_ids: null` to clear the override so the table follows its source again.
 */
export const ExternalDataSchemasDestinationsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSchemasIncrementalFieldsCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Trigger a sync for the schema using its configured sync method. Most methods keep the existing warehouse table and add or merge new rows, but a full-refresh schema rebuilds the whole table on every run. To force a rebuild from the source, use resync.
 */
export const ExternalDataSchemasReloadCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Request a full resync of the schema. For sources that can backfill, this drops the warehouse table and re-imports every row from the source, so existing data is deleted first. A webhook-only schema cannot backfill, so it keeps its existing table and resumes ingestion instead. To sync without requesting a rebuild, use reload.
 */
export const ExternalDataSchemasResyncCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSourcesListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSourcesCreateBodyPrefixMax = 100

export const externalDataSourcesCreateBodyDescriptionMax = 400

export const externalDataSourcesCreateBodyAccessMethodDefault = `warehouse`
export const externalDataSourcesCreateBodyDirectQueryEnabledDefault = false

export const ExternalDataSourcesCreateBody = () => zod.object({
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
    direct_query_enabled: zod
        .boolean()
        .default(externalDataSourcesCreateBodyDirectQueryEnabledDefault)
        .describe(
            'Whether a synced source should also be live-queryable via direct connection. Defaults to false; ignored for pure direct-query sources.'
        ),
    destination_ids: zod
        .array(zod.string())
        .optional()
        .describe(
            'Destinations every table on this source writes to. Set here rather than afterwards, so the opening sync already carries them. Omit to write to the PostHog warehouse only.'
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSourcesPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesPartialUpdateBodyDescriptionMax = 400

export const externalDataSourcesPartialUpdateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesPartialUpdateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesPartialUpdateBody = () => zod
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
export const ExternalDataSourcesDestroyParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesBulkUpdateSchemasPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSourcesBulkUpdateSchemasPartialUpdateBodySchemasItemFullRefreshIntervalDaysMax = 90

export const ExternalDataSourcesBulkUpdateSchemasPartialUpdateBody = () => zod.object({
    schemas: zod
        .array(
            zod.object({
                id: zod.string().describe('Schema identifier to update.'),
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
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesCreateWebhookCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSourcesCreateWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesCreateWebhookCreateBodyDescriptionMax = 400

export const externalDataSourcesCreateWebhookCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesCreateWebhookCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesCreateWebhookCreateBody = () => zod
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
export const ExternalDataSourcesDeleteWebhookCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSourcesDeleteWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesDeleteWebhookCreateBodyDescriptionMax = 400

export const externalDataSourcesDeleteWebhookCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesDeleteWebhookCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesDeleteWebhookCreateBody = () => zod
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
export const ExternalDataSourcesDestinationsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync).
 */
export const ExternalDataSourcesRefreshSchemasCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSourcesRefreshSchemasCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesRefreshSchemasCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesRefreshSchemasCreateBody = () => zod
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
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesReloadCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSourcesReloadCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesReloadCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesReloadCreateBody = () => zod
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
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Repair CDC on a source whose replication resources were lost.
 *
 * Only proceeds on evidence of breakage (a persisted broken marker, or a live probe
 * showing the slot/publication missing) — repairing a healthy source would drop its
 * slot and force a full re-sync. Cancels running CDC jobs, recreates the engine-side
 * slot/publication against the stored CDC config, resets every active CDC schema to
 * snapshot mode for a full re-sync (changes since the old slot died are
 * unrecoverable), clears the broken markers, and resumes the paused schedules.
 * Idempotent: safe to retry after a partial failure. Concurrent repairs of the same
 * source are rejected with a 409.
 */
export const ExternalDataSourcesRepairCdcCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesUpdateWebhookInputsCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax = 100

export const externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax = 400

export const externalDataSourcesUpdateWebhookInputsCreateBodyAutoSyncSchemaPatternsItemMax = 250

export const externalDataSourcesUpdateWebhookInputsCreateBodyAutoSyncSchemaPatternsMax = 100

export const ExternalDataSourcesUpdateWebhookInputsCreateBody = () => zod
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
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesWebhookInfoRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Validate CDC prerequisites against a live Postgres connection.
 *
 * Used by the source wizard to surface ✅/❌ checks before source creation,
 * and by the self-managed setup popup to verify user-created publications.
 */
export const ExternalDataSourcesCheckCdcPrerequisitesCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Return a secure browser link for connecting a data warehouse source.
 *
 * The link opens a minimal connect page rendering the source's full connection form — OAuth options
 * included — with no table selection and no source creation. The user authenticates in their browser,
 * secrets never pass through the agent, and the agent finishes setup afterwards by passing the stored
 * credential id to data-warehouse-source-setup.
 */
export const ExternalDataSourcesConnectLinkRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSourcesConnectLinkRetrieveQueryParams = () => zod.object({
    source_type: zod
        .string()
        .describe("The source type to generate a connect link for (e.g. 'Stripe', 'Postgres', 'Hubspot')."),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesConnectionsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
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
export const ExternalDataSourcesSetupCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSourcesSetupCreateBodyPrefixMax = 100

export const externalDataSourcesSetupCreateBodyDescriptionMax = 400

export const externalDataSourcesSetupCreateBodyDirectQueryEnabledDefault = false

export const ExternalDataSourcesSetupCreateBody = () => zod.object({
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
 * List credentials the requesting user stored via the source connect page that haven't been consumed yet.
 *
 * Returns metadata only (id, source type, timestamps) — never the secrets themselves. Stored
 * credentials are scoped to their creator: only the user who filled the connect page can list
 * or consume them. They are temporary too: they disappear once consumed by `setup` or when
 * they expire. Newest first, so after a user confirms they've finished the connect page, the
 * first entry for the source type is the one to pass to `setup`.
 */
export const ExternalDataSourcesStoredCredentialsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSourcesStoredCredentialsListQueryParams = () => zod.object({
    search: zod.string().optional().describe('A search term.'),
    source_type: zod
        .string()
        .optional()
        .describe("Only return stored credentials for this source type (e.g. 'Stripe', 'Postgres')."),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesWizardRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSourcesWizardRetrieveQueryParams = () => zod.object({
    source_type: zod
        .string()
        .optional()
        .describe(
            "Comma-separated source type(s) to return config for, e.g. 'Postgres' or 'Postgres,Stripe'. Strongly recommended: the unfiltered response describes every supported source and is very large. Omit only to enumerate the available types."
        ),
})
