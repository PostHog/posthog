/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 38 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Returns failed/disabled data pipeline items for the Pipeline status side panel.
 * Includes: materializations, syncs, sources, destinations, and transformations.
 */
export const DataWarehouseDataHealthIssuesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

export const ExternalDataSchemasRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasPartialUpdateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'
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
                operator: zod.string().describe('One of: > >= < <= = != IN "NOT IN".'),
                value: zod
                    .unknown()
                    .describe(
                        "Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`)."
                    ),
            })
        )
        .nullish()
        .describe(
            "Predicates ANDed onto the source query so only matching rows sync. Each is `{column, operator, value}`; `null`/empty (default) syncs all rows. The operator must be one of `> >= < <= = != IN \"NOT IN\"` and the value must match the column's type (for `IN`/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). Applied on the next sync — not retroactive to already-synced rows."
        ),
})

export const ExternalDataSchemasCancelCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasCancelCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'
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
                operator: zod.string().describe('One of: > >= < <= = != IN "NOT IN".'),
                value: zod
                    .unknown()
                    .describe(
                        "Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`)."
                    ),
            })
        )
        .nullish()
        .describe(
            "Predicates ANDed onto the source query so only matching rows sync. Each is `{column, operator, value}`; `null`/empty (default) syncs all rows. The operator must be one of `> >= < <= = != IN \"NOT IN\"` and the value must match the column's type (for `IN`/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). Applied on the next sync — not retroactive to already-synced rows."
        ),
})

export const ExternalDataSchemasDeleteDataDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasIncrementalFieldsCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasIncrementalFieldsCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'
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
                operator: zod.string().describe('One of: > >= < <= = != IN "NOT IN".'),
                value: zod
                    .unknown()
                    .describe(
                        "Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`)."
                    ),
            })
        )
        .nullish()
        .describe(
            "Predicates ANDed onto the source query so only matching rows sync. Each is `{column, operator, value}`; `null`/empty (default) syncs all rows. The operator must be one of `> >= < <= = != IN \"NOT IN\"` and the value must match the column's type (for `IN`/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). Applied on the next sync — not retroactive to already-synced rows."
        ),
})

export const ExternalDataSchemasReloadCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasReloadCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'
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
                operator: zod.string().describe('One of: > >= < <= = != IN "NOT IN".'),
                value: zod
                    .unknown()
                    .describe(
                        "Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`)."
                    ),
            })
        )
        .nullish()
        .describe(
            "Predicates ANDed onto the source query so only matching rows sync. Each is `{column, operator, value}`; `null`/empty (default) syncs all rows. The operator must be one of `> >= < <= = != IN \"NOT IN\"` and the value must match the column's type (for `IN`/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). Applied on the next sync — not retroactive to already-synced rows."
        ),
})

export const ExternalDataSchemasResyncCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasResyncCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'
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
                operator: zod.string().describe('One of: > >= < <= = != IN "NOT IN".'),
                value: zod
                    .unknown()
                    .describe(
                        "Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`)."
                    ),
            })
        )
        .nullish()
        .describe(
            "Predicates ANDed onto the source query so only matching rows sync. Each is `{column, operator, value}`; `null`/empty (default) syncs all rows. The operator must be one of `> >= < <= = != IN \"NOT IN\"` and the value must match the column's type (for `IN`/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). Applied on the next sync — not retroactive to already-synced rows."
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSourcesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesCreateBodyPrefixMax = 100

export const externalDataSourcesCreateBodyDescriptionMax = 400

export const externalDataSourcesCreateBodyAccessMethodDefault = `warehouse`

export const ExternalDataSourcesCreateBody = /* @__PURE__ */ zod.object({
    source_type: zod
        .enum([
            'Ashby',
            'Supabase',
            'CustomerIO',
            'Github',
            'Stripe',
            'Hubspot',
            'Postgres',
            'Zendesk',
            'Snowflake',
            'Salesforce',
            'MySQL',
            'MongoDB',
            'MSSQL',
            'Vitally',
            'BigQuery',
            'Chargebee',
            'Clerk',
            'GoogleAds',
            'GoogleSearchConsole',
            'TemporalIO',
            'DoIt',
            'GoogleSheets',
            'MetaAds',
            'Klaviyo',
            'Mailchimp',
            'Braze',
            'Mailjet',
            'Redshift',
            'Polar',
            'RevenueCat',
            'LinkedinAds',
            'RedditAds',
            'TikTokAds',
            'BingAds',
            'Shopify',
            'Attio',
            'SnapchatAds',
            'Linear',
            'Intercom',
            'Amplitude',
            'Mixpanel',
            'Jira',
            'ActiveCampaign',
            'Marketo',
            'Adjust',
            'AppsFlyer',
            'Freshdesk',
            'GoogleAnalytics',
            'Pipedrive',
            'SendGrid',
            'Slack',
            'PagerDuty',
            'Asana',
            'Notion',
            'Airtable',
            'Greenhouse',
            'BambooHR',
            'Lever',
            'GitLab',
            'Datadog',
            'Sentry',
            'Pendo',
            'FullStory',
            'AmazonAds',
            'PinterestAds',
            'AppleSearchAds',
            'QuickBooks',
            'Xero',
            'NetSuite',
            'WooCommerce',
            'BigCommerce',
            'PayPal',
            'Square',
            'Zoom',
            'Trello',
            'Monday',
            'ClickUp',
            'Confluence',
            'Recurly',
            'SalesLoft',
            'Outreach',
            'Gong',
            'Calendly',
            'Typeform',
            'Iterable',
            'ZohoCRM',
            'Close',
            'Oracle',
            'DynamoDB',
            'Elasticsearch',
            'Kafka',
            'LaunchDarkly',
            'Braintree',
            'Recharge',
            'HelpScout',
            'Gorgias',
            'Instagram',
            'YouTubeAnalytics',
            'FacebookPages',
            'TwitterAds',
            'Workday',
            'ServiceNow',
            'Pardot',
            'Copper',
            'Front',
            'ChartMogul',
            'Zuora',
            'Paddle',
            'CircleCI',
            'CockroachDB',
            'Firebase',
            'AzureBlob',
            'GoogleDrive',
            'OneDrive',
            'SharePoint',
            'Box',
            'SFTP',
            'MicrosoftTeams',
            'Aircall',
            'Webflow',
            'Okta',
            'Auth0',
            'Productboard',
            'Smartsheet',
            'Wrike',
            'Plaid',
            'SurveyMonkey',
            'Eventbrite',
            'RingCentral',
            'Twilio',
            'Freshsales',
            'Shortcut',
            'ConvertKit',
            'Drip',
            'CampaignMonitor',
            'MailerLite',
            'Omnisend',
            'Brevo',
            'Postmark',
            'Granola',
            'BuildBetter',
            'Convex',
            'ClickHouse',
            'Plain',
            'Resend',
            'PgAnalyze',
            'WorkOS',
            'AmazonS3',
            'GoogleCloudStorage',
            'Databricks',
            'Dynamics365',
            'SalesforceMarketingCloud',
            'Db2',
            'Heap',
            'AdobeAnalytics',
            'Matomo',
            'Optimizely',
            'Adyen',
            'GoCardless',
            'Mollie',
            'CheckoutCom',
            'Branch',
            'Criteo',
            'Outbrain',
            'Taboola',
            'AdRoll',
            'DisplayVideo360',
            'GoogleAdManager',
            'CampaignManager360',
            'SearchAds360',
            'AdobeCommerce',
            'AmazonSellingPartner',
            'Ebay',
            'Commercetools',
            'LightspeedRetail',
            'ShipStation',
            'ConstantContact',
            'Mailgun',
            'Eloqua',
            'Sailthru',
            'Ortto',
            'Attentive',
            'Kustomer',
            'Dixa',
            'Gladly',
            'Qualtrics',
            'Delighted',
            'AzureDevOps',
            'Rollbar',
            'Opsgenie',
            'IncidentIo',
            'Pingdom',
            'Cloudflare',
            'CosmosDB',
            'PlanetScale',
            'SapHana',
            'Rippling',
            'HiBob',
            'Personio',
            'Deel',
            'AdpWorkforceNow',
            'Paylocity',
            'Gusto',
            'CultureAmp',
            'Lattice',
            'SageIntacct',
            'FreshBooks',
            'Expensify',
            'Ramp',
            'Brex',
            'Coupa',
            'SapConcur',
            'Apollo',
            'Crunchbase',
            'ZoomInfo',
            'Clari',
            'Chorus',
            'Coda',
            'Guru',
            'Dropbox',
            'Docusign',
            'PandaDoc',
            'SapErp',
            'SapSuccessFactors',
            'OracleEbs',
            'OracleFusion',
            'AmazonSNS',
            'AmazonEventBridge',
            'AmazonSQS',
            'AmazonKinesis',
            'AmazonCloudWatch',
            'OpenAIAds',
            'Custom',
        ])
        .describe(
            '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `GoogleSearchConsole` - GoogleSearchConsole\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex\n* `ClickHouse` - ClickHouse\n* `Plain` - Plain\n* `Resend` - Resend\n* `PgAnalyze` - PgAnalyze\n* `WorkOS` - WorkOS\n* `AmazonS3` - AmazonS3\n* `GoogleCloudStorage` - GoogleCloudStorage\n* `Databricks` - Databricks\n* `Dynamics365` - Dynamics365\n* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n* `Db2` - Db2\n* `Heap` - Heap\n* `AdobeAnalytics` - AdobeAnalytics\n* `Matomo` - Matomo\n* `Optimizely` - Optimizely\n* `Adyen` - Adyen\n* `GoCardless` - GoCardless\n* `Mollie` - Mollie\n* `CheckoutCom` - CheckoutCom\n* `Branch` - Branch\n* `Criteo` - Criteo\n* `Outbrain` - Outbrain\n* `Taboola` - Taboola\n* `AdRoll` - AdRoll\n* `DisplayVideo360` - DisplayVideo360\n* `GoogleAdManager` - GoogleAdManager\n* `CampaignManager360` - CampaignManager360\n* `SearchAds360` - SearchAds360\n* `AdobeCommerce` - AdobeCommerce\n* `AmazonSellingPartner` - AmazonSellingPartner\n* `Ebay` - Ebay\n* `Commercetools` - Commercetools\n* `LightspeedRetail` - LightspeedRetail\n* `ShipStation` - ShipStation\n* `ConstantContact` - ConstantContact\n* `Mailgun` - Mailgun\n* `Eloqua` - Eloqua\n* `Sailthru` - Sailthru\n* `Ortto` - Ortto\n* `Attentive` - Attentive\n* `Kustomer` - Kustomer\n* `Dixa` - Dixa\n* `Gladly` - Gladly\n* `Qualtrics` - Qualtrics\n* `Delighted` - Delighted\n* `AzureDevOps` - AzureDevOps\n* `Rollbar` - Rollbar\n* `Opsgenie` - Opsgenie\n* `IncidentIo` - IncidentIo\n* `Pingdom` - Pingdom\n* `Cloudflare` - Cloudflare\n* `CosmosDB` - CosmosDB\n* `PlanetScale` - PlanetScale\n* `SapHana` - SapHana\n* `Rippling` - Rippling\n* `HiBob` - HiBob\n* `Personio` - Personio\n* `Deel` - Deel\n* `AdpWorkforceNow` - AdpWorkforceNow\n* `Paylocity` - Paylocity\n* `Gusto` - Gusto\n* `CultureAmp` - CultureAmp\n* `Lattice` - Lattice\n* `SageIntacct` - SageIntacct\n* `FreshBooks` - FreshBooks\n* `Expensify` - Expensify\n* `Ramp` - Ramp\n* `Brex` - Brex\n* `Coupa` - Coupa\n* `SapConcur` - SapConcur\n* `Apollo` - Apollo\n* `Crunchbase` - Crunchbase\n* `ZoomInfo` - ZoomInfo\n* `Clari` - Clari\n* `Chorus` - Chorus\n* `Coda` - Coda\n* `Guru` - Guru\n* `Dropbox` - Dropbox\n* `Docusign` - Docusign\n* `PandaDoc` - PandaDoc\n* `SapErp` - SapErp\n* `SapSuccessFactors` - SapSuccessFactors\n* `OracleEbs` - OracleEbs\n* `OracleFusion` - OracleFusion\n* `AmazonSNS` - AmazonSNS\n* `AmazonEventBridge` - AmazonEventBridge\n* `AmazonSQS` - AmazonSQS\n* `AmazonKinesis` - AmazonKinesis\n* `AmazonCloudWatch` - AmazonCloudWatch\n* `OpenAIAds` - OpenAIAds\n* `Custom` - Custom'
        )
        .describe(
            "The source type (e.g. 'Postgres', 'Stripe').\n\n* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `GoogleSearchConsole` - GoogleSearchConsole\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex\n* `ClickHouse` - ClickHouse\n* `Plain` - Plain\n* `Resend` - Resend\n* `PgAnalyze` - PgAnalyze\n* `WorkOS` - WorkOS\n* `AmazonS3` - AmazonS3\n* `GoogleCloudStorage` - GoogleCloudStorage\n* `Databricks` - Databricks\n* `Dynamics365` - Dynamics365\n* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n* `Db2` - Db2\n* `Heap` - Heap\n* `AdobeAnalytics` - AdobeAnalytics\n* `Matomo` - Matomo\n* `Optimizely` - Optimizely\n* `Adyen` - Adyen\n* `GoCardless` - GoCardless\n* `Mollie` - Mollie\n* `CheckoutCom` - CheckoutCom\n* `Branch` - Branch\n* `Criteo` - Criteo\n* `Outbrain` - Outbrain\n* `Taboola` - Taboola\n* `AdRoll` - AdRoll\n* `DisplayVideo360` - DisplayVideo360\n* `GoogleAdManager` - GoogleAdManager\n* `CampaignManager360` - CampaignManager360\n* `SearchAds360` - SearchAds360\n* `AdobeCommerce` - AdobeCommerce\n* `AmazonSellingPartner` - AmazonSellingPartner\n* `Ebay` - Ebay\n* `Commercetools` - Commercetools\n* `LightspeedRetail` - LightspeedRetail\n* `ShipStation` - ShipStation\n* `ConstantContact` - ConstantContact\n* `Mailgun` - Mailgun\n* `Eloqua` - Eloqua\n* `Sailthru` - Sailthru\n* `Ortto` - Ortto\n* `Attentive` - Attentive\n* `Kustomer` - Kustomer\n* `Dixa` - Dixa\n* `Gladly` - Gladly\n* `Qualtrics` - Qualtrics\n* `Delighted` - Delighted\n* `AzureDevOps` - AzureDevOps\n* `Rollbar` - Rollbar\n* `Opsgenie` - Opsgenie\n* `IncidentIo` - IncidentIo\n* `Pingdom` - Pingdom\n* `Cloudflare` - Cloudflare\n* `CosmosDB` - CosmosDB\n* `PlanetScale` - PlanetScale\n* `SapHana` - SapHana\n* `Rippling` - Rippling\n* `HiBob` - HiBob\n* `Personio` - Personio\n* `Deel` - Deel\n* `AdpWorkforceNow` - AdpWorkforceNow\n* `Paylocity` - Paylocity\n* `Gusto` - Gusto\n* `CultureAmp` - CultureAmp\n* `Lattice` - Lattice\n* `SageIntacct` - SageIntacct\n* `FreshBooks` - FreshBooks\n* `Expensify` - Expensify\n* `Ramp` - Ramp\n* `Brex` - Brex\n* `Coupa` - Coupa\n* `SapConcur` - SapConcur\n* `Apollo` - Apollo\n* `Crunchbase` - Crunchbase\n* `ZoomInfo` - ZoomInfo\n* `Clari` - Clari\n* `Chorus` - Chorus\n* `Coda` - Coda\n* `Guru` - Guru\n* `Dropbox` - Dropbox\n* `Docusign` - Docusign\n* `PandaDoc` - PandaDoc\n* `SapErp` - SapErp\n* `SapSuccessFactors` - SapSuccessFactors\n* `OracleEbs` - OracleEbs\n* `OracleFusion` - OracleFusion\n* `AmazonSNS` - AmazonSNS\n* `AmazonEventBridge` - AmazonEventBridge\n* `AmazonSQS` - AmazonSQS\n* `AmazonKinesis` - AmazonKinesis\n* `AmazonCloudWatch` - AmazonCloudWatch\n* `OpenAIAds` - OpenAIAds\n* `Custom` - Custom"
        ),
    payload: zod
        .record(zod.string(), zod.unknown())
        .describe("Connection credentials and a 'schemas' array. Keys depend on source_type."),
    prefix: zod.string().max(externalDataSourcesCreateBodyPrefixMax).nullish().describe('Table name prefix in HogQL.'),
    description: zod
        .string()
        .max(externalDataSourcesCreateBodyDescriptionMax)
        .nullish()
        .describe('Human-readable description.'),
    access_method: zod
        .enum(['warehouse', 'direct'])
        .describe('* `warehouse` - warehouse\n* `direct` - direct')
        .default(externalDataSourcesCreateBodyAccessMethodDefault)
        .describe(
            "Connection mode: 'warehouse' (import) or 'direct' (live query).\n\n* `warehouse` - warehouse\n* `direct` - direct"
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesPartialUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('* `web` - web\n* `api` - api\n* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls. Ignored on update.\n\n* `web` - web\n* `api` - api\n* `mcp` - mcp'
            ),
        client_secret: zod.string().optional(),
        account_id: zod.string().optional(),
        prefix: zod.string().max(externalDataSourcesPartialUpdateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesPartialUpdateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesCreateWebhookCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesCreateWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesCreateWebhookCreateBodyDescriptionMax = 400

export const ExternalDataSourcesCreateWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('* `web` - web\n* `api` - api\n* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls. Ignored on update.\n\n* `web` - web\n* `api` - api\n* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesCreateWebhookCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesCreateWebhookCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDeleteWebhookCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesDeleteWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesDeleteWebhookCreateBodyDescriptionMax = 400

export const ExternalDataSourcesDeleteWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('* `web` - web\n* `api` - api\n* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls. Ignored on update.\n\n* `web` - web\n* `api` - api\n* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync).
 */
export const ExternalDataSourcesRefreshSchemasCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSourcesRefreshSchemasCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('* `web` - web\n* `api` - api\n* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls. Ignored on update.\n\n* `web` - web\n* `api` - api\n* `mcp` - mcp'
            ),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesReloadCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSourcesReloadCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('* `web` - web\n* `api` - api\n* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls. Ignored on update.\n\n* `web` - web\n* `api` - api\n* `mcp` - mcp'
            ),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesUpdateWebhookInputsCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax = 100

export const externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax = 400

export const ExternalDataSourcesUpdateWebhookInputsCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('* `web` - web\n* `api` - api\n* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls. Ignored on update.\n\n* `web` - web\n* `api` - api\n* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesWebhookInfoRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Validate CDC prerequisites against a live Postgres connection.
 *
 * Used by the source wizard to surface ✅/❌ checks before source creation,
 * and by the self-managed setup popup to verify user-created publications.
 */
export const ExternalDataSourcesCheckCdcPrerequisitesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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
export const ExternalDataSourcesConnectLinkRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSourcesConnectLinkRetrieveQueryParams = /* @__PURE__ */ zod.object({
    source_type: zod
        .string()
        .describe("The source type to generate a connect link for (e.g. 'Stripe', 'Postgres', 'Hubspot')."),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesConnectionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSourcesConnectionsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
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
export const ExternalDataSourcesSetupCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesSetupCreateBodyPrefixMax = 100

export const externalDataSourcesSetupCreateBodyDescriptionMax = 400

export const ExternalDataSourcesSetupCreateBody = /* @__PURE__ */ zod.object({
    source_type: zod
        .enum([
            'Ashby',
            'Supabase',
            'CustomerIO',
            'Github',
            'Stripe',
            'Hubspot',
            'Postgres',
            'Zendesk',
            'Snowflake',
            'Salesforce',
            'MySQL',
            'MongoDB',
            'MSSQL',
            'Vitally',
            'BigQuery',
            'Chargebee',
            'Clerk',
            'GoogleAds',
            'GoogleSearchConsole',
            'TemporalIO',
            'DoIt',
            'GoogleSheets',
            'MetaAds',
            'Klaviyo',
            'Mailchimp',
            'Braze',
            'Mailjet',
            'Redshift',
            'Polar',
            'RevenueCat',
            'LinkedinAds',
            'RedditAds',
            'TikTokAds',
            'BingAds',
            'Shopify',
            'Attio',
            'SnapchatAds',
            'Linear',
            'Intercom',
            'Amplitude',
            'Mixpanel',
            'Jira',
            'ActiveCampaign',
            'Marketo',
            'Adjust',
            'AppsFlyer',
            'Freshdesk',
            'GoogleAnalytics',
            'Pipedrive',
            'SendGrid',
            'Slack',
            'PagerDuty',
            'Asana',
            'Notion',
            'Airtable',
            'Greenhouse',
            'BambooHR',
            'Lever',
            'GitLab',
            'Datadog',
            'Sentry',
            'Pendo',
            'FullStory',
            'AmazonAds',
            'PinterestAds',
            'AppleSearchAds',
            'QuickBooks',
            'Xero',
            'NetSuite',
            'WooCommerce',
            'BigCommerce',
            'PayPal',
            'Square',
            'Zoom',
            'Trello',
            'Monday',
            'ClickUp',
            'Confluence',
            'Recurly',
            'SalesLoft',
            'Outreach',
            'Gong',
            'Calendly',
            'Typeform',
            'Iterable',
            'ZohoCRM',
            'Close',
            'Oracle',
            'DynamoDB',
            'Elasticsearch',
            'Kafka',
            'LaunchDarkly',
            'Braintree',
            'Recharge',
            'HelpScout',
            'Gorgias',
            'Instagram',
            'YouTubeAnalytics',
            'FacebookPages',
            'TwitterAds',
            'Workday',
            'ServiceNow',
            'Pardot',
            'Copper',
            'Front',
            'ChartMogul',
            'Zuora',
            'Paddle',
            'CircleCI',
            'CockroachDB',
            'Firebase',
            'AzureBlob',
            'GoogleDrive',
            'OneDrive',
            'SharePoint',
            'Box',
            'SFTP',
            'MicrosoftTeams',
            'Aircall',
            'Webflow',
            'Okta',
            'Auth0',
            'Productboard',
            'Smartsheet',
            'Wrike',
            'Plaid',
            'SurveyMonkey',
            'Eventbrite',
            'RingCentral',
            'Twilio',
            'Freshsales',
            'Shortcut',
            'ConvertKit',
            'Drip',
            'CampaignMonitor',
            'MailerLite',
            'Omnisend',
            'Brevo',
            'Postmark',
            'Granola',
            'BuildBetter',
            'Convex',
            'ClickHouse',
            'Plain',
            'Resend',
            'PgAnalyze',
            'WorkOS',
            'AmazonS3',
            'GoogleCloudStorage',
            'Databricks',
            'Dynamics365',
            'SalesforceMarketingCloud',
            'Db2',
            'Heap',
            'AdobeAnalytics',
            'Matomo',
            'Optimizely',
            'Adyen',
            'GoCardless',
            'Mollie',
            'CheckoutCom',
            'Branch',
            'Criteo',
            'Outbrain',
            'Taboola',
            'AdRoll',
            'DisplayVideo360',
            'GoogleAdManager',
            'CampaignManager360',
            'SearchAds360',
            'AdobeCommerce',
            'AmazonSellingPartner',
            'Ebay',
            'Commercetools',
            'LightspeedRetail',
            'ShipStation',
            'ConstantContact',
            'Mailgun',
            'Eloqua',
            'Sailthru',
            'Ortto',
            'Attentive',
            'Kustomer',
            'Dixa',
            'Gladly',
            'Qualtrics',
            'Delighted',
            'AzureDevOps',
            'Rollbar',
            'Opsgenie',
            'IncidentIo',
            'Pingdom',
            'Cloudflare',
            'CosmosDB',
            'PlanetScale',
            'SapHana',
            'Rippling',
            'HiBob',
            'Personio',
            'Deel',
            'AdpWorkforceNow',
            'Paylocity',
            'Gusto',
            'CultureAmp',
            'Lattice',
            'SageIntacct',
            'FreshBooks',
            'Expensify',
            'Ramp',
            'Brex',
            'Coupa',
            'SapConcur',
            'Apollo',
            'Crunchbase',
            'ZoomInfo',
            'Clari',
            'Chorus',
            'Coda',
            'Guru',
            'Dropbox',
            'Docusign',
            'PandaDoc',
            'SapErp',
            'SapSuccessFactors',
            'OracleEbs',
            'OracleFusion',
            'AmazonSNS',
            'AmazonEventBridge',
            'AmazonSQS',
            'AmazonKinesis',
            'AmazonCloudWatch',
            'OpenAIAds',
            'Custom',
        ])
        .describe(
            '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `GoogleSearchConsole` - GoogleSearchConsole\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex\n* `ClickHouse` - ClickHouse\n* `Plain` - Plain\n* `Resend` - Resend\n* `PgAnalyze` - PgAnalyze\n* `WorkOS` - WorkOS\n* `AmazonS3` - AmazonS3\n* `GoogleCloudStorage` - GoogleCloudStorage\n* `Databricks` - Databricks\n* `Dynamics365` - Dynamics365\n* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n* `Db2` - Db2\n* `Heap` - Heap\n* `AdobeAnalytics` - AdobeAnalytics\n* `Matomo` - Matomo\n* `Optimizely` - Optimizely\n* `Adyen` - Adyen\n* `GoCardless` - GoCardless\n* `Mollie` - Mollie\n* `CheckoutCom` - CheckoutCom\n* `Branch` - Branch\n* `Criteo` - Criteo\n* `Outbrain` - Outbrain\n* `Taboola` - Taboola\n* `AdRoll` - AdRoll\n* `DisplayVideo360` - DisplayVideo360\n* `GoogleAdManager` - GoogleAdManager\n* `CampaignManager360` - CampaignManager360\n* `SearchAds360` - SearchAds360\n* `AdobeCommerce` - AdobeCommerce\n* `AmazonSellingPartner` - AmazonSellingPartner\n* `Ebay` - Ebay\n* `Commercetools` - Commercetools\n* `LightspeedRetail` - LightspeedRetail\n* `ShipStation` - ShipStation\n* `ConstantContact` - ConstantContact\n* `Mailgun` - Mailgun\n* `Eloqua` - Eloqua\n* `Sailthru` - Sailthru\n* `Ortto` - Ortto\n* `Attentive` - Attentive\n* `Kustomer` - Kustomer\n* `Dixa` - Dixa\n* `Gladly` - Gladly\n* `Qualtrics` - Qualtrics\n* `Delighted` - Delighted\n* `AzureDevOps` - AzureDevOps\n* `Rollbar` - Rollbar\n* `Opsgenie` - Opsgenie\n* `IncidentIo` - IncidentIo\n* `Pingdom` - Pingdom\n* `Cloudflare` - Cloudflare\n* `CosmosDB` - CosmosDB\n* `PlanetScale` - PlanetScale\n* `SapHana` - SapHana\n* `Rippling` - Rippling\n* `HiBob` - HiBob\n* `Personio` - Personio\n* `Deel` - Deel\n* `AdpWorkforceNow` - AdpWorkforceNow\n* `Paylocity` - Paylocity\n* `Gusto` - Gusto\n* `CultureAmp` - CultureAmp\n* `Lattice` - Lattice\n* `SageIntacct` - SageIntacct\n* `FreshBooks` - FreshBooks\n* `Expensify` - Expensify\n* `Ramp` - Ramp\n* `Brex` - Brex\n* `Coupa` - Coupa\n* `SapConcur` - SapConcur\n* `Apollo` - Apollo\n* `Crunchbase` - Crunchbase\n* `ZoomInfo` - ZoomInfo\n* `Clari` - Clari\n* `Chorus` - Chorus\n* `Coda` - Coda\n* `Guru` - Guru\n* `Dropbox` - Dropbox\n* `Docusign` - Docusign\n* `PandaDoc` - PandaDoc\n* `SapErp` - SapErp\n* `SapSuccessFactors` - SapSuccessFactors\n* `OracleEbs` - OracleEbs\n* `OracleFusion` - OracleFusion\n* `AmazonSNS` - AmazonSNS\n* `AmazonEventBridge` - AmazonEventBridge\n* `AmazonSQS` - AmazonSQS\n* `AmazonKinesis` - AmazonKinesis\n* `AmazonCloudWatch` - AmazonCloudWatch\n* `OpenAIAds` - OpenAIAds\n* `Custom` - Custom'
        )
        .describe(
            "The source type to set up (e.g. 'Stripe', 'Postgres', 'Hubspot').\n\n* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `GoogleSearchConsole` - GoogleSearchConsole\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex\n* `ClickHouse` - ClickHouse\n* `Plain` - Plain\n* `Resend` - Resend\n* `PgAnalyze` - PgAnalyze\n* `WorkOS` - WorkOS\n* `AmazonS3` - AmazonS3\n* `GoogleCloudStorage` - GoogleCloudStorage\n* `Databricks` - Databricks\n* `Dynamics365` - Dynamics365\n* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n* `Db2` - Db2\n* `Heap` - Heap\n* `AdobeAnalytics` - AdobeAnalytics\n* `Matomo` - Matomo\n* `Optimizely` - Optimizely\n* `Adyen` - Adyen\n* `GoCardless` - GoCardless\n* `Mollie` - Mollie\n* `CheckoutCom` - CheckoutCom\n* `Branch` - Branch\n* `Criteo` - Criteo\n* `Outbrain` - Outbrain\n* `Taboola` - Taboola\n* `AdRoll` - AdRoll\n* `DisplayVideo360` - DisplayVideo360\n* `GoogleAdManager` - GoogleAdManager\n* `CampaignManager360` - CampaignManager360\n* `SearchAds360` - SearchAds360\n* `AdobeCommerce` - AdobeCommerce\n* `AmazonSellingPartner` - AmazonSellingPartner\n* `Ebay` - Ebay\n* `Commercetools` - Commercetools\n* `LightspeedRetail` - LightspeedRetail\n* `ShipStation` - ShipStation\n* `ConstantContact` - ConstantContact\n* `Mailgun` - Mailgun\n* `Eloqua` - Eloqua\n* `Sailthru` - Sailthru\n* `Ortto` - Ortto\n* `Attentive` - Attentive\n* `Kustomer` - Kustomer\n* `Dixa` - Dixa\n* `Gladly` - Gladly\n* `Qualtrics` - Qualtrics\n* `Delighted` - Delighted\n* `AzureDevOps` - AzureDevOps\n* `Rollbar` - Rollbar\n* `Opsgenie` - Opsgenie\n* `IncidentIo` - IncidentIo\n* `Pingdom` - Pingdom\n* `Cloudflare` - Cloudflare\n* `CosmosDB` - CosmosDB\n* `PlanetScale` - PlanetScale\n* `SapHana` - SapHana\n* `Rippling` - Rippling\n* `HiBob` - HiBob\n* `Personio` - Personio\n* `Deel` - Deel\n* `AdpWorkforceNow` - AdpWorkforceNow\n* `Paylocity` - Paylocity\n* `Gusto` - Gusto\n* `CultureAmp` - CultureAmp\n* `Lattice` - Lattice\n* `SageIntacct` - SageIntacct\n* `FreshBooks` - FreshBooks\n* `Expensify` - Expensify\n* `Ramp` - Ramp\n* `Brex` - Brex\n* `Coupa` - Coupa\n* `SapConcur` - SapConcur\n* `Apollo` - Apollo\n* `Crunchbase` - Crunchbase\n* `ZoomInfo` - ZoomInfo\n* `Clari` - Clari\n* `Chorus` - Chorus\n* `Coda` - Coda\n* `Guru` - Guru\n* `Dropbox` - Dropbox\n* `Docusign` - Docusign\n* `PandaDoc` - PandaDoc\n* `SapErp` - SapErp\n* `SapSuccessFactors` - SapSuccessFactors\n* `OracleEbs` - OracleEbs\n* `OracleFusion` - OracleFusion\n* `AmazonSNS` - AmazonSNS\n* `AmazonEventBridge` - AmazonEventBridge\n* `AmazonSQS` - AmazonSQS\n* `AmazonKinesis` - AmazonKinesis\n* `AmazonCloudWatch` - AmazonCloudWatch\n* `OpenAIAds` - OpenAIAds\n* `Custom` - Custom"
        ),
    payload: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Connection details as flat keys for the source_type (discover required fields with the wizard tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection details the user stored via the connect-link page (discover ids with the stored_credentials endpoint) — they are merged in server-side and deleted once consumed. An already-connected OAuth integration can be passed via its id key instead (e.g. {'hubspot_integration_id': 123}). A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible sync defaults."
        ),
    prefix: zod
        .string()
        .max(externalDataSourcesSetupCreateBodyPrefixMax)
        .nullish()
        .describe("Table name prefix in HogQL, e.g. 'stripe' produces stripe_charges. Defaults to the source type."),
    description: zod
        .string()
        .max(externalDataSourcesSetupCreateBodyDescriptionMax)
        .nullish()
        .describe('Human-readable description.'),
})

/**
 * List credentials stored via the source connect page that haven't been consumed yet.
 *
 * Returns metadata only (id, source type, timestamps) — never the secrets themselves. Stored
 * credentials are temporary: they disappear once consumed by `setup` or when they expire.
 * Newest first, so after a user confirms they've finished the connect page, the first entry
 * for the source type is the one to pass to `setup`.
 */
export const ExternalDataSourcesStoredCredentialsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSourcesStoredCredentialsListQueryParams = /* @__PURE__ */ zod.object({
    search: zod.string().optional().describe('A search term.'),
    source_type: zod
        .string()
        .optional()
        .describe("Only return stored credentials for this source type (e.g. 'Stripe', 'Postgres')."),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesWizardRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const InsightVariablesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const insightVariablesCreateBodyNameMax = 400

export const InsightVariablesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(insightVariablesCreateBodyNameMax).describe('Human-readable name for the SQL variable.'),
    type: zod
        .enum(['String', 'Number', 'Boolean', 'List', 'Date'])
        .describe('* `String` - String\n* `Number` - Number\n* `Boolean` - Boolean\n* `List` - List\n* `Date` - Date')
        .describe(
            'Variable type. Controls how the value is rendered and substituted in HogQL.\n\n* `String` - String\n* `Number` - Number\n* `Boolean` - Boolean\n* `List` - List\n* `Date` - Date'
        ),
    default_value: zod.unknown().optional().describe('Default value used when a query references this variable.'),
    values: zod.unknown().optional().describe('Allowed values for List variables. Null for other variable types.'),
})

export const InsightVariablesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this insight variable.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const insightVariablesPartialUpdateBodyNameMax = 400

export const InsightVariablesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(insightVariablesPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable name for the SQL variable.'),
    type: zod
        .enum(['String', 'Number', 'Boolean', 'List', 'Date'])
        .describe('* `String` - String\n* `Number` - Number\n* `Boolean` - Boolean\n* `List` - List\n* `Date` - Date')
        .optional()
        .describe(
            'Variable type. Controls how the value is rendered and substituted in HogQL.\n\n* `String` - String\n* `Number` - Number\n* `Boolean` - Boolean\n* `List` - List\n* `Date` - Date'
        ),
    default_value: zod.unknown().optional().describe('Default value used when a query references this variable.'),
    values: zod.unknown().optional().describe('Allowed values for List variables. Null for other variable types.'),
})

export const InsightVariablesDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this insight variable.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const WarehouseSavedQueriesListQueryParams = /* @__PURE__ */ zod.object({
    page: zod.number().optional().describe('A page number within the paginated result set.'),
    search: zod.string().optional().describe('A search term.'),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesCreateBodyNameMax = 128

export const warehouseSavedQueriesCreateBodyQueryKindDefault = `HogQLQuery`

export const WarehouseSavedQueriesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key (always "HogQLQuery"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {"kind": "HogQLQuery", "query": "SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesPartialUpdateBodyNameMax = 128

export const warehouseSavedQueriesPartialUpdateBodyQueryKindDefault = `HogQLQuery`

export const WarehouseSavedQueriesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesPartialUpdateBodyNameMax)
            .optional()
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesPartialUpdateBodyQueryKindDefault),
                query: zod.string(),
            })
            .optional()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key (always "HogQLQuery"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {"kind": "HogQLQuery", "query": "SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Enable materialization for this saved query with a 24-hour sync frequency.
 */
export const WarehouseSavedQueriesMaterializeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesMaterializeCreateBodyNameMax = 128

export const warehouseSavedQueriesMaterializeCreateBodyQueryKindDefault = `HogQLQuery`

export const WarehouseSavedQueriesMaterializeCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesMaterializeCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesMaterializeCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key (always "HogQLQuery"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {"kind": "HogQLQuery", "query": "SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Undo materialization, revert back to the original view.
 * (i.e. delete the materialized table and the schedule)
 */
export const WarehouseSavedQueriesRevertMaterializationCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesRevertMaterializationCreateBodyNameMax = 128

export const warehouseSavedQueriesRevertMaterializationCreateBodyQueryKindDefault = `HogQLQuery`

export const WarehouseSavedQueriesRevertMaterializationCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRevertMaterializationCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .object({
                kind: zod
                    .enum(['HogQLQuery'])
                    .default(warehouseSavedQueriesRevertMaterializationCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key (always "HogQLQuery"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {"kind": "HogQLQuery", "query": "SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Run this saved query.
 */
export const WarehouseSavedQueriesRunCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesRunCreateBodyNameMax = 128

export const warehouseSavedQueriesRunCreateBodyQueryKindDefault = `HogQLQuery`

export const WarehouseSavedQueriesRunCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRunCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesRunCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key (always "HogQLQuery"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {"kind": "HogQLQuery", "query": "SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Return the recent run history (up to 5 most recent) for this materialized view.
 */
export const WarehouseSavedQueriesRunHistoryRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
