/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 25 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

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

export const externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const ExternalDataSchemasPartialUpdateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc', 'xmin'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc\n* `xmin` - xmin'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, cdc, or xmin.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc\n* `xmin` - xmin'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid', 'xid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid\n* `xid` - xid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid\n* `xid` - xid'
        ),
    incremental_field_lookback_seconds: zod
        .number()
        .min(externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMin)
        .max(externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMax)
        .nullish()
        .describe(
            'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
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
    masked_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            "Names of source columns whose values are replaced with a deterministic one-way digest at sync time, for sensitive data such as passwords or PII. `null` (default) masks nothing. Primary-key columns and the active incremental field can't be masked, and direct query sources don't support masking. Any change to this list triggers a full resync of the table (CDC schemas re-snapshot); synced webhook schemas can't change masking, since their data can't be re-fetched."
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

export const externalDataSchemasCancelCreateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasCancelCreateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const ExternalDataSchemasCancelCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc', 'xmin'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc\n* `xmin` - xmin'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, cdc, or xmin.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc\n* `xmin` - xmin'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid', 'xid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid\n* `xid` - xid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid\n* `xid` - xid'
        ),
    incremental_field_lookback_seconds: zod
        .number()
        .min(externalDataSchemasCancelCreateBodyIncrementalFieldLookbackSecondsMin)
        .max(externalDataSchemasCancelCreateBodyIncrementalFieldLookbackSecondsMax)
        .nullish()
        .describe(
            'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
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
    masked_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            "Names of source columns whose values are replaced with a deterministic one-way digest at sync time, for sensitive data such as passwords or PII. `null` (default) masks nothing. Primary-key columns and the active incremental field can't be masked, and direct query sources don't support masking. Any change to this list triggers a full resync of the table (CDC schemas re-snapshot); synced webhook schemas can't change masking, since their data can't be re-fetched."
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

export const externalDataSchemasIncrementalFieldsCreateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasIncrementalFieldsCreateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const ExternalDataSchemasIncrementalFieldsCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc', 'xmin'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc\n* `xmin` - xmin'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, cdc, or xmin.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc\n* `xmin` - xmin'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid', 'xid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid\n* `xid` - xid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid\n* `xid` - xid'
        ),
    incremental_field_lookback_seconds: zod
        .number()
        .min(externalDataSchemasIncrementalFieldsCreateBodyIncrementalFieldLookbackSecondsMin)
        .max(externalDataSchemasIncrementalFieldsCreateBodyIncrementalFieldLookbackSecondsMax)
        .nullish()
        .describe(
            'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
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
    masked_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            "Names of source columns whose values are replaced with a deterministic one-way digest at sync time, for sensitive data such as passwords or PII. `null` (default) masks nothing. Primary-key columns and the active incremental field can't be masked, and direct query sources don't support masking. Any change to this list triggers a full resync of the table (CDC schemas re-snapshot); synced webhook schemas can't change masking, since their data can't be re-fetched."
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

export const externalDataSchemasReloadCreateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasReloadCreateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const ExternalDataSchemasReloadCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc', 'xmin'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc\n* `xmin` - xmin'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, cdc, or xmin.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc\n* `xmin` - xmin'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid', 'xid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid\n* `xid` - xid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid\n* `xid` - xid'
        ),
    incremental_field_lookback_seconds: zod
        .number()
        .min(externalDataSchemasReloadCreateBodyIncrementalFieldLookbackSecondsMin)
        .max(externalDataSchemasReloadCreateBodyIncrementalFieldLookbackSecondsMax)
        .nullish()
        .describe(
            'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
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
    masked_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            "Names of source columns whose values are replaced with a deterministic one-way digest at sync time, for sensitive data such as passwords or PII. `null` (default) masks nothing. Primary-key columns and the active incremental field can't be masked, and direct query sources don't support masking. Any change to this list triggers a full resync of the table (CDC schemas re-snapshot); synced webhook schemas can't change masking, since their data can't be re-fetched."
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

export const externalDataSchemasResyncCreateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasResyncCreateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const ExternalDataSchemasResyncCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc', 'xmin'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc\n* `xmin` - xmin'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, cdc, or xmin.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc\n* `xmin` - xmin'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid', 'xid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid\n* `xid` - xid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid\n* `xid` - xid'
        ),
    incremental_field_lookback_seconds: zod
        .number()
        .min(externalDataSchemasResyncCreateBodyIncrementalFieldLookbackSecondsMin)
        .max(externalDataSchemasResyncCreateBodyIncrementalFieldLookbackSecondsMax)
        .nullish()
        .describe(
            'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
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
    masked_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            "Names of source columns whose values are replaced with a deterministic one-way digest at sync time, for sensitive data such as passwords or PII. `null` (default) masks nothing. Primary-key columns and the active incremental field can't be masked, and direct query sources don't support masking. Any change to this list triggers a full resync of the table (CDC schemas re-snapshot); synced webhook schemas can't change masking, since their data can't be re-fetched."
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
export const externalDataSourcesCreateBodyDirectQueryEnabledDefault = true

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
            'OneHundredMs',
            'SevenShifts',
            'AcuityScheduling',
            'AgileCRM',
            'Aha',
            'Airbyte',
            'Akeneo',
            'Algolia',
            'AlpacaBrokerAPI',
            'ApifyDataset',
            'Appcues',
            'Appfigures',
            'Appfollow',
            'Apptivo',
            'AssemblyAI',
            'Awin',
            'AwsCloudTrail',
            'AzureTableStorage',
            'Babelforce',
            'Basecamp',
            'Beamer',
            'BigMailer',
            'Bluetally',
            'BoldSign',
            'BreezyHR',
            'Bugsnag',
            'Buildkite',
            'Bunny',
            'Buzzsprout',
            'CalCom',
            'CallRail',
            'Campayn',
            'Canny',
            'CapsuleCRM',
            'CaptainData',
            'CartCom',
            'CastorEDC',
            'Chameleon',
            'Chargedesk',
            'Chargify',
            'Chift',
            'Churnkey',
            'Cin7',
            'CiscoMeraki',
            'Clazar',
            'Clockify',
            'Clockodo',
            'Cloudbeds',
            'Coassemble',
            'Codefresh',
            'Concord',
            'ConfigCat',
            'Couchbase',
            'Curve',
            'Customerly',
            'Datascope',
            'Dbt',
            'Deputy',
            'DevinAI',
            'Docuseal',
            'Dolibarr',
            'Dremio',
            'DropboxSign',
            'Dwolla',
            'EConomic',
            'Easypost',
            'Easypromos',
            'Elasticemail',
            'EmailOctopus',
            'EmploymentHero',
            'Encharge',
            'Eventee',
            'Eventzilla',
            'Everhour',
            'EZOfficeInventory',
            'Factorial',
            'Fastbill',
            'Fastly',
            'Fauna',
            'Feishu',
            'Fillout',
            'Finage',
            'Firebolt',
            'FireHydrant',
            'Fleetio',
            'Flexmail',
            'Flexport',
            'FloatApp',
            'Flowlu',
            'Formbricks',
            'FreeAgent',
            'Freightview',
            'Freshcaller',
            'Freshchat',
            'Freshservice',
            'Fulcrum',
            'GainsightPx',
            'GitBook',
            'Glassfrog',
            'Goldcast',
            'GoLogin',
            'Grafana',
            'GreytHr',
            'Gridly',
            'Harness',
            'Height',
            'Hellobaton',
            'HighLevel',
            'HoorayHR',
            'Hubplanner',
            'Humanitix',
            'Huntr',
            'Inflowinventory',
            'InforNexus',
            'Insightful',
            'Insightly',
            'Instantly',
            'Instatus',
            'Intruder',
            'Invoiced',
            'Invoiceninja',
            'JamfPro',
            'JobNimbus',
            'Jotform',
            'JudgeMeReviews',
            'JustCall',
            'JustSift',
            'K6Cloud',
            'Katana',
            'Keka',
            'Kisi',
            'Kissmetrics',
            'Klarna',
            'Klaus',
            'Lago',
            'Leadfeeder',
            'Lemlist',
            'LessAnnoyingCRM',
            'LinkedinPages',
            'Linkrunner',
            'Linnworks',
            'Lob',
            'Lokalise',
            'Looker',
            'Luma',
            'MailerSend',
            'Mailosaur',
            'Mailtrap',
            'Mantle',
            'Mention',
            'MercadoAds',
            'Merge',
            'Metabase',
            'Metricool',
            'MicrosoftDataverse',
            'MicrosoftEntraId',
            'MicrosoftLists',
            'Miro',
            'Missive',
            'MixMax',
            'Mode',
            'Mux',
            'MyHours',
            'N8n',
            'Navan',
            'NebiusAI',
            'Nexiopay',
            'NinjaOneRMM',
            'NoCRM',
            'NorthpassLMS',
            'Nutshell',
            'Nylas',
            'Oncehub',
            'Onepagecrm',
            'OneSignal',
            'Onfleet',
            'OpinionStage',
            'OPUSWatch',
            'Orb',
            'Orbit',
            'Oura',
            'Oveit',
            'PabblySubscriptionsBilling',
            'Paperform',
            'Papersign',
            'Partnerize',
            'PartnerStack',
            'PayFit',
            'Paystack',
            'Pennylane',
            'Perk',
            'PersistIq',
            'Persona',
            'Phyllo',
            'Picqer',
            'Pipeliner',
            'PivotalTracker',
            'Piwik',
            'Planhat',
            'Plausible',
            'Poplar',
            'PrestaShop',
            'Pretix',
            'Primetric',
            'Printify',
            'Productive',
            'Pylon',
            'Qonto',
            'Qualaroo',
            'Railz',
            'RDStationMarketing',
            'Recruitee',
            'Reddit',
            'ReferralHero',
            'RentCast',
            'Repairshopr',
            'ReplyIo',
            'RetailExpress',
            'Retently',
            'RevolutMerchant',
            'RocketChat',
            'Rocketlane',
            'Rootly',
            'Ruddr',
            'SafetyCulture',
            'SageHR',
            'Salesflare',
            'SAPFieldglass',
            'SavvyCal',
            'Secoda',
            'Segment',
            'Sendowl',
            'SendPulse',
            'Senseforce',
            'Serpstat',
            'Sharetribe',
            'Shippo',
            'ShopWired',
            'Shortio',
            'Shutterstock',
            'SigmaComputing',
            'SignNow',
            'SimpleCast',
            'Simplesat',
            'Smaily',
            'SmartEngage',
            'Smartreach',
            'Smartwaiver',
            'SolarwindsServiceDesk',
            'SonarCloud',
            'SparkPost',
            'SplitIo',
            'SpotifyAds',
            'SpotlerCRM',
            'Squarespace',
            'Statsig',
            'Statuspage',
            'Stigg',
            'Strava',
            'SurveySparrow',
            'Survicate',
            'Svix',
            'Systeme',
            'Tavus',
            'Teamtailor',
            'Teamwork',
            'Tempo',
            'Testrail',
            'Thinkific',
            'ThinkificCourses',
            'ThriveLearning',
            'Ticketmaster',
            'TicketTailor',
            'TickTick',
            'Timely',
            'Tinyemail',
            'Todoist',
            'Toggl',
            'TrackPMS',
            'Tremendous',
            'TrustPilot',
            'Twitter',
            'TyntecSMS',
            'Unleash',
            'UpPromote',
            'Uptick',
            'Uservoice',
            'Vantage',
            'Veeqo',
            'Vercel',
            'VismaEconomic',
            'VWO',
            'Waiteraid',
            'Wasabi',
            'WhenIWork',
            'Wordpress',
            'Workable',
            'Workflowmax',
            'Workramp',
            'Wufoo',
            'Xsolla',
            'YandexMetrica',
            'Yotpo',
            'Ynab',
            'Younium',
            'YouSign',
            'YoutubeData',
            'ZapierSupportedStorage',
            'ZapSign',
            'ZendeskSell',
            'ZendeskSunshine',
            'Zenefits',
            'Zenloop',
            'ZohoAnalytics',
            'ZohoBigin',
            'ZohoBilling',
            'ZohoBooks',
            'ZohoCampaign',
            'ZohoDesk',
            'ZohoExpense',
            'ZohoInventory',
            'ZohoInvoice',
            'ZonkaFeedback',
            'AlphaVantage',
            'Aviationstack',
            'Bitly',
            'Blogger',
            'Breezometer',
            'CareQualityCommission',
            'Cimis',
            'CoinApi',
            'CoinGecko',
            'CoinMarketCap',
            'DingConnect',
            'Dockerhub',
            'ExchangeRatesApi',
            'FinancialModelling',
            'Finnhub',
            'Finnworlds',
            'Giphy',
            'Gmail',
            'GNews',
            'GoogleCalendar',
            'GoogleClassroom',
            'GoogleDirectory',
            'GoogleForms',
            'GooglePageSpeedInsights',
            'GoogleTasks',
            'GoogleWebfonts',
            'GoogleWorkspaceAdminReports',
            'HuggingFace',
            'IlluminaBasespace',
            'Imagga',
            'Interzoid',
            'IP2Whois',
            'KYVE',
            'Marketstack',
            'Mendeley',
            'Nasa',
            'NewYorkTimes',
            'NewsApi',
            'NewsData',
            'OpenDataDc',
            'OpenExchangeRates',
            'OpenAQ',
            'OpenFDA',
            'OpenWeather',
            'Outlook',
            'Perigon',
            'Pexels',
            'Pocket',
            'Polygon',
            'PyPI',
            'Recreation',
            'RKICovid',
            'Rss',
            'SimFin',
            'StockData',
            'Guardian',
            'TMDb',
            'TVMaze',
            'TwelveData',
            'Ubidots',
            'USCensus',
            'Watchmode',
            'WikipediaPageviews',
            'YahooFinance',
            'Clarifai',
            'Adapty',
            'Braintrust',
            'StreamElements',
            'Streamlabs',
            'Datorama',
            'Ahrefs',
            'Lightfield',
            'Appstack',
            'Razorpay',
            'Neon',
            'NewRelic',
            'Custom',
            'Tile38',
            'Chatwoot',
            'Sanity',
            'Metronome',
            'Jobber',
            'Knock',
            'Leexi',
            'RB2B',
            'Superwall',
            'Liana',
            'TawkTo',
            'Hightouch',
            'LemonSqueezy',
            'Ikas',
            'Talkwalker',
            'NextdoorAds',
            'AppLovin',
            'Baserow',
            'Plunk',
            'Dub',
            'AirOps',
            'Podium',
            'Loops',
            'Redis',
            'Mercury',
            'Gojiberry',
            'Teachable',
        ])
        .describe(
            '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `GoogleSearchConsole` - GoogleSearchConsole\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex\n* `ClickHouse` - ClickHouse\n* `Plain` - Plain\n* `Resend` - Resend\n* `PgAnalyze` - PgAnalyze\n* `WorkOS` - WorkOS\n* `AmazonS3` - AmazonS3\n* `GoogleCloudStorage` - GoogleCloudStorage\n* `Databricks` - Databricks\n* `Dynamics365` - Dynamics365\n* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n* `Db2` - Db2\n* `Heap` - Heap\n* `AdobeAnalytics` - AdobeAnalytics\n* `Matomo` - Matomo\n* `Optimizely` - Optimizely\n* `Adyen` - Adyen\n* `GoCardless` - GoCardless\n* `Mollie` - Mollie\n* `CheckoutCom` - CheckoutCom\n* `Branch` - Branch\n* `Criteo` - Criteo\n* `Outbrain` - Outbrain\n* `Taboola` - Taboola\n* `AdRoll` - AdRoll\n* `DisplayVideo360` - DisplayVideo360\n* `GoogleAdManager` - GoogleAdManager\n* `CampaignManager360` - CampaignManager360\n* `SearchAds360` - SearchAds360\n* `AdobeCommerce` - AdobeCommerce\n* `AmazonSellingPartner` - AmazonSellingPartner\n* `Ebay` - Ebay\n* `Commercetools` - Commercetools\n* `LightspeedRetail` - LightspeedRetail\n* `ShipStation` - ShipStation\n* `ConstantContact` - ConstantContact\n* `Mailgun` - Mailgun\n* `Eloqua` - Eloqua\n* `Sailthru` - Sailthru\n* `Ortto` - Ortto\n* `Attentive` - Attentive\n* `Kustomer` - Kustomer\n* `Dixa` - Dixa\n* `Gladly` - Gladly\n* `Qualtrics` - Qualtrics\n* `Delighted` - Delighted\n* `AzureDevOps` - AzureDevOps\n* `Rollbar` - Rollbar\n* `Opsgenie` - Opsgenie\n* `IncidentIo` - IncidentIo\n* `Pingdom` - Pingdom\n* `Cloudflare` - Cloudflare\n* `CosmosDB` - CosmosDB\n* `PlanetScale` - PlanetScale\n* `SapHana` - SapHana\n* `Rippling` - Rippling\n* `HiBob` - HiBob\n* `Personio` - Personio\n* `Deel` - Deel\n* `AdpWorkforceNow` - AdpWorkforceNow\n* `Paylocity` - Paylocity\n* `Gusto` - Gusto\n* `CultureAmp` - CultureAmp\n* `Lattice` - Lattice\n* `SageIntacct` - SageIntacct\n* `FreshBooks` - FreshBooks\n* `Expensify` - Expensify\n* `Ramp` - Ramp\n* `Brex` - Brex\n* `Coupa` - Coupa\n* `SapConcur` - SapConcur\n* `Apollo` - Apollo\n* `Crunchbase` - Crunchbase\n* `ZoomInfo` - ZoomInfo\n* `Clari` - Clari\n* `Chorus` - Chorus\n* `Coda` - Coda\n* `Guru` - Guru\n* `Dropbox` - Dropbox\n* `Docusign` - Docusign\n* `PandaDoc` - PandaDoc\n* `SapErp` - SapErp\n* `SapSuccessFactors` - SapSuccessFactors\n* `OracleEbs` - OracleEbs\n* `OracleFusion` - OracleFusion\n* `AmazonSNS` - AmazonSNS\n* `AmazonEventBridge` - AmazonEventBridge\n* `AmazonSQS` - AmazonSQS\n* `AmazonKinesis` - AmazonKinesis\n* `AmazonCloudWatch` - AmazonCloudWatch\n* `OpenAIAds` - OpenAIAds\n* `OneHundredMs` - OneHundredMs\n* `SevenShifts` - SevenShifts\n* `AcuityScheduling` - AcuityScheduling\n* `AgileCRM` - AgileCRM\n* `Aha` - Aha\n* `Airbyte` - Airbyte\n* `Akeneo` - Akeneo\n* `Algolia` - Algolia\n* `AlpacaBrokerAPI` - AlpacaBrokerAPI\n* `ApifyDataset` - ApifyDataset\n* `Appcues` - Appcues\n* `Appfigures` - Appfigures\n* `Appfollow` - Appfollow\n* `Apptivo` - Apptivo\n* `AssemblyAI` - AssemblyAI\n* `Awin` - Awin\n* `AwsCloudTrail` - AwsCloudTrail\n* `AzureTableStorage` - AzureTableStorage\n* `Babelforce` - Babelforce\n* `Basecamp` - Basecamp\n* `Beamer` - Beamer\n* `BigMailer` - BigMailer\n* `Bluetally` - Bluetally\n* `BoldSign` - BoldSign\n* `BreezyHR` - BreezyHR\n* `Bugsnag` - Bugsnag\n* `Buildkite` - Buildkite\n* `Bunny` - Bunny\n* `Buzzsprout` - Buzzsprout\n* `CalCom` - CalCom\n* `CallRail` - CallRail\n* `Campayn` - Campayn\n* `Canny` - Canny\n* `CapsuleCRM` - CapsuleCRM\n* `CaptainData` - CaptainData\n* `CartCom` - CartCom\n* `CastorEDC` - CastorEDC\n* `Chameleon` - Chameleon\n* `Chargedesk` - Chargedesk\n* `Chargify` - Chargify\n* `Chift` - Chift\n* `Churnkey` - Churnkey\n* `Cin7` - Cin7\n* `CiscoMeraki` - CiscoMeraki\n* `Clazar` - Clazar\n* `Clockify` - Clockify\n* `Clockodo` - Clockodo\n* `Cloudbeds` - Cloudbeds\n* `Coassemble` - Coassemble\n* `Codefresh` - Codefresh\n* `Concord` - Concord\n* `ConfigCat` - ConfigCat\n* `Couchbase` - Couchbase\n* `Curve` - Curve\n* `Customerly` - Customerly\n* `Datascope` - Datascope\n* `Dbt` - Dbt\n* `Deputy` - Deputy\n* `DevinAI` - DevinAI\n* `Docuseal` - Docuseal\n* `Dolibarr` - Dolibarr\n* `Dremio` - Dremio\n* `DropboxSign` - DropboxSign\n* `Dwolla` - Dwolla\n* `EConomic` - EConomic\n* `Easypost` - Easypost\n* `Easypromos` - Easypromos\n* `Elasticemail` - Elasticemail\n* `EmailOctopus` - EmailOctopus\n* `EmploymentHero` - EmploymentHero\n* `Encharge` - Encharge\n* `Eventee` - Eventee\n* `Eventzilla` - Eventzilla\n* `Everhour` - Everhour\n* `EZOfficeInventory` - EZOfficeInventory\n* `Factorial` - Factorial\n* `Fastbill` - Fastbill\n* `Fastly` - Fastly\n* `Fauna` - Fauna\n* `Feishu` - Feishu\n* `Fillout` - Fillout\n* `Finage` - Finage\n* `Firebolt` - Firebolt\n* `FireHydrant` - FireHydrant\n* `Fleetio` - Fleetio\n* `Flexmail` - Flexmail\n* `Flexport` - Flexport\n* `FloatApp` - FloatApp\n* `Flowlu` - Flowlu\n* `Formbricks` - Formbricks\n* `FreeAgent` - FreeAgent\n* `Freightview` - Freightview\n* `Freshcaller` - Freshcaller\n* `Freshchat` - Freshchat\n* `Freshservice` - Freshservice\n* `Fulcrum` - Fulcrum\n* `GainsightPx` - GainsightPx\n* `GitBook` - GitBook\n* `Glassfrog` - Glassfrog\n* `Goldcast` - Goldcast\n* `GoLogin` - GoLogin\n* `Grafana` - Grafana\n* `GreytHr` - GreytHr\n* `Gridly` - Gridly\n* `Harness` - Harness\n* `Height` - Height\n* `Hellobaton` - Hellobaton\n* `HighLevel` - HighLevel\n* `HoorayHR` - HoorayHR\n* `Hubplanner` - Hubplanner\n* `Humanitix` - Humanitix\n* `Huntr` - Huntr\n* `Inflowinventory` - Inflowinventory\n* `InforNexus` - InforNexus\n* `Insightful` - Insightful\n* `Insightly` - Insightly\n* `Instantly` - Instantly\n* `Instatus` - Instatus\n* `Intruder` - Intruder\n* `Invoiced` - Invoiced\n* `Invoiceninja` - Invoiceninja\n* `JamfPro` - JamfPro\n* `JobNimbus` - JobNimbus\n* `Jotform` - Jotform\n* `JudgeMeReviews` - JudgeMeReviews\n* `JustCall` - JustCall\n* `JustSift` - JustSift\n* `K6Cloud` - K6Cloud\n* `Katana` - Katana\n* `Keka` - Keka\n* `Kisi` - Kisi\n* `Kissmetrics` - Kissmetrics\n* `Klarna` - Klarna\n* `Klaus` - Klaus\n* `Lago` - Lago\n* `Leadfeeder` - Leadfeeder\n* `Lemlist` - Lemlist\n* `LessAnnoyingCRM` - LessAnnoyingCRM\n* `LinkedinPages` - LinkedinPages\n* `Linkrunner` - Linkrunner\n* `Linnworks` - Linnworks\n* `Lob` - Lob\n* `Lokalise` - Lokalise\n* `Looker` - Looker\n* `Luma` - Luma\n* `MailerSend` - MailerSend\n* `Mailosaur` - Mailosaur\n* `Mailtrap` - Mailtrap\n* `Mantle` - Mantle\n* `Mention` - Mention\n* `MercadoAds` - MercadoAds\n* `Merge` - Merge\n* `Metabase` - Metabase\n* `Metricool` - Metricool\n* `MicrosoftDataverse` - MicrosoftDataverse\n* `MicrosoftEntraId` - MicrosoftEntraId\n* `MicrosoftLists` - MicrosoftLists\n* `Miro` - Miro\n* `Missive` - Missive\n* `MixMax` - MixMax\n* `Mode` - Mode\n* `Mux` - Mux\n* `MyHours` - MyHours\n* `N8n` - N8n\n* `Navan` - Navan\n* `NebiusAI` - NebiusAI\n* `Nexiopay` - Nexiopay\n* `NinjaOneRMM` - NinjaOneRMM\n* `NoCRM` - NoCRM\n* `NorthpassLMS` - NorthpassLMS\n* `Nutshell` - Nutshell\n* `Nylas` - Nylas\n* `Oncehub` - Oncehub\n* `Onepagecrm` - Onepagecrm\n* `OneSignal` - OneSignal\n* `Onfleet` - Onfleet\n* `OpinionStage` - OpinionStage\n* `OPUSWatch` - OPUSWatch\n* `Orb` - Orb\n* `Orbit` - Orbit\n* `Oura` - Oura\n* `Oveit` - Oveit\n* `PabblySubscriptionsBilling` - PabblySubscriptionsBilling\n* `Paperform` - Paperform\n* `Papersign` - Papersign\n* `Partnerize` - Partnerize\n* `PartnerStack` - PartnerStack\n* `PayFit` - PayFit\n* `Paystack` - Paystack\n* `Pennylane` - Pennylane\n* `Perk` - Perk\n* `PersistIq` - PersistIq\n* `Persona` - Persona\n* `Phyllo` - Phyllo\n* `Picqer` - Picqer\n* `Pipeliner` - Pipeliner\n* `PivotalTracker` - PivotalTracker\n* `Piwik` - Piwik\n* `Planhat` - Planhat\n* `Plausible` - Plausible\n* `Poplar` - Poplar\n* `PrestaShop` - PrestaShop\n* `Pretix` - Pretix\n* `Primetric` - Primetric\n* `Printify` - Printify\n* `Productive` - Productive\n* `Pylon` - Pylon\n* `Qonto` - Qonto\n* `Qualaroo` - Qualaroo\n* `Railz` - Railz\n* `RDStationMarketing` - RDStationMarketing\n* `Recruitee` - Recruitee\n* `Reddit` - Reddit\n* `ReferralHero` - ReferralHero\n* `RentCast` - RentCast\n* `Repairshopr` - Repairshopr\n* `ReplyIo` - ReplyIo\n* `RetailExpress` - RetailExpress\n* `Retently` - Retently\n* `RevolutMerchant` - RevolutMerchant\n* `RocketChat` - RocketChat\n* `Rocketlane` - Rocketlane\n* `Rootly` - Rootly\n* `Ruddr` - Ruddr\n* `SafetyCulture` - SafetyCulture\n* `SageHR` - SageHR\n* `Salesflare` - Salesflare\n* `SAPFieldglass` - SAPFieldglass\n* `SavvyCal` - SavvyCal\n* `Secoda` - Secoda\n* `Segment` - Segment\n* `Sendowl` - Sendowl\n* `SendPulse` - SendPulse\n* `Senseforce` - Senseforce\n* `Serpstat` - Serpstat\n* `Sharetribe` - Sharetribe\n* `Shippo` - Shippo\n* `ShopWired` - ShopWired\n* `Shortio` - Shortio\n* `Shutterstock` - Shutterstock\n* `SigmaComputing` - SigmaComputing\n* `SignNow` - SignNow\n* `SimpleCast` - SimpleCast\n* `Simplesat` - Simplesat\n* `Smaily` - Smaily\n* `SmartEngage` - SmartEngage\n* `Smartreach` - Smartreach\n* `Smartwaiver` - Smartwaiver\n* `SolarwindsServiceDesk` - SolarwindsServiceDesk\n* `SonarCloud` - SonarCloud\n* `SparkPost` - SparkPost\n* `SplitIo` - SplitIo\n* `SpotifyAds` - SpotifyAds\n* `SpotlerCRM` - SpotlerCRM\n* `Squarespace` - Squarespace\n* `Statsig` - Statsig\n* `Statuspage` - Statuspage\n* `Stigg` - Stigg\n* `Strava` - Strava\n* `SurveySparrow` - SurveySparrow\n* `Survicate` - Survicate\n* `Svix` - Svix\n* `Systeme` - Systeme\n* `Tavus` - Tavus\n* `Teamtailor` - Teamtailor\n* `Teamwork` - Teamwork\n* `Tempo` - Tempo\n* `Testrail` - Testrail\n* `Thinkific` - Thinkific\n* `ThinkificCourses` - ThinkificCourses\n* `ThriveLearning` - ThriveLearning\n* `Ticketmaster` - Ticketmaster\n* `TicketTailor` - TicketTailor\n* `TickTick` - TickTick\n* `Timely` - Timely\n* `Tinyemail` - Tinyemail\n* `Todoist` - Todoist\n* `Toggl` - Toggl\n* `TrackPMS` - TrackPMS\n* `Tremendous` - Tremendous\n* `TrustPilot` - TrustPilot\n* `Twitter` - Twitter\n* `TyntecSMS` - TyntecSMS\n* `Unleash` - Unleash\n* `UpPromote` - UpPromote\n* `Uptick` - Uptick\n* `Uservoice` - Uservoice\n* `Vantage` - Vantage\n* `Veeqo` - Veeqo\n* `Vercel` - Vercel\n* `VismaEconomic` - VismaEconomic\n* `VWO` - VWO\n* `Waiteraid` - Waiteraid\n* `Wasabi` - Wasabi\n* `WhenIWork` - WhenIWork\n* `Wordpress` - Wordpress\n* `Workable` - Workable\n* `Workflowmax` - Workflowmax\n* `Workramp` - Workramp\n* `Wufoo` - Wufoo\n* `Xsolla` - Xsolla\n* `YandexMetrica` - YandexMetrica\n* `Yotpo` - Yotpo\n* `Ynab` - Ynab\n* `Younium` - Younium\n* `YouSign` - YouSign\n* `YoutubeData` - YoutubeData\n* `ZapierSupportedStorage` - ZapierSupportedStorage\n* `ZapSign` - ZapSign\n* `ZendeskSell` - ZendeskSell\n* `ZendeskSunshine` - ZendeskSunshine\n* `Zenefits` - Zenefits\n* `Zenloop` - Zenloop\n* `ZohoAnalytics` - ZohoAnalytics\n* `ZohoBigin` - ZohoBigin\n* `ZohoBilling` - ZohoBilling\n* `ZohoBooks` - ZohoBooks\n* `ZohoCampaign` - ZohoCampaign\n* `ZohoDesk` - ZohoDesk\n* `ZohoExpense` - ZohoExpense\n* `ZohoInventory` - ZohoInventory\n* `ZohoInvoice` - ZohoInvoice\n* `ZonkaFeedback` - ZonkaFeedback\n* `AlphaVantage` - AlphaVantage\n* `Aviationstack` - Aviationstack\n* `Bitly` - Bitly\n* `Blogger` - Blogger\n* `Breezometer` - Breezometer\n* `CareQualityCommission` - CareQualityCommission\n* `Cimis` - Cimis\n* `CoinApi` - CoinApi\n* `CoinGecko` - CoinGecko\n* `CoinMarketCap` - CoinMarketCap\n* `DingConnect` - DingConnect\n* `Dockerhub` - Dockerhub\n* `ExchangeRatesApi` - ExchangeRatesApi\n* `FinancialModelling` - FinancialModelling\n* `Finnhub` - Finnhub\n* `Finnworlds` - Finnworlds\n* `Giphy` - Giphy\n* `Gmail` - Gmail\n* `GNews` - GNews\n* `GoogleCalendar` - GoogleCalendar\n* `GoogleClassroom` - GoogleClassroom\n* `GoogleDirectory` - GoogleDirectory\n* `GoogleForms` - GoogleForms\n* `GooglePageSpeedInsights` - GooglePageSpeedInsights\n* `GoogleTasks` - GoogleTasks\n* `GoogleWebfonts` - GoogleWebfonts\n* `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports\n* `HuggingFace` - HuggingFace\n* `IlluminaBasespace` - IlluminaBasespace\n* `Imagga` - Imagga\n* `Interzoid` - Interzoid\n* `IP2Whois` - IP2Whois\n* `KYVE` - KYVE\n* `Marketstack` - Marketstack\n* `Mendeley` - Mendeley\n* `Nasa` - Nasa\n* `NewYorkTimes` - NewYorkTimes\n* `NewsApi` - NewsApi\n* `NewsData` - NewsData\n* `OpenDataDc` - OpenDataDc\n* `OpenExchangeRates` - OpenExchangeRates\n* `OpenAQ` - OpenAQ\n* `OpenFDA` - OpenFDA\n* `OpenWeather` - OpenWeather\n* `Outlook` - Outlook\n* `Perigon` - Perigon\n* `Pexels` - Pexels\n* `Pocket` - Pocket\n* `Polygon` - Polygon\n* `PyPI` - PyPI\n* `Recreation` - Recreation\n* `RKICovid` - RKICovid\n* `Rss` - Rss\n* `SimFin` - SimFin\n* `StockData` - StockData\n* `Guardian` - Guardian\n* `TMDb` - TMDb\n* `TVMaze` - TVMaze\n* `TwelveData` - TwelveData\n* `Ubidots` - Ubidots\n* `USCensus` - USCensus\n* `Watchmode` - Watchmode\n* `WikipediaPageviews` - WikipediaPageviews\n* `YahooFinance` - YahooFinance\n* `Clarifai` - Clarifai\n* `Adapty` - Adapty\n* `Braintrust` - Braintrust\n* `StreamElements` - StreamElements\n* `Streamlabs` - Streamlabs\n* `Datorama` - Datorama\n* `Ahrefs` - Ahrefs\n* `Lightfield` - Lightfield\n* `Appstack` - Appstack\n* `Razorpay` - Razorpay\n* `Neon` - Neon\n* `NewRelic` - NewRelic\n* `Custom` - Custom\n* `Tile38` - Tile38\n* `Chatwoot` - Chatwoot\n* `Sanity` - Sanity\n* `Metronome` - Metronome\n* `Jobber` - Jobber\n* `Knock` - Knock\n* `Leexi` - Leexi\n* `RB2B` - RB2B\n* `Superwall` - Superwall\n* `Liana` - Liana\n* `TawkTo` - TawkTo\n* `Hightouch` - Hightouch\n* `LemonSqueezy` - LemonSqueezy\n* `Ikas` - Ikas\n* `Talkwalker` - Talkwalker\n* `NextdoorAds` - NextdoorAds\n* `AppLovin` - AppLovin\n* `Baserow` - Baserow\n* `Plunk` - Plunk\n* `Dub` - Dub\n* `AirOps` - AirOps\n* `Podium` - Podium\n* `Loops` - Loops\n* `Redis` - Redis\n* `Mercury` - Mercury\n* `Gojiberry` - Gojiberry\n* `Teachable` - Teachable'
        )
        .describe(
            "The source type (e.g. 'Postgres', 'Stripe').\n\n* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `GoogleSearchConsole` - GoogleSearchConsole\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex\n* `ClickHouse` - ClickHouse\n* `Plain` - Plain\n* `Resend` - Resend\n* `PgAnalyze` - PgAnalyze\n* `WorkOS` - WorkOS\n* `AmazonS3` - AmazonS3\n* `GoogleCloudStorage` - GoogleCloudStorage\n* `Databricks` - Databricks\n* `Dynamics365` - Dynamics365\n* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n* `Db2` - Db2\n* `Heap` - Heap\n* `AdobeAnalytics` - AdobeAnalytics\n* `Matomo` - Matomo\n* `Optimizely` - Optimizely\n* `Adyen` - Adyen\n* `GoCardless` - GoCardless\n* `Mollie` - Mollie\n* `CheckoutCom` - CheckoutCom\n* `Branch` - Branch\n* `Criteo` - Criteo\n* `Outbrain` - Outbrain\n* `Taboola` - Taboola\n* `AdRoll` - AdRoll\n* `DisplayVideo360` - DisplayVideo360\n* `GoogleAdManager` - GoogleAdManager\n* `CampaignManager360` - CampaignManager360\n* `SearchAds360` - SearchAds360\n* `AdobeCommerce` - AdobeCommerce\n* `AmazonSellingPartner` - AmazonSellingPartner\n* `Ebay` - Ebay\n* `Commercetools` - Commercetools\n* `LightspeedRetail` - LightspeedRetail\n* `ShipStation` - ShipStation\n* `ConstantContact` - ConstantContact\n* `Mailgun` - Mailgun\n* `Eloqua` - Eloqua\n* `Sailthru` - Sailthru\n* `Ortto` - Ortto\n* `Attentive` - Attentive\n* `Kustomer` - Kustomer\n* `Dixa` - Dixa\n* `Gladly` - Gladly\n* `Qualtrics` - Qualtrics\n* `Delighted` - Delighted\n* `AzureDevOps` - AzureDevOps\n* `Rollbar` - Rollbar\n* `Opsgenie` - Opsgenie\n* `IncidentIo` - IncidentIo\n* `Pingdom` - Pingdom\n* `Cloudflare` - Cloudflare\n* `CosmosDB` - CosmosDB\n* `PlanetScale` - PlanetScale\n* `SapHana` - SapHana\n* `Rippling` - Rippling\n* `HiBob` - HiBob\n* `Personio` - Personio\n* `Deel` - Deel\n* `AdpWorkforceNow` - AdpWorkforceNow\n* `Paylocity` - Paylocity\n* `Gusto` - Gusto\n* `CultureAmp` - CultureAmp\n* `Lattice` - Lattice\n* `SageIntacct` - SageIntacct\n* `FreshBooks` - FreshBooks\n* `Expensify` - Expensify\n* `Ramp` - Ramp\n* `Brex` - Brex\n* `Coupa` - Coupa\n* `SapConcur` - SapConcur\n* `Apollo` - Apollo\n* `Crunchbase` - Crunchbase\n* `ZoomInfo` - ZoomInfo\n* `Clari` - Clari\n* `Chorus` - Chorus\n* `Coda` - Coda\n* `Guru` - Guru\n* `Dropbox` - Dropbox\n* `Docusign` - Docusign\n* `PandaDoc` - PandaDoc\n* `SapErp` - SapErp\n* `SapSuccessFactors` - SapSuccessFactors\n* `OracleEbs` - OracleEbs\n* `OracleFusion` - OracleFusion\n* `AmazonSNS` - AmazonSNS\n* `AmazonEventBridge` - AmazonEventBridge\n* `AmazonSQS` - AmazonSQS\n* `AmazonKinesis` - AmazonKinesis\n* `AmazonCloudWatch` - AmazonCloudWatch\n* `OpenAIAds` - OpenAIAds\n* `OneHundredMs` - OneHundredMs\n* `SevenShifts` - SevenShifts\n* `AcuityScheduling` - AcuityScheduling\n* `AgileCRM` - AgileCRM\n* `Aha` - Aha\n* `Airbyte` - Airbyte\n* `Akeneo` - Akeneo\n* `Algolia` - Algolia\n* `AlpacaBrokerAPI` - AlpacaBrokerAPI\n* `ApifyDataset` - ApifyDataset\n* `Appcues` - Appcues\n* `Appfigures` - Appfigures\n* `Appfollow` - Appfollow\n* `Apptivo` - Apptivo\n* `AssemblyAI` - AssemblyAI\n* `Awin` - Awin\n* `AwsCloudTrail` - AwsCloudTrail\n* `AzureTableStorage` - AzureTableStorage\n* `Babelforce` - Babelforce\n* `Basecamp` - Basecamp\n* `Beamer` - Beamer\n* `BigMailer` - BigMailer\n* `Bluetally` - Bluetally\n* `BoldSign` - BoldSign\n* `BreezyHR` - BreezyHR\n* `Bugsnag` - Bugsnag\n* `Buildkite` - Buildkite\n* `Bunny` - Bunny\n* `Buzzsprout` - Buzzsprout\n* `CalCom` - CalCom\n* `CallRail` - CallRail\n* `Campayn` - Campayn\n* `Canny` - Canny\n* `CapsuleCRM` - CapsuleCRM\n* `CaptainData` - CaptainData\n* `CartCom` - CartCom\n* `CastorEDC` - CastorEDC\n* `Chameleon` - Chameleon\n* `Chargedesk` - Chargedesk\n* `Chargify` - Chargify\n* `Chift` - Chift\n* `Churnkey` - Churnkey\n* `Cin7` - Cin7\n* `CiscoMeraki` - CiscoMeraki\n* `Clazar` - Clazar\n* `Clockify` - Clockify\n* `Clockodo` - Clockodo\n* `Cloudbeds` - Cloudbeds\n* `Coassemble` - Coassemble\n* `Codefresh` - Codefresh\n* `Concord` - Concord\n* `ConfigCat` - ConfigCat\n* `Couchbase` - Couchbase\n* `Curve` - Curve\n* `Customerly` - Customerly\n* `Datascope` - Datascope\n* `Dbt` - Dbt\n* `Deputy` - Deputy\n* `DevinAI` - DevinAI\n* `Docuseal` - Docuseal\n* `Dolibarr` - Dolibarr\n* `Dremio` - Dremio\n* `DropboxSign` - DropboxSign\n* `Dwolla` - Dwolla\n* `EConomic` - EConomic\n* `Easypost` - Easypost\n* `Easypromos` - Easypromos\n* `Elasticemail` - Elasticemail\n* `EmailOctopus` - EmailOctopus\n* `EmploymentHero` - EmploymentHero\n* `Encharge` - Encharge\n* `Eventee` - Eventee\n* `Eventzilla` - Eventzilla\n* `Everhour` - Everhour\n* `EZOfficeInventory` - EZOfficeInventory\n* `Factorial` - Factorial\n* `Fastbill` - Fastbill\n* `Fastly` - Fastly\n* `Fauna` - Fauna\n* `Feishu` - Feishu\n* `Fillout` - Fillout\n* `Finage` - Finage\n* `Firebolt` - Firebolt\n* `FireHydrant` - FireHydrant\n* `Fleetio` - Fleetio\n* `Flexmail` - Flexmail\n* `Flexport` - Flexport\n* `FloatApp` - FloatApp\n* `Flowlu` - Flowlu\n* `Formbricks` - Formbricks\n* `FreeAgent` - FreeAgent\n* `Freightview` - Freightview\n* `Freshcaller` - Freshcaller\n* `Freshchat` - Freshchat\n* `Freshservice` - Freshservice\n* `Fulcrum` - Fulcrum\n* `GainsightPx` - GainsightPx\n* `GitBook` - GitBook\n* `Glassfrog` - Glassfrog\n* `Goldcast` - Goldcast\n* `GoLogin` - GoLogin\n* `Grafana` - Grafana\n* `GreytHr` - GreytHr\n* `Gridly` - Gridly\n* `Harness` - Harness\n* `Height` - Height\n* `Hellobaton` - Hellobaton\n* `HighLevel` - HighLevel\n* `HoorayHR` - HoorayHR\n* `Hubplanner` - Hubplanner\n* `Humanitix` - Humanitix\n* `Huntr` - Huntr\n* `Inflowinventory` - Inflowinventory\n* `InforNexus` - InforNexus\n* `Insightful` - Insightful\n* `Insightly` - Insightly\n* `Instantly` - Instantly\n* `Instatus` - Instatus\n* `Intruder` - Intruder\n* `Invoiced` - Invoiced\n* `Invoiceninja` - Invoiceninja\n* `JamfPro` - JamfPro\n* `JobNimbus` - JobNimbus\n* `Jotform` - Jotform\n* `JudgeMeReviews` - JudgeMeReviews\n* `JustCall` - JustCall\n* `JustSift` - JustSift\n* `K6Cloud` - K6Cloud\n* `Katana` - Katana\n* `Keka` - Keka\n* `Kisi` - Kisi\n* `Kissmetrics` - Kissmetrics\n* `Klarna` - Klarna\n* `Klaus` - Klaus\n* `Lago` - Lago\n* `Leadfeeder` - Leadfeeder\n* `Lemlist` - Lemlist\n* `LessAnnoyingCRM` - LessAnnoyingCRM\n* `LinkedinPages` - LinkedinPages\n* `Linkrunner` - Linkrunner\n* `Linnworks` - Linnworks\n* `Lob` - Lob\n* `Lokalise` - Lokalise\n* `Looker` - Looker\n* `Luma` - Luma\n* `MailerSend` - MailerSend\n* `Mailosaur` - Mailosaur\n* `Mailtrap` - Mailtrap\n* `Mantle` - Mantle\n* `Mention` - Mention\n* `MercadoAds` - MercadoAds\n* `Merge` - Merge\n* `Metabase` - Metabase\n* `Metricool` - Metricool\n* `MicrosoftDataverse` - MicrosoftDataverse\n* `MicrosoftEntraId` - MicrosoftEntraId\n* `MicrosoftLists` - MicrosoftLists\n* `Miro` - Miro\n* `Missive` - Missive\n* `MixMax` - MixMax\n* `Mode` - Mode\n* `Mux` - Mux\n* `MyHours` - MyHours\n* `N8n` - N8n\n* `Navan` - Navan\n* `NebiusAI` - NebiusAI\n* `Nexiopay` - Nexiopay\n* `NinjaOneRMM` - NinjaOneRMM\n* `NoCRM` - NoCRM\n* `NorthpassLMS` - NorthpassLMS\n* `Nutshell` - Nutshell\n* `Nylas` - Nylas\n* `Oncehub` - Oncehub\n* `Onepagecrm` - Onepagecrm\n* `OneSignal` - OneSignal\n* `Onfleet` - Onfleet\n* `OpinionStage` - OpinionStage\n* `OPUSWatch` - OPUSWatch\n* `Orb` - Orb\n* `Orbit` - Orbit\n* `Oura` - Oura\n* `Oveit` - Oveit\n* `PabblySubscriptionsBilling` - PabblySubscriptionsBilling\n* `Paperform` - Paperform\n* `Papersign` - Papersign\n* `Partnerize` - Partnerize\n* `PartnerStack` - PartnerStack\n* `PayFit` - PayFit\n* `Paystack` - Paystack\n* `Pennylane` - Pennylane\n* `Perk` - Perk\n* `PersistIq` - PersistIq\n* `Persona` - Persona\n* `Phyllo` - Phyllo\n* `Picqer` - Picqer\n* `Pipeliner` - Pipeliner\n* `PivotalTracker` - PivotalTracker\n* `Piwik` - Piwik\n* `Planhat` - Planhat\n* `Plausible` - Plausible\n* `Poplar` - Poplar\n* `PrestaShop` - PrestaShop\n* `Pretix` - Pretix\n* `Primetric` - Primetric\n* `Printify` - Printify\n* `Productive` - Productive\n* `Pylon` - Pylon\n* `Qonto` - Qonto\n* `Qualaroo` - Qualaroo\n* `Railz` - Railz\n* `RDStationMarketing` - RDStationMarketing\n* `Recruitee` - Recruitee\n* `Reddit` - Reddit\n* `ReferralHero` - ReferralHero\n* `RentCast` - RentCast\n* `Repairshopr` - Repairshopr\n* `ReplyIo` - ReplyIo\n* `RetailExpress` - RetailExpress\n* `Retently` - Retently\n* `RevolutMerchant` - RevolutMerchant\n* `RocketChat` - RocketChat\n* `Rocketlane` - Rocketlane\n* `Rootly` - Rootly\n* `Ruddr` - Ruddr\n* `SafetyCulture` - SafetyCulture\n* `SageHR` - SageHR\n* `Salesflare` - Salesflare\n* `SAPFieldglass` - SAPFieldglass\n* `SavvyCal` - SavvyCal\n* `Secoda` - Secoda\n* `Segment` - Segment\n* `Sendowl` - Sendowl\n* `SendPulse` - SendPulse\n* `Senseforce` - Senseforce\n* `Serpstat` - Serpstat\n* `Sharetribe` - Sharetribe\n* `Shippo` - Shippo\n* `ShopWired` - ShopWired\n* `Shortio` - Shortio\n* `Shutterstock` - Shutterstock\n* `SigmaComputing` - SigmaComputing\n* `SignNow` - SignNow\n* `SimpleCast` - SimpleCast\n* `Simplesat` - Simplesat\n* `Smaily` - Smaily\n* `SmartEngage` - SmartEngage\n* `Smartreach` - Smartreach\n* `Smartwaiver` - Smartwaiver\n* `SolarwindsServiceDesk` - SolarwindsServiceDesk\n* `SonarCloud` - SonarCloud\n* `SparkPost` - SparkPost\n* `SplitIo` - SplitIo\n* `SpotifyAds` - SpotifyAds\n* `SpotlerCRM` - SpotlerCRM\n* `Squarespace` - Squarespace\n* `Statsig` - Statsig\n* `Statuspage` - Statuspage\n* `Stigg` - Stigg\n* `Strava` - Strava\n* `SurveySparrow` - SurveySparrow\n* `Survicate` - Survicate\n* `Svix` - Svix\n* `Systeme` - Systeme\n* `Tavus` - Tavus\n* `Teamtailor` - Teamtailor\n* `Teamwork` - Teamwork\n* `Tempo` - Tempo\n* `Testrail` - Testrail\n* `Thinkific` - Thinkific\n* `ThinkificCourses` - ThinkificCourses\n* `ThriveLearning` - ThriveLearning\n* `Ticketmaster` - Ticketmaster\n* `TicketTailor` - TicketTailor\n* `TickTick` - TickTick\n* `Timely` - Timely\n* `Tinyemail` - Tinyemail\n* `Todoist` - Todoist\n* `Toggl` - Toggl\n* `TrackPMS` - TrackPMS\n* `Tremendous` - Tremendous\n* `TrustPilot` - TrustPilot\n* `Twitter` - Twitter\n* `TyntecSMS` - TyntecSMS\n* `Unleash` - Unleash\n* `UpPromote` - UpPromote\n* `Uptick` - Uptick\n* `Uservoice` - Uservoice\n* `Vantage` - Vantage\n* `Veeqo` - Veeqo\n* `Vercel` - Vercel\n* `VismaEconomic` - VismaEconomic\n* `VWO` - VWO\n* `Waiteraid` - Waiteraid\n* `Wasabi` - Wasabi\n* `WhenIWork` - WhenIWork\n* `Wordpress` - Wordpress\n* `Workable` - Workable\n* `Workflowmax` - Workflowmax\n* `Workramp` - Workramp\n* `Wufoo` - Wufoo\n* `Xsolla` - Xsolla\n* `YandexMetrica` - YandexMetrica\n* `Yotpo` - Yotpo\n* `Ynab` - Ynab\n* `Younium` - Younium\n* `YouSign` - YouSign\n* `YoutubeData` - YoutubeData\n* `ZapierSupportedStorage` - ZapierSupportedStorage\n* `ZapSign` - ZapSign\n* `ZendeskSell` - ZendeskSell\n* `ZendeskSunshine` - ZendeskSunshine\n* `Zenefits` - Zenefits\n* `Zenloop` - Zenloop\n* `ZohoAnalytics` - ZohoAnalytics\n* `ZohoBigin` - ZohoBigin\n* `ZohoBilling` - ZohoBilling\n* `ZohoBooks` - ZohoBooks\n* `ZohoCampaign` - ZohoCampaign\n* `ZohoDesk` - ZohoDesk\n* `ZohoExpense` - ZohoExpense\n* `ZohoInventory` - ZohoInventory\n* `ZohoInvoice` - ZohoInvoice\n* `ZonkaFeedback` - ZonkaFeedback\n* `AlphaVantage` - AlphaVantage\n* `Aviationstack` - Aviationstack\n* `Bitly` - Bitly\n* `Blogger` - Blogger\n* `Breezometer` - Breezometer\n* `CareQualityCommission` - CareQualityCommission\n* `Cimis` - Cimis\n* `CoinApi` - CoinApi\n* `CoinGecko` - CoinGecko\n* `CoinMarketCap` - CoinMarketCap\n* `DingConnect` - DingConnect\n* `Dockerhub` - Dockerhub\n* `ExchangeRatesApi` - ExchangeRatesApi\n* `FinancialModelling` - FinancialModelling\n* `Finnhub` - Finnhub\n* `Finnworlds` - Finnworlds\n* `Giphy` - Giphy\n* `Gmail` - Gmail\n* `GNews` - GNews\n* `GoogleCalendar` - GoogleCalendar\n* `GoogleClassroom` - GoogleClassroom\n* `GoogleDirectory` - GoogleDirectory\n* `GoogleForms` - GoogleForms\n* `GooglePageSpeedInsights` - GooglePageSpeedInsights\n* `GoogleTasks` - GoogleTasks\n* `GoogleWebfonts` - GoogleWebfonts\n* `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports\n* `HuggingFace` - HuggingFace\n* `IlluminaBasespace` - IlluminaBasespace\n* `Imagga` - Imagga\n* `Interzoid` - Interzoid\n* `IP2Whois` - IP2Whois\n* `KYVE` - KYVE\n* `Marketstack` - Marketstack\n* `Mendeley` - Mendeley\n* `Nasa` - Nasa\n* `NewYorkTimes` - NewYorkTimes\n* `NewsApi` - NewsApi\n* `NewsData` - NewsData\n* `OpenDataDc` - OpenDataDc\n* `OpenExchangeRates` - OpenExchangeRates\n* `OpenAQ` - OpenAQ\n* `OpenFDA` - OpenFDA\n* `OpenWeather` - OpenWeather\n* `Outlook` - Outlook\n* `Perigon` - Perigon\n* `Pexels` - Pexels\n* `Pocket` - Pocket\n* `Polygon` - Polygon\n* `PyPI` - PyPI\n* `Recreation` - Recreation\n* `RKICovid` - RKICovid\n* `Rss` - Rss\n* `SimFin` - SimFin\n* `StockData` - StockData\n* `Guardian` - Guardian\n* `TMDb` - TMDb\n* `TVMaze` - TVMaze\n* `TwelveData` - TwelveData\n* `Ubidots` - Ubidots\n* `USCensus` - USCensus\n* `Watchmode` - Watchmode\n* `WikipediaPageviews` - WikipediaPageviews\n* `YahooFinance` - YahooFinance\n* `Clarifai` - Clarifai\n* `Adapty` - Adapty\n* `Braintrust` - Braintrust\n* `StreamElements` - StreamElements\n* `Streamlabs` - Streamlabs\n* `Datorama` - Datorama\n* `Ahrefs` - Ahrefs\n* `Lightfield` - Lightfield\n* `Appstack` - Appstack\n* `Razorpay` - Razorpay\n* `Neon` - Neon\n* `NewRelic` - NewRelic\n* `Custom` - Custom\n* `Tile38` - Tile38\n* `Chatwoot` - Chatwoot\n* `Sanity` - Sanity\n* `Metronome` - Metronome\n* `Jobber` - Jobber\n* `Knock` - Knock\n* `Leexi` - Leexi\n* `RB2B` - RB2B\n* `Superwall` - Superwall\n* `Liana` - Liana\n* `TawkTo` - TawkTo\n* `Hightouch` - Hightouch\n* `LemonSqueezy` - LemonSqueezy\n* `Ikas` - Ikas\n* `Talkwalker` - Talkwalker\n* `NextdoorAds` - NextdoorAds\n* `AppLovin` - AppLovin\n* `Baserow` - Baserow\n* `Plunk` - Plunk\n* `Dub` - Dub\n* `AirOps` - AirOps\n* `Podium` - Podium\n* `Loops` - Loops\n* `Redis` - Redis\n* `Mercury` - Mercury\n* `Gojiberry` - Gojiberry\n* `Teachable` - Teachable"
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
    direct_query_enabled: zod
        .boolean()
        .default(externalDataSourcesCreateBodyDirectQueryEnabledDefault)
        .describe(
            'Whether a synced source should also be live-queryable via direct connection. Defaults to true; ignored for pure direct-query sources.'
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
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to true for new sources; ignored for pure direct-query sources.'
            ),
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
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to true for new sources; ignored for pure direct-query sources.'
            ),
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
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to true for new sources; ignored for pure direct-query sources.'
            ),
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
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to true for new sources; ignored for pure direct-query sources.'
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
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to true for new sources; ignored for pure direct-query sources.'
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
        direct_query_enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this synced source is also live-queryable via direct connection. Defaults to true for new sources; ignored for pure direct-query sources.'
            ),
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

