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

export const ExternalDataSchemasCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
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
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
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
})

export const ExternalDataSchemasUpdateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
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
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
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
})

export const ExternalDataSchemasPartialUpdateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
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
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
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
})

export const ExternalDataSchemasCancelCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
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
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
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
})

export const ExternalDataSchemasIncrementalFieldsCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
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
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
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
})

export const ExternalDataSchemasReloadCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
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
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
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
})

export const ExternalDataSchemasResyncCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
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
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
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
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesCreateBodyPrefixMax = 100

export const externalDataSourcesCreateBodyDescriptionMax = 400

export const externalDataSourcesCreateBodyAccessMethodDefault = `warehouse`
export const externalDataSourcesCreateBodyCreatedViaDefault = `api`

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
            '\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom'
        )
        .describe(
            "The source type (e.g. 'Postgres', 'Stripe').\n\n\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom"
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
        .describe('\* `warehouse` - warehouse\n\* `direct` - direct')
        .default(externalDataSourcesCreateBodyAccessMethodDefault)
        .describe(
            "Connection mode: 'warehouse' (import) or 'direct' (live query).\n\n\* `warehouse` - warehouse\n\* `direct` - direct"
        ),
    created_via: zod
        .enum(['web', 'api', 'mcp'])
        .describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp')
        .default(externalDataSourcesCreateBodyCreatedViaDefault)
        .describe('Where the request came from\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesUpdateBodyPrefixMax = 100

export const externalDataSourcesUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesUpdateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesPartialUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
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
export const ExternalDataSourcesBulkUpdateSchemasPartialUpdateBody = /* @__PURE__ */ zod.object({
    schemas: zod
        .array(
            zod.object({
                id: zod.uuid().describe('Schema identifier to update.'),
                should_sync: zod.boolean().optional().describe('Whether the schema should be queryable\/synced.'),
                sync_type: zod
                    .union([
                        zod
                            .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                            .describe(
                                '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                            ),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'Requested sync mode for the schema.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                    ),
                incremental_field: zod
                    .string()
                    .nullish()
                    .describe('Incremental cursor field for incremental or append syncs.'),
                incremental_field_type: zod.string().nullish().describe('Type of the incremental cursor field.'),
                sync_frequency: zod.string().nullish().describe('Human-readable sync frequency value.'),
                sync_time_of_day: zod.iso.time({}).nullish().describe('UTC anchor time for scheduled syncs.'),
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
            })
        )
        .optional()
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

export const ExternalDataSourcesCheckCdcPrerequisitesForSourceCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyPrefixMax).nullish(),
        description: zod
            .string()
            .max(externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyDescriptionMax)
            .nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesCreateWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesCreateWebhookCreateBodyDescriptionMax = 400

export const ExternalDataSourcesCreateWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
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
export const externalDataSourcesDeleteWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesDeleteWebhookCreateBodyDescriptionMax = 400

export const ExternalDataSourcesDeleteWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

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

export const ExternalDataSourcesDisableCdcCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesDisableCdcCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesDisableCdcCreateBodyDescriptionMax).nullish(),
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

export const ExternalDataSourcesEnableCdcCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesEnableCdcCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesEnableCdcCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync).
 */
export const externalDataSourcesRefreshSchemasCreateBodyPrefixMax = 100

export const externalDataSourcesRefreshSchemasCreateBodyDescriptionMax = 400

export const ExternalDataSourcesRefreshSchemasCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesRefreshSchemasCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesRefreshSchemasCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesReloadCreateBodyPrefixMax = 100

export const externalDataSourcesReloadCreateBodyDescriptionMax = 400

export const ExternalDataSourcesReloadCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesReloadCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesReloadCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesRevenueAnalyticsConfigPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string().optional(),
        account_id: zod.string().optional(),
        prefix: zod.string().max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyPrefixMax).nullish(),
        description: zod
            .string()
            .max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyDescriptionMax)
            .nullish(),
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

export const ExternalDataSourcesUpdateCdcSettingsCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateCdcSettingsCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateCdcSettingsCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax = 100

export const externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax = 400

export const ExternalDataSourcesUpdateWebhookInputsCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
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
export const ExternalDataSourcesDatabaseSchemaCreateBody = /* @__PURE__ */ zod
    .object({
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
                '\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom'
            )
            .describe(
                'The source type to validate against.\n\n\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom'
            ),
    })
    .describe(
        'Validate credentials and preview available tables from a remote database.\n\nThe request body contains source_type plus flat source-specific credential fields\n(e.g. host, port, database, user, password, schema for Postgres). The credential\nfields vary per source_type and are validated dynamically by the source registry.'
    )

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
            '\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom'
        )
        .describe(
            "The source type to set up (e.g. 'Stripe', 'Postgres', 'Hubspot').\n\n\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom"
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
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesSourcePrefixCreateBodyPrefixMax = 100

export const externalDataSourcesSourcePrefixCreateBodyDescriptionMax = 400

export const ExternalDataSourcesSourcePrefixCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesSourcePrefixCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesSourcePrefixCreateBodyDescriptionMax).nullish(),
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
            '\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom'
        )
        .describe(
            "The source type these credentials are for (e.g. 'Stripe', 'Postgres').\n\n\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom"
        ),
    payload: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'Connection details as flat keys for the source_type — the same fields the create flow accepts (host, port, password, API key, …). Checked against a live connection before being stored.'
        ),
})
