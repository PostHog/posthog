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

export const externalDataSchemasUpdateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasUpdateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const externalDataSchemasUpdateBodyApiVersionMax = 128

export const ExternalDataSchemasUpdateBody = /* @__PURE__ */ zod.object({
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

export const externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasPartialUpdateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const externalDataSchemasPartialUpdateBodyApiVersionMax = 128

export const ExternalDataSchemasPartialUpdateBody = /* @__PURE__ */ zod.object({
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

export const externalDataSchemasIncrementalFieldsCreateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasIncrementalFieldsCreateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const externalDataSchemasIncrementalFieldsCreateBodyApiVersionMax = 128

export const ExternalDataSchemasIncrementalFieldsCreateBody = /* @__PURE__ */ zod.object({
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
        .min(externalDataSchemasIncrementalFieldsCreateBodyIncrementalFieldLookbackSecondsMin)
        .max(externalDataSchemasIncrementalFieldsCreateBodyIncrementalFieldLookbackSecondsMax)
        .nullish()
        .describe(
            'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp\/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
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
        .max(externalDataSchemasIncrementalFieldsCreateBodyApiVersionMax)
        .nullish()
        .describe(
            "Vendor API version override for this schema. `null` (default) syncs on the source's pinned version. Must be one of the source type's supported versions. User-managed: version-migration tooling never changes it. Not available for webhook-sync schemas."
        ),
})

export const externalDataSchemasReloadCreateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasReloadCreateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const externalDataSchemasReloadCreateBodyApiVersionMax = 128

export const ExternalDataSchemasReloadCreateBody = /* @__PURE__ */ zod.object({
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
        .min(externalDataSchemasReloadCreateBodyIncrementalFieldLookbackSecondsMin)
        .max(externalDataSchemasReloadCreateBodyIncrementalFieldLookbackSecondsMax)
        .nullish()
        .describe(
            'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp\/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
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
        .max(externalDataSchemasReloadCreateBodyApiVersionMax)
        .nullish()
        .describe(
            "Vendor API version override for this schema. `null` (default) syncs on the source's pinned version. Must be one of the source type's supported versions. User-managed: version-migration tooling never changes it. Not available for webhook-sync schemas."
        ),
})

export const externalDataSchemasResyncCreateBodyIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemasResyncCreateBodyIncrementalFieldLookbackSecondsMax = 5184000

export const externalDataSchemasResyncCreateBodyApiVersionMax = 128

export const ExternalDataSchemasResyncCreateBody = /* @__PURE__ */ zod.object({
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
        .min(externalDataSchemasResyncCreateBodyIncrementalFieldLookbackSecondsMin)
        .max(externalDataSchemasResyncCreateBodyIncrementalFieldLookbackSecondsMax)
        .nullish()
        .describe(
            'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp\/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
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
        .max(externalDataSchemasResyncCreateBodyApiVersionMax)
        .nullish()
        .describe(
            "Vendor API version override for this schema. `null` (default) syncs on the source's pinned version. Must be one of the source type's supported versions. User-managed: version-migration tooling never changes it. Not available for webhook-sync schemas."
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

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
export const ExternalDataSourcesCheckCdcPrerequisitesForSourceCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesCreateWebhookCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDeleteWebhookCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

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
export const ExternalDataSourcesDisableCdcCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

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
export const ExternalDataSourcesEnableCdcCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync).
 */
export const ExternalDataSourcesRefreshSchemasCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesReloadCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export const ExternalDataSourcesRevenueAnalyticsConfigPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Update CDC tuning fields without enabling/disabling.
 *
 * Lets users edit ``cdc_auto_drop_slot``, ``cdc_lag_warning_threshold_mb``, and
 * ``cdc_lag_critical_threshold_mb`` independently. These fields are universal
 * across engines. Engine-specific identifiers (slot name, management mode, …)
 * are immutable post-enable — switching them requires disable + enable.
 */
export const ExternalDataSourcesUpdateCdcSettingsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesUpdateWebhookInputsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDatabaseSchemaCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

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

export const ExternalDataSourcesDraftCustomManifestCreateBody = /* @__PURE__ */ zod.object({
    source_name: zod
        .string()
        .default(externalDataSourcesDraftCustomManifestCreateBodySourceNameDefault)
        .describe("Optional human name of the API being connected (e.g. 'Acme CRM'). Used only to orient the model."),
    docs_url: zod
        .url()
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
export const ExternalDataSourcesPreviewResourceCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

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
export const ExternalDataSourcesSetupCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesSourcePrefixCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Validate and store credentials for a data warehouse source without creating the source.
 *
 * Backs the source connect page: the user enters credentials directly in PostHog, they are
 * checked against a live connection, then stashed encrypted in a temporary store. The returned
 * credential id can be passed to `setup` as {'credential_id': <id>} to create the source — so
 * secrets never travel through an agent conversation. The stash is single-use: it is deleted
 * as soon as `setup` consumes it, and expires after 24 hours if never consumed.
 */
export const ExternalDataSourcesStoreCredentialsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
