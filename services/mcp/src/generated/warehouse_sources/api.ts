/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 46 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

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
                    .enum(['5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day'])
                    .describe(
                        '\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'How often to sync. One of 5min, 15min, 30min, 1hour, 6hour, 12hour, 24hour, 7day or 30day; the fastest is 5 minutes. Common spellings are mapped to these: hourly = 1hour, daily = 24hour, weekly = 7day, monthly = 30day, and durations such as 60min, 1h, 24h, 1day or 1week. To stop a table syncing, set should_sync to false instead.\n\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
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
        copy_access_rules_to_history: zod
            .boolean()
            .optional()
            .describe(
                "When the table keeps history after this update, replace the history table's access rules with the table's own rules. If the history table doesn't exist yet, the rules are copied when its first snapshot loads. Requires the right to manage access to both tables."
            ),
        enabled_columns: zod
            .array(zod.string())
            .nullish()
            .describe(
                'Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.'
            ),
        masked_columns: zod
            .array(zod.string())
            .nullish()
            .describe(
                "Names of source columns whose values are replaced with a deterministic one-way digest at sync time, for sensitive data such as passwords or PII. `null` (default) masks nothing. Primary-key, partition and incremental columns can't be masked, and direct query sources don't support masking. Any change to this list starts a full resync of the table (CDC tables take a new snapshot), or stages it until syncing is turned on. A synced webhook table can't change its masked columns, because its data can't be fetched again."
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
        payload: zod
            .object({
                credential_id: zod
                    .string()
                    .describe(
                        "Id of a stored credential to reconnect this source with. The user enters new connection details on the page that data-warehouse-source-connect-link returns, and the id comes from the stored_credentials list. Only the user who stored the credential can use it, and it must be for this source's source_type and not expired. Its values replace the source's connection details, then the connection is checked. An SSH tunnel or connection host that the user did not enter on the page is not kept. The stored credential is deleted when the update succeeds."
                    ),
            })
            .optional()
            .describe(
                "Update only. Reconnects the source or rotates its credentials with a stored credential, so secrets do not go through the request. Send {'credential_id': '<uuid>'} without job_inputs."
            ),
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
                sync_frequency: zod
                    .string()
                    .nullish()
                    .describe(
                        'How often to sync. One of 5min, 15min, 30min, 1hour, 6hour, 12hour, 24hour, 7day or 30day; the fastest is 5 minutes. Common spellings are mapped to these: hourly = 1hour, daily = 24hour, weekly = 7day, monthly = 30day, and durations such as 60min, 1h, 24h, 1day or 1week. To stop a table syncing, set should_sync to false instead.'
                    ),
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
                masked_columns: zod
                    .array(zod.string())
                    .nullish()
                    .describe(
                        'Columns whose values are replaced with a one-way digest at sync time. Null means mask nothing. Any change starts a full resync of the table.'
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
 * Live CDC health for an existing source: slot/publication existence and WAL lag.
 *
 * Reads from the source DB via the engine adapter. Returns ``{"enabled": false}``
 * when CDC is off, or the stored config plus live ``slot_exists`` /
 * ``publication_exists`` / ``lag_bytes`` when on. 400s if the source DB is
 * unreachable so the UI can show a degraded/unreachable state.
 */
export const ExternalDataSourcesCdcStatusRetrieveParams = () => zod.object({
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
export const ExternalDataSourcesCreateWebhookCreateParams = () => zod.object({
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
export const ExternalDataSourcesDeleteWebhookCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

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
 * Read or replace the destinations every table on this source syncs to.
 *
 * A table with its own override ignores this set until the override is cleared.
 */
export const ExternalDataSourcesDestinationsPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSourcesDestinationsPartialUpdateBody = () => zod.object({
    destination_ids: zod
        .array(zod.string())
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
export const ExternalDataSourcesDisableCdcCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

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
export const ExternalDataSourcesEnableCdcCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSourcesEnableCdcCreateBodyCdcManagementModeDefault = `posthog`

export const ExternalDataSourcesEnableCdcCreateBody = () => zod.object({
    cdc_management_mode: zod
        .enum(['posthog', 'self_managed'])
        .describe('\* `posthog` - PostHog\n\* `self_managed` - Self managed')
        .default(externalDataSourcesEnableCdcCreateBodyCdcManagementModeDefault)
        .describe(
            "Who owns the replication slot and publication. 'posthog' (default) lets PostHog create and drop them, which needs a database user that can manage replication. 'self_managed' expects the customer to have created the publication already; PostHog only creates the slot.\n\n\* `posthog` - PostHog\n\* `self_managed` - Self managed"
        ),
    cdc_slot_name: zod
        .string()
        .optional()
        .describe('Name of the replication slot to use. Defaults to a name derived from the source id.'),
    cdc_publication_name: zod
        .string()
        .optional()
        .describe(
            "Name of the publication to read changes from. Defaults to a name derived from the source id, or 'posthog_pub' in self_managed mode."
        ),
    cdc_auto_drop_slot: zod
        .boolean()
        .optional()
        .describe(
            "Whether PostHog drops the replication slot automatically when lag is critical, to protect the source database disk. Only applies in 'posthog' management mode. Defaults to true."
        ),
    cdc_lag_warning_threshold_mb: zod
        .number()
        .min(1)
        .optional()
        .describe('Replication lag in MB above which a warning shows. Must be lower than the critical threshold.'),
    cdc_lag_critical_threshold_mb: zod
        .number()
        .min(1)
        .optional()
        .describe('Replication lag in MB above which the lag is critical. Must be higher than the warning threshold.'),
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
 * Resume a CDC source whose extraction schedule was paused by a non-retryable
 * failure that left the replication slot intact (bad credentials, SSL/host errors).
 *
 * Once the user has fixed the root cause, this re-probes the source DB — confirming
 * the connection now succeeds and the slot/publication still exist — then unpauses the
 * extraction schedule so streaming resumes from where it left off. No re-snapshot, so
 * it's the cheap counterpart to Repair CDC. If the slot/publication are actually gone
 * (``cdc_broken``, or a live probe showing them missing), resume is refused — only
 * Repair CDC can recreate them, at the cost of a full re-sync.
 */
export const ExternalDataSourcesResumeCdcCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Update CDC tuning fields without enabling/disabling.
 *
 * Lets users edit ``cdc_auto_drop_slot``, ``cdc_lag_warning_threshold_mb``, and
 * ``cdc_lag_critical_threshold_mb`` independently. These fields are universal
 * across engines. Engine-specific identifiers (slot name, management mode, …)
 * are immutable post-enable — switching them requires disable + enable.
 */
export const ExternalDataSourcesUpdateCdcSettingsCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSourcesUpdateCdcSettingsCreateBody = () => zod.object({
    cdc_auto_drop_slot: zod
        .boolean()
        .optional()
        .describe(
            "Whether PostHog drops the replication slot automatically when lag is critical. Only applies in 'posthog' management mode."
        ),
    cdc_lag_warning_threshold_mb: zod
        .number()
        .min(1)
        .optional()
        .describe('Replication lag in MB above which a warning shows. Must be lower than the critical threshold.'),
    cdc_lag_critical_threshold_mb: zod
        .number()
        .min(1)
        .optional()
        .describe('Replication lag in MB above which the lag is critical. Must be higher than the warning threshold.'),
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

export const ExternalDataSourcesUpdateWebhookInputsCreateBody = () => zod.object({
    inputs: zod
        .record(zod.string(), zod.string())
        .describe(
            'Webhook input values keyed by the source\'s declared webhook field names, for example `{\"signing_secret\": \"...\"}`. Only keys the source type declares as webhook fields are accepted, and a required field cannot be blank.'
        ),
})

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
 * Create the planned PostHog source for one migration item, then set its sync schedule.
 */
export const ExternalDataSourcesApplyMigrationItemCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataSourcesApplyMigrationItemCreateBodyPrefixMax = 100

export const ExternalDataSourcesApplyMigrationItemCreateBody = () => zod.object({
    item_id: zod.string().describe('The migration item to create a PostHog source for.'),
    credential_id: zod
        .string()
        .describe("Stored credential from the source connect page, for the item's PostHog source type."),
    prefix: zod
        .string()
        .max(externalDataSourcesApplyMigrationItemCreateBodyPrefixMax)
        .optional()
        .describe('Table name prefix to use instead of the planned one, for example when the planned one is taken.'),
    destination_ids: zod
        .array(zod.string())
        .optional()
        .describe('Destinations to write the new source to. Omit to write to the PostHog warehouse.'),
    table_overrides: zod
        .array(
            zod.object({
                vendor_table: zod
                    .string()
                    .describe(
                        "A Fivetran table from the item: a planned table's `vendor_table`, or one of `unmatched_tables`."
                    ),
                posthog_table: zod
                    .string()
                    .nullable()
                    .describe('The PostHog table to sync it as. Null leaves the table out.'),
            })
        )
        .optional()
        .describe(
            'Changes to the planned tables that the user confirmed: rename an inferred pair, map an unmatched table, or leave a table out.'
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

export const ExternalDataSourcesCheckCdcPrerequisitesCreateBody = () => zod.object({
    source_type: zod
        .string()
        .describe("A CDC-capable source type, for example 'Postgres'. Other source types are rejected."),
    payload: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Connection details as flat keys for the source_type, the same fields the create flow takes in its payload (host, port, database, user, password, schema, ssh_tunnel and so on). Discover them with 'external-data-sources-wizard'. Prefer {'credential_id': <id>} referencing connection details the user stored via the connect-link page: it is merged in server-side and is not consumed by this check, so the same id still works for source setup afterwards."
        ),
    cdc_management_mode: zod
        .string()
        .optional()
        .describe(
            "Who owns the replication slot and publication: 'posthog' (default, PostHog creates them) or 'self_managed' (the user created them)."
        ),
    tables: zod
        .array(zod.string())
        .optional()
        .describe('Tables to check against the publication. Omit to check the database-level prerequisites only.'),
    cdc_slot_name: zod
        .string()
        .nullish()
        .describe("Self-managed replication slot name to check. Ignored in 'posthog' mode."),
    cdc_publication_name: zod
        .string()
        .nullish()
        .describe("Self-managed publication name to check. Ignored in 'posthog' mode."),
})

/**
 * Return a secure browser link for connecting a data warehouse source.
 *
 * The link opens a minimal connect page rendering the source's full connection form — OAuth options
 * included — with no table selection and no source creation. The user authenticates in their browser,
 * secrets never pass through the agent, and the agent finishes setup afterwards by passing the stored
 * credential id to data-warehouse-source-setup. To reconnect an existing source, the agent passes the
 * id in the payload of a source update instead.
 */
export const ExternalDataSourcesConnectLinkRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSourcesConnectLinkRetrieveQueryParams = () => zod.object({
    migration_item_id: zod
        .string()
        .optional()
        .describe(
            "Optional warehouse migration item. The connect page then shows the item's non-secret settings from the vendor, so the user only enters the secret."
        ),
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
            "Connection details as flat keys for the source_type (discover required fields with the wizard tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection details the user stored via the connect-link page (discover ids with the stored_credentials endpoint). Stored credentials work once, expire after 24 hours, are deleted once the source is created, and must be stored for the same source_type. An already-connected OAuth integration can be passed via its id key instead. The key name differs per source and is listed in the wizard output as the source's OAuth field, e.g. {'hubspot_integration_id': 123}, {'google_ads_integration_id': 45} or {'meta_ads_integration_id': 67}. For source_type 'Custom' (a user-defined REST API) the keys are 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the auth type the manifest declares — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic); keep secrets in these auth_\* keys, never inline in the manifest. A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible sync defaults."
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

/**
 * Import a team's Fivetran setup and plan the PostHog sources that replace it.
 */
export const WarehouseMigrationsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseMigrationsListQueryLimitMax = 1000

export const WarehouseMigrationsListQueryParams = () => zod.object({
    limit: zod
        .number()
        .max(warehouseMigrationsListQueryLimitMax)
        .optional()
        .describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Import a team's Fivetran setup and plan the PostHog sources that replace it.
 */
export const warehouseMigrationsRetrievePathIdRegExp = new RegExp(
    '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

export const WarehouseMigrationsRetrieveParams = () => zod.object({
    id: zod.string().regex(warehouseMigrationsRetrievePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Plan vendor connections an agent read, and add them to an uploaded migration.
 */
export const warehouseMigrationsConnectionsCreatePathIdRegExp = new RegExp(
    '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

export const WarehouseMigrationsConnectionsCreateParams = () => zod.object({
    id: zod.string().regex(warehouseMigrationsConnectionsCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseMigrationsConnectionsCreateBodyDestinationsMax = 100

export const warehouseMigrationsConnectionsCreateBodyConnectionsMax = 25

export const WarehouseMigrationsConnectionsCreateBody = () => zod.object({
    account: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('The Fivetran account info response, unchanged. Send it once, with the first upload.'),
    destinations: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .max(warehouseMigrationsConnectionsCreateBodyDestinationsMax)
        .optional()
        .describe(
            "Fivetran destination details responses, unchanged. Send them before the connections that use them, so PostHog reads each connection's sync time in its destination's time zone."
        ),
    connections: zod
        .array(
            zod.object({
                connection: zod
                    .record(zod.string(), zod.unknown())
                    .describe(
                        'The Fivetran connection details response, unchanged. The `code` and `data` envelope may stay.'
                    ),
                schema_config: zod
                    .record(zod.string(), zod.unknown())
                    .nullish()
                    .describe(
                        'The Fivetran schema config response for this connection, unchanged. Null when Fivetran has none.'
                    ),
            })
        )
        .max(warehouseMigrationsConnectionsCreateBodyConnectionsMax)
        .optional()
        .describe(
            'At most 25 connections. A connection uploaded again replaces its plan, unless it is already created in PostHog or skipped.'
        ),
})

/**
 * Estimate the monthly rows and cost of moving the connections, from the usage the user reported.
 */
export const warehouseMigrationsCostEstimateCreatePathIdRegExp = new RegExp(
    '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

export const WarehouseMigrationsCostEstimateCreateParams = () => zod.object({
    id: zod.string().regex(warehouseMigrationsCostEstimateCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseMigrationsCostEstimateCreateBodyUsageItemConnectionNameMax = 400

export const warehouseMigrationsCostEstimateCreateBodyUsageItemMonthlyRowsMin = 0
export const warehouseMigrationsCostEstimateCreateBodyUsageItemMonthlyRowsMax = 2147483647

export const warehouseMigrationsCostEstimateCreateBodyUsageItemDestinationIdMax = 400

export const warehouseMigrationsCostEstimateCreateBodyUsageItemSchemaNameMax = 400

export const warehouseMigrationsCostEstimateCreateBodyUsageItemTableNameMax = 400

export const warehouseMigrationsCostEstimateCreateBodyUsageMax = 10000

export const warehouseMigrationsCostEstimateCreateBodyTableOverridesMax = 10000

export const WarehouseMigrationsCostEstimateCreateBody = () => zod.object({
    usage: zod
        .array(
            zod.object({
                connection_name: zod
                    .string()
                    .max(warehouseMigrationsCostEstimateCreateBodyUsageItemConnectionNameMax)
                    .describe(
                        "The Fivetran connection name, which is also its destination schema. `connection_name` in the Fivetran Platform Connector's `INCREMENTAL_MAR` table."
                    ),
                monthly_rows: zod
                    .number()
                    .min(warehouseMigrationsCostEstimateCreateBodyUsageItemMonthlyRowsMin)
                    .max(warehouseMigrationsCostEstimateCreateBodyUsageItemMonthlyRowsMax)
                    .describe(
                        'Monthly active rows (MAR) Fivetran counted in a typical month, for the table or, without `table_name`, the whole connection.'
                    ),
                destination_id: zod
                    .string()
                    .max(warehouseMigrationsCostEstimateCreateBodyUsageItemDestinationIdMax)
                    .nullish()
                    .describe('The Fivetran destination (group) id. Needed only when two connections share a name.'),
                schema_name: zod
                    .string()
                    .max(warehouseMigrationsCostEstimateCreateBodyUsageItemSchemaNameMax)
                    .nullish()
                    .describe('The destination schema the table lands in, as `schema_name` in `INCREMENTAL_MAR`.'),
                table_name: zod
                    .string()
                    .max(warehouseMigrationsCostEstimateCreateBodyUsageItemTableNameMax)
                    .nullish()
                    .describe('The table. Leave it out when the number covers the whole connection.'),
            })
        )
        .max(warehouseMigrationsCostEstimateCreateBodyUsageMax)
        .optional()
        .describe(
            'Monthly active rows the user reported, per connection or per table. Send it empty to get `usage_query` and the prices before the user has numbers.'
        ),
    table_overrides: zod
        .array(
            zod.object({
                vendor_table: zod
                    .string()
                    .describe(
                        "A Fivetran table from the item: a planned table's `vendor_table`, or one of `unmatched_tables`."
                    ),
                posthog_table: zod
                    .string()
                    .nullable()
                    .describe('The PostHog table to sync it as. Null leaves the table out.'),
                item_id: zod.string().describe('The migration item the table belongs to.'),
            })
        )
        .max(warehouseMigrationsCostEstimateCreateBodyTableOverridesMax)
        .optional()
        .describe(
            "The table choices the user confirmed for apply, so the estimate prices the tables apply creates. Same shape as apply's `table_overrides`, with the item each one belongs to."
        ),
})

/**
 * Import a team's Fivetran setup and plan the PostHog sources that replace it.
 */
export const warehouseMigrationsItemsListPathIdRegExp = new RegExp(
    '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

export const WarehouseMigrationsItemsListParams = () => zod.object({
    id: zod.string().regex(warehouseMigrationsItemsListPathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseMigrationsItemsListQueryLimitMax = 1000

export const WarehouseMigrationsItemsListQueryParams = () => zod.object({
    limit: zod
        .number()
        .max(warehouseMigrationsItemsListQueryLimitMax)
        .optional()
        .describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Import a team's Fivetran setup and plan the PostHog sources that replace it.
 */
export const warehouseMigrationsItemsSkipCreatePathIdRegExp = new RegExp(
    '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

export const WarehouseMigrationsItemsSkipCreateParams = () => zod.object({
    id: zod.string().regex(warehouseMigrationsItemsSkipCreatePathIdRegExp),
    item_id: zod.string().describe('Item ID.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Skip many connections at once, or all but the ones to keep.
 */
export const warehouseMigrationsItemsBulkSkipCreatePathIdRegExp = new RegExp(
    '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

export const WarehouseMigrationsItemsBulkSkipCreateParams = () => zod.object({
    id: zod.string().regex(warehouseMigrationsItemsBulkSkipCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const WarehouseMigrationsItemsBulkSkipCreateBody = () => zod.object({
    item_ids: zod
        .array(zod.string())
        .min(1)
        .optional()
        .describe('Items to skip. Pass this or `keep_item_ids`, not both.'),
    keep_item_ids: zod
        .array(zod.string())
        .optional()
        .describe('Items to keep. Every other item is skipped, for example to migrate only one connection.'),
})

/**
 * Import a team's Fivetran setup and plan the PostHog sources that replace it.
 */
export const warehouseMigrationsRefreshCreatePathIdRegExp = new RegExp(
    '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

export const WarehouseMigrationsRefreshCreateParams = () => zod.object({
    id: zod.string().regex(warehouseMigrationsRefreshCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Import a team's Fivetran setup and plan the PostHog sources that replace it.
 */
export const WarehouseMigrationsConnectLinkRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const WarehouseMigrationsConnectLinkRetrieveQueryParams = () => zod.object({
    provider: zod.enum(['fivetran']).describe('The ETL vendor to import from.\n\n\* `fivetran` - Fivetran'),
})

/**
 * Start a migration that an agent fills with what it reads from the vendor, without a vendor key.
 */
export const WarehouseMigrationsUploadCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const WarehouseMigrationsUploadCreateBody = () => zod.object({
    provider: zod
        .enum(['fivetran'])
        .describe('\* `fivetran` - Fivetran')
        .describe('The ETL vendor to import from.\n\n\* `fivetran` - Fivetran'),
})