export const externalDataSourcesSetupCreateBodyDirectQueryEnabledDefault = true

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
            'OneHundredMs',
            'SevenShifts',
            'AcuityScheduling',
            'AgileCRM',
            'Aha',
            'Airbyte',
            'Akeneo',
            'Algolia',
            'AlpacaBrokerAPI',
            'ApifyDataset',
            'Appcues',
            'Appfigures',
            'Appfollow',
            'Apptivo',
            'AssemblyAI',
            'Awin',
            'AwsCloudTrail',
            'AzureTableStorage',
            'Babelforce',
            'Basecamp',
            'Beamer',
            'BigMailer',
            'Bluetally',
            'BoldSign',
            'BreezyHR',
            'Bugsnag',
            'Buildkite',
            'Bunny',
            'Buzzsprout',
            'CalCom',
            'CallRail',
            'Campayn',
            'Canny',
            'CapsuleCRM',
            'CaptainData',
            'CartCom',
            'CastorEDC',
            'Chameleon',
            'Chargedesk',
            'Chargify',
            'Chift',
            'Churnkey',
            'Cin7',
            'CiscoMeraki',
            'Clazar',
            'Clockify',
            'Clockodo',
            'Cloudbeds',
            'Coassemble',
            'Codefresh',
            'Concord',
            'ConfigCat',
            'Couchbase',
            'Curve',
            'Customerly',
            'Datascope',
            'Dbt',
            'Deputy',
            'DevinAI',
            'Docuseal',
            'Dolibarr',
            'Dremio',
            'DropboxSign',
            'Dwolla',
            'EConomic',
            'Easypost',
            'Easypromos',
            'Elasticemail',
            'EmailOctopus',
            'EmploymentHero',
            'Encharge',
            'Eventee',
            'Eventzilla',
            'Everhour',
            'EZOfficeInventory',
            'Factorial',
            'Fastbill',
            'Fastly',
            'Fauna',
            'Feishu',
            'Fillout',
            'Finage',
            'Firebolt',
            'FireHydrant',
            'Fleetio',
            'Flexmail',
            'Flexport',
            'FloatApp',
            'Flowlu',
            'Formbricks',
            'FreeAgent',
            'Freightview',
            'Freshcaller',
            'Freshchat',
            'Freshservice',
            'Fulcrum',
            'GainsightPx',
            'GitBook',
            'Glassfrog',
            'Goldcast',
            'GoLogin',
            'Grafana',
            'GreytHr',
            'Gridly',
            'Harness',
            'Height',
            'Hellobaton',
            'HighLevel',
            'HoorayHR',
            'Hubplanner',
            'Humanitix',
            'Huntr',
            'Inflowinventory',
            'InforNexus',
            'Insightful',
            'Insightly',
            'Instantly',
            'Instatus',
            'Intruder',
            'Invoiced',
            'Invoiceninja',
            'JamfPro',
            'JobNimbus',
            'Jotform',
            'JudgeMeReviews',
            'JustCall',
            'JustSift',
            'K6Cloud',
            'Katana',
            'Keka',
            'Kisi',
            'Kissmetrics',
            'Klarna',
            'Klaus',
            'Lago',
            'Leadfeeder',
            'Lemlist',
            'LessAnnoyingCRM',
            'LinkedinPages',
            'Linkrunner',
            'Linnworks',
            'Lob',
            'Lokalise',
            'Looker',
            'Luma',
            'MailerSend',
            'Mailosaur',
            'Mailtrap',
            'Mantle',
            'Mention',
            'MercadoAds',
            'Merge',
            'Metabase',
            'Metricool',
            'MicrosoftDataverse',
            'MicrosoftEntraId',
            'MicrosoftLists',
            'Miro',
            'Missive',
            'MixMax',
            'Mode',
            'Mux',
            'MyHours',
            'N8n',
            'Navan',
            'NebiusAI',
            'Nexiopay',
            'NinjaOneRMM',
            'NoCRM',
            'NorthpassLMS',
            'Nutshell',
            'Nylas',
            'Oncehub',
            'Onepagecrm',
            'OneSignal',
            'Onfleet',
            'OpinionStage',
            'OPUSWatch',
            'Orb',
            'Orbit',
            'Oura',
            'Oveit',
            'PabblySubscriptionsBilling',
            'Paperform',
            'Papersign',
            'Partnerize',
            'PartnerStack',
            'PayFit',
            'Paystack',
            'Pennylane',
            'Perk',
            'PersistIq',
            'Persona',
            'Phyllo',
            'Picqer',
            'Pipeliner',
            'PivotalTracker',
            'Piwik',
            'Planhat',
            'Plausible',
            'Poplar',
            'PrestaShop',
            'Pretix',
            'Primetric',
            'Printify',
            'Productive',
            'Pylon',
            'Qonto',
            'Qualaroo',
            'Railz',
            'RDStationMarketing',
            'Recruitee',
            'Reddit',
            'ReferralHero',
            'RentCast',
            'Repairshopr',
            'ReplyIo',
            'RetailExpress',
            'Retently',
            'RevolutMerchant',
            'RocketChat',
            'Rocketlane',
            'Rootly',
            'Ruddr',
            'SafetyCulture',
            'SageHR',
            'Salesflare',
            'SAPFieldglass',
            'SavvyCal',
            'Secoda',
            'Segment',
            'Sendowl',
            'SendPulse',
            'Senseforce',
            'Serpstat',
            'Sharetribe',
            'Shippo',
            'ShopWired',
            'Shortio',
            'Shutterstock',
            'SigmaComputing',
            'SignNow',
            'SimpleCast',
            'Simplesat',
            'Smaily',
            'SmartEngage',
            'Smartreach',
            'Smartwaiver',
            'SolarwindsServiceDesk',
            'SonarCloud',
            'SparkPost',
            'SplitIo',
            'SpotifyAds',
            'SpotlerCRM',
            'Squarespace',
            'Statsig',
            'Statuspage',
            'Stigg',
            'Strava',
            'SurveySparrow',
            'Survicate',
            'Svix',
            'Systeme',
            'Tavus',
            'Teamtailor',
            'Teamwork',
            'Tempo',
            'Testrail',
            'Thinkific',
            'ThinkificCourses',
            'ThriveLearning',
            'Ticketmaster',
            'TicketTailor',
            'TickTick',
            'Timely',
            'Tinyemail',
            'Todoist',
            'Toggl',
            'TrackPMS',
            'Tremendous',
            'TrustPilot',
            'Twitter',
            'TyntecSMS',
            'Unleash',
            'UpPromote',
            'Uptick',
            'Uservoice',
            'Vantage',
            'Veeqo',
            'Vercel',
            'VismaEconomic',
            'VWO',
            'Waiteraid',
            'Wasabi',
            'WhenIWork',
            'Wordpress',
            'Workable',
            'Workflowmax',
            'Workramp',
            'Wufoo',
            'Xsolla',
            'YandexMetrica',
            'Yotpo',
            'Ynab',
            'Younium',
            'YouSign',
            'YoutubeData',
            'ZapierSupportedStorage',
            'ZapSign',
            'ZendeskSell',
            'ZendeskSunshine',
            'Zenefits',
            'Zenloop',
            'ZohoAnalytics',
            'ZohoBigin',
            'ZohoBilling',
            'ZohoBooks',
            'ZohoCampaign',
            'ZohoDesk',
            'ZohoExpense',
            'ZohoInventory',
            'ZohoInvoice',
            'ZonkaFeedback',
            'AlphaVantage',
            'Aviationstack',
            'Bitly',
            'Blogger',
            'Breezometer',
            'CareQualityCommission',
            'Cimis',
            'CoinApi',
            'CoinGecko',
            'CoinMarketCap',
            'DingConnect',
            'Dockerhub',
            'ExchangeRatesApi',
            'FinancialModelling',
            'Finnhub',
            'Finnworlds',
            'Giphy',
            'Gmail',
            'GNews',
            'GoogleCalendar',
            'GoogleClassroom',
            'GoogleDirectory',
            'GoogleForms',
            'GooglePageSpeedInsights',
            'GoogleTasks',
            'GoogleWebfonts',
            'GoogleWorkspaceAdminReports',
            'HuggingFace',
            'IlluminaBasespace',
            'Imagga',
            'Interzoid',
            'IP2Whois',
            'KYVE',
            'Marketstack',
            'Mendeley',
            'Nasa',
            'NewYorkTimes',
            'NewsApi',
            'NewsData',
            'OpenDataDc',
            'OpenExchangeRates',
            'OpenAQ',
            'OpenFDA',
            'OpenWeather',
            'Outlook',
            'Perigon',
            'Pexels',
            'Pocket',
            'Polygon',
            'PyPI',
            'Recreation',
            'RKICovid',
            'Rss',
            'SimFin',
            'StockData',
            'Guardian',
            'TMDb',
            'TVMaze',
            'TwelveData',
            'Ubidots',
            'USCensus',
            'Watchmode',
            'WikipediaPageviews',
            'YahooFinance',
            'Clarifai',
            'Adapty',
            'Braintrust',
            'StreamElements',
            'Streamlabs',
            'Datorama',
            'Ahrefs',
            'Lightfield',
            'Appstack',
            'Razorpay',
            'Neon',
            'NewRelic',
            'Custom',
            'Tile38',
            'Chatwoot',
            'Sanity',
            'Metronome',
            'Jobber',
            'Knock',
            'Leexi',
            'RB2B',
            'Superwall',
            'Liana',
            'TawkTo',
            'Hightouch',
            'LemonSqueezy',
            'Ikas',
            'Talkwalker',
            'NextdoorAds',
            'AppLovin',
            'Baserow',
            'Plunk',
            'Dub',
            'AirOps',
            'Podium',
            'Loops',
            'Redis',
            'Mercury',
            'Gojiberry',
            'Teachable',
        ])
        .describe(
            '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `GoogleSearchConsole` - GoogleSearchConsole\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex\n* `ClickHouse` - ClickHouse\n* `Plain` - Plain\n* `Resend` - Resend\n* `PgAnalyze` - PgAnalyze\n* `WorkOS` - WorkOS\n* `AmazonS3` - AmazonS3\n* `GoogleCloudStorage` - GoogleCloudStorage\n* `Databricks` - Databricks\n* `Dynamics365` - Dynamics365\n* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n* `Db2` - Db2\n* `Heap` - Heap\n* `AdobeAnalytics` - AdobeAnalytics\n* `Matomo` - Matomo\n* `Optimizely` - Optimizely\n* `Adyen` - Adyen\n* `GoCardless` - GoCardless\n* `Mollie` - Mollie\n* `CheckoutCom` - CheckoutCom\n* `Branch` - Branch\n* `Criteo` - Criteo\n* `Outbrain` - Outbrain\n* `Taboola` - Taboola\n* `AdRoll` - AdRoll\n* `DisplayVideo360` - DisplayVideo360\n* `GoogleAdManager` - GoogleAdManager\n* `CampaignManager360` - CampaignManager360\n* `SearchAds360` - SearchAds360\n* `AdobeCommerce` - AdobeCommerce\n* `AmazonSellingPartner` - AmazonSellingPartner\n* `Ebay` - Ebay\n* `Commercetools` - Commercetools\n* `LightspeedRetail` - LightspeedRetail\n* `ShipStation` - ShipStation\n* `ConstantContact` - ConstantContact\n* `Mailgun` - Mailgun\n* `Eloqua` - Eloqua\n* `Sailthru` - Sailthru\n* `Ortto` - Ortto\n* `Attentive` - Attentive\n* `Kustomer` - Kustomer\n* `Dixa` - Dixa\n* `Gladly` - Gladly\n* `Qualtrics` - Qualtrics\n* `Delighted` - Delighted\n* `AzureDevOps` - AzureDevOps\n* `Rollbar` - Rollbar\n* `Opsgenie` - Opsgenie\n* `IncidentIo` - IncidentIo\n* `Pingdom` - Pingdom\n* `Cloudflare` - Cloudflare\n* `CosmosDB` - CosmosDB\n* `PlanetScale` - PlanetScale\n* `SapHana` - SapHana\n* `Rippling` - Rippling\n* `HiBob` - HiBob\n* `Personio` - Personio\n* `Deel` - Deel\n* `AdpWorkforceNow` - AdpWorkforceNow\n* `Paylocity` - Paylocity\n* `Gusto` - Gusto\n* `CultureAmp` - CultureAmp\n* `Lattice` - Lattice\n* `SageIntacct` - SageIntacct\n* `FreshBooks` - FreshBooks\n* `Expensify` - Expensify\n* `Ramp` - Ramp\n* `Brex` - Brex\n* `Coupa` - Coupa\n* `SapConcur` - SapConcur\n* `Apollo` - Apollo\n* `Crunchbase` - Crunchbase\n* `ZoomInfo` - ZoomInfo\n* `Clari` - Clari\n* `Chorus` - Chorus\n* `Coda` - Coda\n* `Guru` - Guru\n* `Dropbox` - Dropbox\n* `Docusign` - Docusign\n* `PandaDoc` - PandaDoc\n* `SapErp` - SapErp\n* `SapSuccessFactors` - SapSuccessFactors\n* `OracleEbs` - OracleEbs\n* `OracleFusion` - OracleFusion\n* `AmazonSNS` - AmazonSNS\n* `AmazonEventBridge` - AmazonEventBridge\n* `AmazonSQS` - AmazonSQS\n* `AmazonKinesis` - AmazonKinesis\n* `AmazonCloudWatch` - AmazonCloudWatch\n* `OpenAIAds` - OpenAIAds\n* `OneHundredMs` - OneHundredMs\n* `SevenShifts` - SevenShifts\n* `AcuityScheduling` - AcuityScheduling\n* `AgileCRM` - AgileCRM\n* `Aha` - Aha\n* `Airbyte` - Airbyte\n* `Akeneo` - Akeneo\n* `Algolia` - Algolia\n* `AlpacaBrokerAPI` - AlpacaBrokerAPI\n* `ApifyDataset` - ApifyDataset\n* `Appcues` - Appcues\n* `Appfigures` - Appfigures\n* `Appfollow` - Appfollow\n* `Apptivo` - Apptivo\n* `AssemblyAI` - AssemblyAI\n* `Awin` - Awin\n* `AwsCloudTrail` - AwsCloudTrail\n* `AzureTableStorage` - AzureTableStorage\n* `Babelforce` - Babelforce\n* `Basecamp` - Basecamp\n* `Beamer` - Beamer\n* `BigMailer` - BigMailer\n* `Bluetally` - Bluetally\n* `BoldSign` - BoldSign\n* `BreezyHR` - BreezyHR\n* `Bugsnag` - Bugsnag\n* `Buildkite` - Buildkite\n* `Bunny` - Bunny\n* `Buzzsprout` - Buzzsprout\n* `CalCom` - CalCom\n* `CallRail` - CallRail\n* `Campayn` - Campayn\n* `Canny` - Canny\n* `CapsuleCRM` - CapsuleCRM\n* `CaptainData` - CaptainData\n* `CartCom` - CartCom\n* `CastorEDC` - CastorEDC\n* `Chameleon` - Chameleon\n* `Chargedesk` - Chargedesk\n* `Chargify` - Chargify\n* `Chift` - Chift\n* `Churnkey` - Churnkey\n* `Cin7` - Cin7\n* `CiscoMeraki` - CiscoMeraki\n* `Clazar` - Clazar\n* `Clockify` - Clockify\n* `Clockodo` - Clockodo\n* `Cloudbeds` - Cloudbeds\n* `Coassemble` - Coassemble\n* `Codefresh` - Codefresh\n* `Concord` - Concord\n* `ConfigCat` - ConfigCat\n* `Couchbase` - Couchbase\n* `Curve` - Curve\n* `Customerly` - Customerly\n* `Datascope` - Datascope\n* `Dbt` - Dbt\n* `Deputy` - Deputy\n* `DevinAI` - DevinAI\n* `Docuseal` - Docuseal\n* `Dolibarr` - Dolibarr\n* `Dremio` - Dremio\n* `DropboxSign` - DropboxSign\n* `Dwolla` - Dwolla\n* `EConomic` - EConomic\n* `Easypost` - Easypost\n* `Easypromos` - Easypromos\n* `Elasticemail` - Elasticemail\n* `EmailOctopus` - EmailOctopus\n* `EmploymentHero` - EmploymentHero\n* `Encharge` - Encharge\n* `Eventee` - Eventee\n* `Eventzilla` - Eventzilla\n* `Everhour` - Everhour\n* `EZOfficeInventory` - EZOfficeInventory\n* `Factorial` - Factorial\n* `Fastbill` - Fastbill\n* `Fastly` - Fastly\n* `Fauna` - Fauna\n* `Feishu` - Feishu\n* `Fillout` - Fillout\n* `Finage` - Finage\n* `Firebolt` - Firebolt\n* `FireHydrant` - FireHydrant\n* `Fleetio` - Fleetio\n* `Flexmail` - Flexmail\n* `Flexport` - Flexport\n* `FloatApp` - FloatApp\n* `Flowlu` - Flowlu\n* `Formbricks` - Formbricks\n* `FreeAgent` - FreeAgent\n* `Freightview` - Freightview\n* `Freshcaller` - Freshcaller\n* `Freshchat` - Freshchat\n* `Freshservice` - Freshservice\n* `Fulcrum` - Fulcrum\n* `GainsightPx` - GainsightPx\n* `GitBook` - GitBook\n* `Glassfrog` - Glassfrog\n* `Goldcast` - Goldcast\n* `GoLogin` - GoLogin\n* `Grafana` - Grafana\n* `GreytHr` - GreytHr\n* `Gridly` - Gridly\n* `Harness` - Harness\n* `Height` - Height\n* `Hellobaton` - Hellobaton\n* `HighLevel` - HighLevel\n* `HoorayHR` - HoorayHR\n* `Hubplanner` - Hubplanner\n* `Humanitix` - Humanitix\n* `Huntr` - Huntr\n* `Inflowinventory` - Inflowinventory\n* `InforNexus` - InforNexus\n* `Insightful` - Insightful\n* `Insightly` - Insightly\n* `Instantly` - Instantly\n* `Instatus` - Instatus\n* `Intruder` - Intruder\n* `Invoiced` - Invoiced\n* `Invoiceninja` - Invoiceninja\n* `JamfPro` - JamfPro\n* `JobNimbus` - JobNimbus\n* `Jotform` - Jotform\n* `JudgeMeReviews` - JudgeMeReviews\n* `JustCall` - JustCall\n* `JustSift` - JustSift\n* `K6Cloud` - K6Cloud\n* `Katana` - Katana\n* `Keka` - Keka\n* `Kisi` - Kisi\n* `Kissmetrics` - Kissmetrics\n* `Klarna` - Klarna\n* `Klaus` - Klaus\n* `Lago` - Lago\n* `Leadfeeder` - Leadfeeder\n* `Lemlist` - Lemlist\n* `LessAnnoyingCRM` - LessAnnoyingCRM\n* `LinkedinPages` - LinkedinPages\n* `Linkrunner` - Linkrunner\n* `Linnworks` - Linnworks\n* `Lob` - Lob\n* `Lokalise` - Lokalise\n* `Looker` - Looker\n* `Luma` - Luma\n* `MailerSend` - MailerSend\n* `Mailosaur` - Mailosaur\n* `Mailtrap` - Mailtrap\n* `Mantle` - Mantle\n* `Mention` - Mention\n* `MercadoAds` - MercadoAds\n* `Merge` - Merge\n* `Metabase` - Metabase\n* `Metricool` - Metricool\n* `MicrosoftDataverse` - MicrosoftDataverse\n* `MicrosoftEntraId` - MicrosoftEntraId\n* `MicrosoftLists` - MicrosoftLists\n* `Miro` - Miro\n* `Missive` - Missive\n* `MixMax` - MixMax\n* `Mode` - Mode\n* `Mux` - Mux\n* `MyHours` - MyHours\n* `N8n` - N8n\n* `Navan` - Navan\n* `NebiusAI` - NebiusAI\n* `Nexiopay` - Nexiopay\n* `NinjaOneRMM` - NinjaOneRMM\n* `NoCRM` - NoCRM\n* `NorthpassLMS` - NorthpassLMS\n* `Nutshell` - Nutshell\n* `Nylas` - Nylas\n* `Oncehub` - Oncehub\n* `Onepagecrm` - Onepagecrm\n* `OneSignal` - OneSignal\n* `Onfleet` - Onfleet\n* `OpinionStage` - OpinionStage\n* `OPUSWatch` - OPUSWatch\n* `Orb` - Orb\n* `Orbit` - Orbit\n* `Oura` - Oura\n* `Oveit` - Oveit\n* `PabblySubscriptionsBilling` - PabblySubscriptionsBilling\n* `Paperform` - Paperform\n* `Papersign` - Papersign\n* `Partnerize` - Partnerize\n* `PartnerStack` - PartnerStack\n* `PayFit` - PayFit\n* `Paystack` - Paystack\n* `Pennylane` - Pennylane\n* `Perk` - Perk\n* `PersistIq` - PersistIq\n* `Persona` - Persona\n* `Phyllo` - Phyllo\n* `Picqer` - Picqer\n* `Pipeliner` - Pipeliner\n* `PivotalTracker` - PivotalTracker\n* `Piwik` - Piwik\n* `Planhat` - Planhat\n* `Plausible` - Plausible\n* `Poplar` - Poplar\n* `PrestaShop` - PrestaShop\n* `Pretix` - Pretix\n* `Primetric` - Primetric\n* `Printify` - Printify\n* `Productive` - Productive\n* `Pylon` - Pylon\n* `Qonto` - Qonto\n* `Qualaroo` - Qualaroo\n* `Railz` - Railz\n* `RDStationMarketing` - RDStationMarketing\n* `Recruitee` - Recruitee\n* `Reddit` - Reddit\n* `ReferralHero` - ReferralHero\n* `RentCast` - RentCast\n* `Repairshopr` - Repairshopr\n* `ReplyIo` - ReplyIo\n* `RetailExpress` - RetailExpress\n* `Retently` - Retently\n* `RevolutMerchant` - RevolutMerchant\n* `RocketChat` - RocketChat\n* `Rocketlane` - Rocketlane\n* `Rootly` - Rootly\n* `Ruddr` - Ruddr\n* `SafetyCulture` - SafetyCulture\n* `SageHR` - SageHR\n* `Salesflare` - Salesflare\n* `SAPFieldglass` - SAPFieldglass\n* `SavvyCal` - SavvyCal\n* `Secoda` - Secoda\n* `Segment` - Segment\n* `Sendowl` - Sendowl\n* `SendPulse` - SendPulse\n* `Senseforce` - Senseforce\n* `Serpstat` - Serpstat\n* `Sharetribe` - Sharetribe\n* `Shippo` - Shippo\n* `ShopWired` - ShopWired\n* `Shortio` - Shortio\n* `Shutterstock` - Shutterstock\n* `SigmaComputing` - SigmaComputing\n* `SignNow` - SignNow\n* `SimpleCast` - SimpleCast\n* `Simplesat` - Simplesat\n* `Smaily` - Smaily\n* `SmartEngage` - SmartEngage\n* `Smartreach` - Smartreach\n* `Smartwaiver` - Smartwaiver\n* `SolarwindsServiceDesk` - SolarwindsServiceDesk\n* `SonarCloud` - SonarCloud\n* `SparkPost` - SparkPost\n* `SplitIo` - SplitIo\n* `SpotifyAds` - SpotifyAds\n* `SpotlerCRM` - SpotlerCRM\n* `Squarespace` - Squarespace\n* `Statsig` - Statsig\n* `Statuspage` - Statuspage\n* `Stigg` - Stigg\n* `Strava` - Strava\n* `SurveySparrow` - SurveySparrow\n* `Survicate` - Survicate\n* `Svix` - Svix\n* `Systeme` - Systeme\n* `Tavus` - Tavus\n* `Teamtailor` - Teamtailor\n* `Teamwork` - Teamwork\n* `Tempo` - Tempo\n* `Testrail` - Testrail\n* `Thinkific` - Thinkific\n* `ThinkificCourses` - ThinkificCourses\n* `ThriveLearning` - ThriveLearning\n* `Ticketmaster` - Ticketmaster\n* `TicketTailor` - TicketTailor\n* `TickTick` - TickTick\n* `Timely` - Timely\n* `Tinyemail` - Tinyemail\n* `Todoist` - Todoist\n* `Toggl` - Toggl\n* `TrackPMS` - TrackPMS\n* `Tremendous` - Tremendous\n* `TrustPilot` - TrustPilot\n* `Twitter` - Twitter\n* `TyntecSMS` - TyntecSMS\n* `Unleash` - Unleash\n* `UpPromote` - UpPromote\n* `Uptick` - Uptick\n* `Uservoice` - Uservoice\n* `Vantage` - Vantage\n* `Veeqo` - Veeqo\n* `Vercel` - Vercel\n* `VismaEconomic` - VismaEconomic\n* `VWO` - VWO\n* `Waiteraid` - Waiteraid\n* `Wasabi` - Wasabi\n* `WhenIWork` - WhenIWork\n* `Wordpress` - Wordpress\n* `Workable` - Workable\n* `Workflowmax` - Workflowmax\n* `Workramp` - Workramp\n* `Wufoo` - Wufoo\n* `Xsolla` - Xsolla\n* `YandexMetrica` - YandexMetrica\n* `Yotpo` - Yotpo\n* `Ynab` - Ynab\n* `Younium` - Younium\n* `YouSign` - YouSign\n* `YoutubeData` - YoutubeData\n* `ZapierSupportedStorage` - ZapierSupportedStorage\n* `ZapSign` - ZapSign\n* `ZendeskSell` - ZendeskSell\n* `ZendeskSunshine` - ZendeskSunshine\n* `Zenefits` - Zenefits\n* `Zenloop` - Zenloop\n* `ZohoAnalytics` - ZohoAnalytics\n* `ZohoBigin` - ZohoBigin\n* `ZohoBilling` - ZohoBilling\n* `ZohoBooks` - ZohoBooks\n* `ZohoCampaign` - ZohoCampaign\n* `ZohoDesk` - ZohoDesk\n* `ZohoExpense` - ZohoExpense\n* `ZohoInventory` - ZohoInventory\n* `ZohoInvoice` - ZohoInvoice\n* `ZonkaFeedback` - ZonkaFeedback\n* `AlphaVantage` - AlphaVantage\n* `Aviationstack` - Aviationstack\n* `Bitly` - Bitly\n* `Blogger` - Blogger\n* `Breezometer` - Breezometer\n* `CareQualityCommission` - CareQualityCommission\n* `Cimis` - Cimis\n* `CoinApi` - CoinApi\n* `CoinGecko` - CoinGecko\n* `CoinMarketCap` - CoinMarketCap\n* `DingConnect` - DingConnect\n* `Dockerhub` - Dockerhub\n* `ExchangeRatesApi` - ExchangeRatesApi\n* `FinancialModelling` - FinancialModelling\n* `Finnhub` - Finnhub\n* `Finnworlds` - Finnworlds\n* `Giphy` - Giphy\n* `Gmail` - Gmail\n* `GNews` - GNews\n* `GoogleCalendar` - GoogleCalendar\n* `GoogleClassroom` - GoogleClassroom\n* `GoogleDirectory` - GoogleDirectory\n* `GoogleForms` - GoogleForms\n* `GooglePageSpeedInsights` - GooglePageSpeedInsights\n* `GoogleTasks` - GoogleTasks\n* `GoogleWebfonts` - GoogleWebfonts\n* `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports\n* `HuggingFace` - HuggingFace\n* `IlluminaBasespace` - IlluminaBasespace\n* `Imagga` - Imagga\n* `Interzoid` - Interzoid\n* `IP2Whois` - IP2Whois\n* `KYVE` - KYVE\n* `Marketstack` - Marketstack\n* `Mendeley` - Mendeley\n* `Nasa` - Nasa\n* `NewYorkTimes` - NewYorkTimes\n* `NewsApi` - NewsApi\n* `NewsData` - NewsData\n* `OpenDataDc` - OpenDataDc\n* `OpenExchangeRates` - OpenExchangeRates\n* `OpenAQ` - OpenAQ\n* `OpenFDA` - OpenFDA\n* `OpenWeather` - OpenWeather\n* `Outlook` - Outlook\n* `Perigon` - Perigon\n* `Pexels` - Pexels\n* `Pocket` - Pocket\n* `Polygon` - Polygon\n* `PyPI` - PyPI\n* `Recreation` - Recreation\n* `RKICovid` - RKICovid\n* `Rss` - Rss\n* `SimFin` - SimFin\n* `StockData` - StockData\n* `Guardian` - Guardian\n* `TMDb` - TMDb\n* `TVMaze` - TVMaze\n* `TwelveData` - TwelveData\n* `Ubidots` - Ubidots\n* `USCensus` - USCensus\n* `Watchmode` - Watchmode\n* `WikipediaPageviews` - WikipediaPageviews\n* `YahooFinance` - YahooFinance\n* `Clarifai` - Clarifai\n* `Adapty` - Adapty\n* `Braintrust` - Braintrust\n* `StreamElements` - StreamElements\n* `Streamlabs` - Streamlabs\n* `Datorama` - Datorama\n* `Ahrefs` - Ahrefs\n* `Lightfield` - Lightfield\n* `Appstack` - Appstack\n* `Razorpay` - Razorpay\n* `Neon` - Neon\n* `NewRelic` - NewRelic\n* `Custom` - Custom\n* `Tile38` - Tile38\n* `Chatwoot` - Chatwoot\n* `Sanity` - Sanity\n* `Metronome` - Metronome\n* `Jobber` - Jobber\n* `Knock` - Knock\n* `Leexi` - Leexi\n* `RB2B` - RB2B\n* `Superwall` - Superwall\n* `Liana` - Liana\n* `TawkTo` - TawkTo\n* `Hightouch` - Hightouch\n* `LemonSqueezy` - LemonSqueezy\n* `Ikas` - Ikas\n* `Talkwalker` - Talkwalker\n* `NextdoorAds` - NextdoorAds\n* `AppLovin` - AppLovin\n* `Baserow` - Baserow\n* `Plunk` - Plunk\n* `Dub` - Dub\n* `AirOps` - AirOps\n* `Podium` - Podium\n* `Loops` - Loops\n* `Redis` - Redis\n* `Mercury` - Mercury\n* `Gojiberry` - Gojiberry\n* `Teachable` - Teachable'
        )
        .describe(
            "The source type to set up (e.g. 'Stripe', 'Postgres', 'Hubspot').\n\n* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `GoogleSearchConsole` - GoogleSearchConsole\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex\n* `ClickHouse` - ClickHouse\n* `Plain` - Plain\n* `Resend` - Resend\n* `PgAnalyze` - PgAnalyze\n* `WorkOS` - WorkOS\n* `AmazonS3` - AmazonS3\n* `GoogleCloudStorage` - GoogleCloudStorage\n* `Databricks` - Databricks\n* `Dynamics365` - Dynamics365\n* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n* `Db2` - Db2\n* `Heap` - Heap\n* `AdobeAnalytics` - AdobeAnalytics\n* `Matomo` - Matomo\n* `Optimizely` - Optimizely\n* `Adyen` - Adyen\n* `GoCardless` - GoCardless\n* `Mollie` - Mollie\n* `CheckoutCom` - CheckoutCom\n* `Branch` - Branch\n* `Criteo` - Criteo\n* `Outbrain` - Outbrain\n* `Taboola` - Taboola\n* `AdRoll` - AdRoll\n* `DisplayVideo360` - DisplayVideo360\n* `GoogleAdManager` - GoogleAdManager\n* `CampaignManager360` - CampaignManager360\n* `SearchAds360` - SearchAds360\n* `AdobeCommerce` - AdobeCommerce\n* `AmazonSellingPartner` - AmazonSellingPartner\n* `Ebay` - Ebay\n* `Commercetools` - Commercetools\n* `LightspeedRetail` - LightspeedRetail\n* `ShipStation` - ShipStation\n* `ConstantContact` - ConstantContact\n* `Mailgun` - Mailgun\n* `Eloqua` - Eloqua\n* `Sailthru` - Sailthru\n* `Ortto` - Ortto\n* `Attentive` - Attentive\n* `Kustomer` - Kustomer\n* `Dixa` - Dixa\n* `Gladly` - Gladly\n* `Qualtrics` - Qualtrics\n* `Delighted` - Delighted\n* `AzureDevOps` - AzureDevOps\n* `Rollbar` - Rollbar\n* `Opsgenie` - Opsgenie\n* `IncidentIo` - IncidentIo\n* `Pingdom` - Pingdom\n* `Cloudflare` - Cloudflare\n* `CosmosDB` - CosmosDB\n* `PlanetScale` - PlanetScale\n* `SapHana` - SapHana\n* `Rippling` - Rippling\n* `HiBob` - HiBob\n* `Personio` - Personio\n* `Deel` - Deel\n* `AdpWorkforceNow` - AdpWorkforceNow\n* `Paylocity` - Paylocity\n* `Gusto` - Gusto\n* `CultureAmp` - CultureAmp\n* `Lattice` - Lattice\n* `SageIntacct` - SageIntacct\n* `FreshBooks` - FreshBooks\n* `Expensify` - Expensify\n* `Ramp` - Ramp\n* `Brex` - Brex\n* `Coupa` - Coupa\n* `SapConcur` - SapConcur\n* `Apollo` - Apollo\n* `Crunchbase` - Crunchbase\n* `ZoomInfo` - ZoomInfo\n* `Clari` - Clari\n* `Chorus` - Chorus\n* `Coda` - Coda\n* `Guru` - Guru\n* `Dropbox` - Dropbox\n* `Docusign` - Docusign\n* `PandaDoc` - PandaDoc\n* `SapErp` - SapErp\n* `SapSuccessFactors` - SapSuccessFactors\n* `OracleEbs` - OracleEbs\n* `OracleFusion` - OracleFusion\n* `AmazonSNS` - AmazonSNS\n* `AmazonEventBridge` - AmazonEventBridge\n* `AmazonSQS` - AmazonSQS\n* `AmazonKinesis` - AmazonKinesis\n* `AmazonCloudWatch` - AmazonCloudWatch\n* `OpenAIAds` - OpenAIAds\n* `OneHundredMs` - OneHundredMs\n* `SevenShifts` - SevenShifts\n* `AcuityScheduling` - AcuityScheduling\n* `AgileCRM` - AgileCRM\n* `Aha` - Aha\n* `Airbyte` - Airbyte\n* `Akeneo` - Akeneo\n* `Algolia` - Algolia\n* `AlpacaBrokerAPI` - AlpacaBrokerAPI\n* `ApifyDataset` - ApifyDataset\n* `Appcues` - Appcues\n* `Appfigures` - Appfigures\n* `Appfollow` - Appfollow\n* `Apptivo` - Apptivo\n* `AssemblyAI` - AssemblyAI\n* `Awin` - Awin\n* `AwsCloudTrail` - AwsCloudTrail\n* `AzureTableStorage` - AzureTableStorage\n* `Babelforce` - Babelforce\n* `Basecamp` - Basecamp\n* `Beamer` - Beamer\n* `BigMailer` - BigMailer\n* `Bluetally` - Bluetally\n* `BoldSign` - BoldSign\n* `BreezyHR` - BreezyHR\n* `Bugsnag` - Bugsnag\n* `Buildkite` - Buildkite\n* `Bunny` - Bunny\n* `Buzzsprout` - Buzzsprout\n* `CalCom` - CalCom\n* `CallRail` - CallRail\n* `Campayn` - Campayn\n* `Canny` - Canny\n* `CapsuleCRM` - CapsuleCRM\n* `CaptainData` - CaptainData\n* `CartCom` - CartCom\n* `CastorEDC` - CastorEDC\n* `Chameleon` - Chameleon\n* `Chargedesk` - Chargedesk\n* `Chargify` - Chargify\n* `Chift` - Chift\n* `Churnkey` - Churnkey\n* `Cin7` - Cin7\n* `CiscoMeraki` - CiscoMeraki\n* `Clazar` - Clazar\n* `Clockify` - Clockify\n* `Clockodo` - Clockodo\n* `Cloudbeds` - Cloudbeds\n* `Coassemble` - Coassemble\n* `Codefresh` - Codefresh\n* `Concord` - Concord\n* `ConfigCat` - ConfigCat\n* `Couchbase` - Couchbase\n* `Curve` - Curve\n* `Customerly` - Customerly\n* `Datascope` - Datascope\n* `Dbt` - Dbt\n* `Deputy` - Deputy\n* `DevinAI` - DevinAI\n* `Docuseal` - Docuseal\n* `Dolibarr` - Dolibarr\n* `Dremio` - Dremio\n* `DropboxSign` - DropboxSign\n* `Dwolla` - Dwolla\n* `EConomic` - EConomic\n* `Easypost` - Easypost\n* `Easypromos` - Easypromos\n* `Elasticemail` - Elasticemail\n* `EmailOctopus` - EmailOctopus\n* `EmploymentHero` - EmploymentHero\n* `Encharge` - Encharge\n* `Eventee` - Eventee\n* `Eventzilla` - Eventzilla\n* `Everhour` - Everhour\n* `EZOfficeInventory` - EZOfficeInventory\n* `Factorial` - Factorial\n* `Fastbill` - Fastbill\n* `Fastly` - Fastly\n* `Fauna` - Fauna\n* `Feishu` - Feishu\n* `Fillout` - Fillout\n* `Finage` - Finage\n* `Firebolt` - Firebolt\n* `FireHydrant` - FireHydrant\n* `Fleetio` - Fleetio\n* `Flexmail` - Flexmail\n* `Flexport` - Flexport\n* `FloatApp` - FloatApp\n* `Flowlu` - Flowlu\n* `Formbricks` - Formbricks\n* `FreeAgent` - FreeAgent\n* `Freightview` - Freightview\n* `Freshcaller` - Freshcaller\n* `Freshchat` - Freshchat\n* `Freshservice` - Freshservice\n* `Fulcrum` - Fulcrum\n* `GainsightPx` - GainsightPx\n* `GitBook` - GitBook\n* `Glassfrog` - Glassfrog\n* `Goldcast` - Goldcast\n* `GoLogin` - GoLogin\n* `Grafana` - Grafana\n* `GreytHr` - GreytHr\n* `Gridly` - Gridly\n* `Harness` - Harness\n* `Height` - Height\n* `Hellobaton` - Hellobaton\n* `HighLevel` - HighLevel\n* `HoorayHR` - HoorayHR\n* `Hubplanner` - Hubplanner\n* `Humanitix` - Humanitix\n* `Huntr` - Huntr\n* `Inflowinventory` - Inflowinventory\n* `InforNexus` - InforNexus\n* `Insightful` - Insightful\n* `Insightly` - Insightly\n* `Instantly` - Instantly\n* `Instatus` - Instatus\n* `Intruder` - Intruder\n* `Invoiced` - Invoiced\n* `Invoiceninja` - Invoiceninja\n* `JamfPro` - JamfPro\n* `JobNimbus` - JobNimbus\n* `Jotform` - Jotform\n* `JudgeMeReviews` - JudgeMeReviews\n* `JustCall` - JustCall\n* `JustSift` - JustSift\n* `K6Cloud` - K6Cloud\n* `Katana` - Katana\n* `Keka` - Keka\n* `Kisi` - Kisi\n* `Kissmetrics` - Kissmetrics\n* `Klarna` - Klarna\n* `Klaus` - Klaus\n* `Lago` - Lago\n* `Leadfeeder` - Leadfeeder\n* `Lemlist` - Lemlist\n* `LessAnnoyingCRM` - LessAnnoyingCRM\n* `LinkedinPages` - LinkedinPages\n* `Linkrunner` - Linkrunner\n* `Linnworks` - Linnworks\n* `Lob` - Lob\n* `Lokalise` - Lokalise\n* `Looker` - Looker\n* `Luma` - Luma\n* `MailerSend` - MailerSend\n* `Mailosaur` - Mailosaur\n* `Mailtrap` - Mailtrap\n* `Mantle` - Mantle\n* `Mention` - Mention\n* `MercadoAds` - MercadoAds\n* `Merge` - Merge\n* `Metabase` - Metabase\n* `Metricool` - Metricool\n* `MicrosoftDataverse` - MicrosoftDataverse\n* `MicrosoftEntraId` - MicrosoftEntraId\n* `MicrosoftLists` - MicrosoftLists\n* `Miro` - Miro\n* `Missive` - Missive\n* `MixMax` - MixMax\n* `Mode` - Mode\n* `Mux` - Mux\n* `MyHours` - MyHours\n* `N8n` - N8n\n* `Navan` - Navan\n* `NebiusAI` - NebiusAI\n* `Nexiopay` - Nexiopay\n* `NinjaOneRMM` - NinjaOneRMM\n* `NoCRM` - NoCRM\n* `NorthpassLMS` - NorthpassLMS\n* `Nutshell` - Nutshell\n* `Nylas` - Nylas\n* `Oncehub` - Oncehub\n* `Onepagecrm` - Onepagecrm\n* `OneSignal` - OneSignal\n* `Onfleet` - Onfleet\n* `OpinionStage` - OpinionStage\n* `OPUSWatch` - OPUSWatch\n* `Orb` - Orb\n* `Orbit` - Orbit\n* `Oura` - Oura\n* `Oveit` - Oveit\n* `PabblySubscriptionsBilling` - PabblySubscriptionsBilling\n* `Paperform` - Paperform\n* `Papersign` - Papersign\n* `Partnerize` - Partnerize\n* `PartnerStack` - PartnerStack\n* `PayFit` - PayFit\n* `Paystack` - Paystack\n* `Pennylane` - Pennylane\n* `Perk` - Perk\n* `PersistIq` - PersistIq\n* `Persona` - Persona\n* `Phyllo` - Phyllo\n* `Picqer` - Picqer\n* `Pipeliner` - Pipeliner\n* `PivotalTracker` - PivotalTracker\n* `Piwik` - Piwik\n* `Planhat` - Planhat\n* `Plausible` - Plausible\n* `Poplar` - Poplar\n* `PrestaShop` - PrestaShop\n* `Pretix` - Pretix\n* `Primetric` - Primetric\n* `Printify` - Printify\n* `Productive` - Productive\n* `Pylon` - Pylon\n* `Qonto` - Qonto\n* `Qualaroo` - Qualaroo\n* `Railz` - Railz\n* `RDStationMarketing` - RDStationMarketing\n* `Recruitee` - Recruitee\n* `Reddit` - Reddit\n* `ReferralHero` - ReferralHero\n* `RentCast` - RentCast\n* `Repairshopr` - Repairshopr\n* `ReplyIo` - ReplyIo\n* `RetailExpress` - RetailExpress\n* `Retently` - Retently\n* `RevolutMerchant` - RevolutMerchant\n* `RocketChat` - RocketChat\n* `Rocketlane` - Rocketlane\n* `Rootly` - Rootly\n* `Ruddr` - Ruddr\n* `SafetyCulture` - SafetyCulture\n* `SageHR` - SageHR\n* `Salesflare` - Salesflare\n* `SAPFieldglass` - SAPFieldglass\n* `SavvyCal` - SavvyCal\n* `Secoda` - Secoda\n* `Segment` - Segment\n* `Sendowl` - Sendowl\n* `SendPulse` - SendPulse\n* `Senseforce` - Senseforce\n* `Serpstat` - Serpstat\n* `Sharetribe` - Sharetribe\n* `Shippo` - Shippo\n* `ShopWired` - ShopWired\n* `Shortio` - Shortio\n* `Shutterstock` - Shutterstock\n* `SigmaComputing` - SigmaComputing\n* `SignNow` - SignNow\n* `SimpleCast` - SimpleCast\n* `Simplesat` - Simplesat\n* `Smaily` - Smaily\n* `SmartEngage` - SmartEngage\n* `Smartreach` - Smartreach\n* `Smartwaiver` - Smartwaiver\n* `SolarwindsServiceDesk` - SolarwindsServiceDesk\n* `SonarCloud` - SonarCloud\n* `SparkPost` - SparkPost\n* `SplitIo` - SplitIo\n* `SpotifyAds` - SpotifyAds\n* `SpotlerCRM` - SpotlerCRM\n* `Squarespace` - Squarespace\n* `Statsig` - Statsig\n* `Statuspage` - Statuspage\n* `Stigg` - Stigg\n* `Strava` - Strava\n* `SurveySparrow` - SurveySparrow\n* `Survicate` - Survicate\n* `Svix` - Svix\n* `Systeme` - Systeme\n* `Tavus` - Tavus\n* `Teamtailor` - Teamtailor\n* `Teamwork` - Teamwork\n* `Tempo` - Tempo\n* `Testrail` - Testrail\n* `Thinkific` - Thinkific\n* `ThinkificCourses` - ThinkificCourses\n* `ThriveLearning` - ThriveLearning\n* `Ticketmaster` - Ticketmaster\n* `TicketTailor` - TicketTailor\n* `TickTick` - TickTick\n* `Timely` - Timely\n* `Tinyemail` - Tinyemail\n* `Todoist` - Todoist\n* `Toggl` - Toggl\n* `TrackPMS` - TrackPMS\n* `Tremendous` - Tremendous\n* `TrustPilot` - TrustPilot\n* `Twitter` - Twitter\n* `TyntecSMS` - TyntecSMS\n* `Unleash` - Unleash\n* `UpPromote` - UpPromote\n* `Uptick` - Uptick\n* `Uservoice` - Uservoice\n* `Vantage` - Vantage\n* `Veeqo` - Veeqo\n* `Vercel` - Vercel\n* `VismaEconomic` - VismaEconomic\n* `VWO` - VWO\n* `Waiteraid` - Waiteraid\n* `Wasabi` - Wasabi\n* `WhenIWork` - WhenIWork\n* `Wordpress` - Wordpress\n* `Workable` - Workable\n* `Workflowmax` - Workflowmax\n* `Workramp` - Workramp\n* `Wufoo` - Wufoo\n* `Xsolla` - Xsolla\n* `YandexMetrica` - YandexMetrica\n* `Yotpo` - Yotpo\n* `Ynab` - Ynab\n* `Younium` - Younium\n* `YouSign` - YouSign\n* `YoutubeData` - YoutubeData\n* `ZapierSupportedStorage` - ZapierSupportedStorage\n* `ZapSign` - ZapSign\n* `ZendeskSell` - ZendeskSell\n* `ZendeskSunshine` - ZendeskSunshine\n* `Zenefits` - Zenefits\n* `Zenloop` - Zenloop\n* `ZohoAnalytics` - ZohoAnalytics\n* `ZohoBigin` - ZohoBigin\n* `ZohoBilling` - ZohoBilling\n* `ZohoBooks` - ZohoBooks\n* `ZohoCampaign` - ZohoCampaign\n* `ZohoDesk` - ZohoDesk\n* `ZohoExpense` - ZohoExpense\n* `ZohoInventory` - ZohoInventory\n* `ZohoInvoice` - ZohoInvoice\n* `ZonkaFeedback` - ZonkaFeedback\n* `AlphaVantage` - AlphaVantage\n* `Aviationstack` - Aviationstack\n* `Bitly` - Bitly\n* `Blogger` - Blogger\n* `Breezometer` - Breezometer\n* `CareQualityCommission` - CareQualityCommission\n* `Cimis` - Cimis\n* `CoinApi` - CoinApi\n* `CoinGecko` - CoinGecko\n* `CoinMarketCap` - CoinMarketCap\n* `DingConnect` - DingConnect\n* `Dockerhub` - Dockerhub\n* `ExchangeRatesApi` - ExchangeRatesApi\n* `FinancialModelling` - FinancialModelling\n* `Finnhub` - Finnhub\n* `Finnworlds` - Finnworlds\n* `Giphy` - Giphy\n* `Gmail` - Gmail\n* `GNews` - GNews\n* `GoogleCalendar` - GoogleCalendar\n* `GoogleClassroom` - GoogleClassroom\n* `GoogleDirectory` - GoogleDirectory\n* `GoogleForms` - GoogleForms\n* `GooglePageSpeedInsights` - GooglePageSpeedInsights\n* `GoogleTasks` - GoogleTasks\n* `GoogleWebfonts` - GoogleWebfonts\n* `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports\n* `HuggingFace` - HuggingFace\n* `IlluminaBasespace` - IlluminaBasespace\n* `Imagga` - Imagga\n* `Interzoid` - Interzoid\n* `IP2Whois` - IP2Whois\n* `KYVE` - KYVE\n* `Marketstack` - Marketstack\n* `Mendeley` - Mendeley\n* `Nasa` - Nasa\n* `NewYorkTimes` - NewYorkTimes\n* `NewsApi` - NewsApi\n* `NewsData` - NewsData\n* `OpenDataDc` - OpenDataDc\n* `OpenExchangeRates` - OpenExchangeRates\n* `OpenAQ` - OpenAQ\n* `OpenFDA` - OpenFDA\n* `OpenWeather` - OpenWeather\n* `Outlook` - Outlook\n* `Perigon` - Perigon\n* `Pexels` - Pexels\n* `Pocket` - Pocket\n* `Polygon` - Polygon\n* `PyPI` - PyPI\n* `Recreation` - Recreation\n* `RKICovid` - RKICovid\n* `Rss` - Rss\n* `SimFin` - SimFin\n* `StockData` - StockData\n* `Guardian` - Guardian\n* `TMDb` - TMDb\n* `TVMaze` - TVMaze\n* `TwelveData` - TwelveData\n* `Ubidots` - Ubidots\n* `USCensus` - USCensus\n* `Watchmode` - Watchmode\n* `WikipediaPageviews` - WikipediaPageviews\n* `YahooFinance` - YahooFinance\n* `Clarifai` - Clarifai\n* `Adapty` - Adapty\n* `Braintrust` - Braintrust\n* `StreamElements` - StreamElements\n* `Streamlabs` - Streamlabs\n* `Datorama` - Datorama\n* `Ahrefs` - Ahrefs\n* `Lightfield` - Lightfield\n* `Appstack` - Appstack\n* `Razorpay` - Razorpay\n* `Neon` - Neon\n* `NewRelic` - NewRelic\n* `Custom` - Custom\n* `Tile38` - Tile38\n* `Chatwoot` - Chatwoot\n* `Sanity` - Sanity\n* `Metronome` - Metronome\n* `Jobber` - Jobber\n* `Knock` - Knock\n* `Leexi` - Leexi\n* `RB2B` - RB2B\n* `Superwall` - Superwall\n* `Liana` - Liana\n* `TawkTo` - TawkTo\n* `Hightouch` - Hightouch\n* `LemonSqueezy` - LemonSqueezy\n* `Ikas` - Ikas\n* `Talkwalker` - Talkwalker\n* `NextdoorAds` - NextdoorAds\n* `AppLovin` - AppLovin\n* `Baserow` - Baserow\n* `Plunk` - Plunk\n* `Dub` - Dub\n* `AirOps` - AirOps\n* `Podium` - Podium\n* `Loops` - Loops\n* `Redis` - Redis\n* `Mercury` - Mercury\n* `Gojiberry` - Gojiberry\n* `Teachable` - Teachable"
        ),
    payload: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Connection details as flat keys for the source_type (discover required fields with the wizard tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection details the user stored via the connect-link page (discover ids with the stored_credentials endpoint) — they are merged in server-side and deleted once consumed. An already-connected OAuth integration can be passed via its id key instead (e.g. {'hubspot_integration_id': 123}). For source_type 'Custom' (a user-defined REST API) the keys are 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the auth type the manifest declares — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic); keep secrets in these auth_* keys, never inline in the manifest. A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible sync defaults."
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
    direct_query_enabled: zod
        .boolean()
        .default(externalDataSourcesSetupCreateBodyDirectQueryEnabledDefault)
        .describe(
            'Whether a synced source should also be live-queryable via direct connection. Defaults to true; ignored for pure direct-query sources.'
        ),
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

export const ExternalDataSourcesWizardRetrieveQueryParams = /* @__PURE__ */ zod.object({
    source_type: zod
        .string()
        .optional()
        .describe(
            "Comma-separated source type(s) to return config for, e.g. 'Postgres' or 'Postgres,Stripe'. Strongly recommended: the unfiltered response describes every supported source and is very large. Omit only to enumerate the available types."
        ),
})
