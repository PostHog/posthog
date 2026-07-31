/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const SyncTypeEnumApi = zod
    .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc', 'xmin'])
    .describe(
        '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc\n\* `xmin` - xmin'
    )

export type SyncTypeEnumApi = zod.input<typeof SyncTypeEnumApi>
export type SyncTypeEnumApiOutput = zod.output<typeof SyncTypeEnumApi>

export const IncrementalFieldTypeEnumApi = zod
    .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid', 'xid'])
    .describe(
        '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid\n\* `xid` - xid'
    )

export type IncrementalFieldTypeEnumApi = zod.input<typeof IncrementalFieldTypeEnumApi>
export type IncrementalFieldTypeEnumApiOutput = zod.output<typeof IncrementalFieldTypeEnumApi>

export const ExternalDataSchemaSyncFrequencyEnumApi = zod
    .enum(['never', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day'])
    .describe(
        '\* `never` - never\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
    )

export type ExternalDataSchemaSyncFrequencyEnumApi = zod.input<typeof ExternalDataSchemaSyncFrequencyEnumApi>
export type ExternalDataSchemaSyncFrequencyEnumApiOutput = zod.output<typeof ExternalDataSchemaSyncFrequencyEnumApi>

export const CdcTableModeEnumApi = zod
    .enum(['consolidated', 'cdc_only', 'both'])
    .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both')

export type CdcTableModeEnumApi = zod.input<typeof CdcTableModeEnumApi>
export type CdcTableModeEnumApiOutput = zod.output<typeof CdcTableModeEnumApi>

export const ExternalDataSourceApiVersionDeprecationApi = zod.object({
    version: zod.string().describe('The deprecated vendor API version this source is pinned to.'),
    sunset_at: zod.iso.date().nullable().describe('Date the vendor stops serving this version; null if not announced.'),
    default_version: zod.string().describe("The source's current default vendor API version — the migration target."),
})

export type ExternalDataSourceApiVersionDeprecationApi = zod.input<typeof ExternalDataSourceApiVersionDeprecationApi>
export type ExternalDataSourceApiVersionDeprecationApiOutput = zod.output<
    typeof ExternalDataSourceApiVersionDeprecationApi
>

export const externalDataSchemaApiIncrementalFieldLookbackSecondsMin = 0
export const externalDataSchemaApiIncrementalFieldLookbackSecondsMax = 5184000

export const externalDataSchemaApiApiVersionMax = 128

export const ExternalDataSchemaApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string(),
        label: zod.string().nullable(),
        table: zod.record(zod.string(), zod.unknown()).nullable(),
        should_sync: zod.boolean().optional(),
        last_synced_at: zod.iso.datetime({ offset: true }).nullable(),
        latest_error: zod.string().nullable().describe('The latest error that occurred when syncing this schema.'),
        incremental: zod.boolean(),
        status: zod.string().nullable(),
        sync_type: zod
            .union([SyncTypeEnumApi, zod.null()])
            .optional()
            .describe(
                'Sync strategy: incremental, full_refresh, append, cdc, or xmin.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc\n\* `xmin` - xmin'
            ),
        incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
        incremental_field_type: zod
            .union([IncrementalFieldTypeEnumApi, zod.null()])
            .optional()
            .describe(
                'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid\n\* `xid` - xid'
            ),
        incremental_field_lookback_seconds: zod
            .number()
            .min(externalDataSchemaApiIncrementalFieldLookbackSecondsMin)
            .max(externalDataSchemaApiIncrementalFieldLookbackSecondsMax)
            .nullish()
            .describe(
                'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp\/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
            ),
        sync_frequency: zod
            .union([ExternalDataSchemaSyncFrequencyEnumApi, zod.null()])
            .optional()
            .describe(
                'How often to sync. The fastest sync frequency is 5 minutes.\n\n\* `never` - never\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
            ),
        sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
        description: zod.string().nullable(),
        primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
        cdc_table_mode: zod
            .union([CdcTableModeEnumApi, zod.null()])
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
        available_columns: zod
            .array(
                zod.object({
                    name: zod.string(),
                    data_type: zod.string().optional(),
                    is_nullable: zod.boolean().optional(),
                })
            )
            .describe(
                "Column metadata (name, data type, nullable) for this schema. For SQL sources this is the source-side schema discovered via `refresh_schemas`; for other sources (and once synced) it falls back to the synced table's columns. Empty only before the first successful sync\/refresh."
            ),
        source: zod
            .object({
                id: zod.string().optional(),
                source_type: zod.string().optional(),
                access_method: zod.string().optional(),
                supports_column_selection: zod.boolean().optional(),
                supports_row_filters: zod.boolean().optional(),
                user_access_level: zod.string().nullish(),
                api_version: zod.string().nullish(),
                supported_api_versions: zod.array(zod.string()).optional(),
            })
            .nullable()
            .describe(
                "Lightweight parent-source summary (id, source_type, access_method, column-selection support, the requesting user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so read-only views can render without fetching the full source and all its schemas."
            ),
        api_version: zod
            .string()
            .max(externalDataSchemaApiApiVersionMax)
            .nullish()
            .describe(
                "Vendor API version override for this schema. `null` (default) syncs on the source's pinned version. Must be one of the source type's supported versions. User-managed: version-migration tooling never changes it. Not available for webhook-sync schemas."
            ),
        api_version_deprecation: zod
            .union([ExternalDataSourceApiVersionDeprecationApi, zod.null()])
            .describe(
                "Set when this schema's version override is deprecated by the vendor; null when there is no override or it is not deprecated. The source-level field covers the source pin."
            ),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('A schema of an external data source: its sync configuration and the warehouse table it syncs into.')

export type ExternalDataSchemaApi = zod.input<typeof ExternalDataSchemaApi>
export type ExternalDataSchemaApiOutput = zod.output<typeof ExternalDataSchemaApi>

export const PaginatedExternalDataSchemaListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ExternalDataSchemaApi),
})

export type PaginatedExternalDataSchemaListApi = zod.input<typeof PaginatedExternalDataSchemaListApi>
export type PaginatedExternalDataSchemaListApiOutput = zod.output<typeof PaginatedExternalDataSchemaListApi>

export const patchedExternalDataSchemaApiIncrementalFieldLookbackSecondsMin = 0
export const patchedExternalDataSchemaApiIncrementalFieldLookbackSecondsMax = 5184000

export const patchedExternalDataSchemaApiApiVersionMax = 128

export const PatchedExternalDataSchemaApi = zod
    .object({
        id: zod.uuid().optional(),
        name: zod.string().optional(),
        label: zod.string().nullish(),
        table: zod.record(zod.string(), zod.unknown()).nullish(),
        should_sync: zod.boolean().optional(),
        last_synced_at: zod.iso.datetime({ offset: true }).nullish(),
        latest_error: zod.string().nullish().describe('The latest error that occurred when syncing this schema.'),
        incremental: zod.boolean().optional(),
        status: zod.string().nullish(),
        sync_type: zod
            .union([SyncTypeEnumApi, zod.null()])
            .optional()
            .describe(
                'Sync strategy: incremental, full_refresh, append, cdc, or xmin.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc\n\* `xmin` - xmin'
            ),
        incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
        incremental_field_type: zod
            .union([IncrementalFieldTypeEnumApi, zod.null()])
            .optional()
            .describe(
                'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid\n\* `xid` - xid'
            ),
        incremental_field_lookback_seconds: zod
            .number()
            .min(patchedExternalDataSchemaApiIncrementalFieldLookbackSecondsMin)
            .max(patchedExternalDataSchemaApiIncrementalFieldLookbackSecondsMax)
            .nullish()
            .describe(
                'Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp\/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).'
            ),
        sync_frequency: zod
            .union([ExternalDataSchemaSyncFrequencyEnumApi, zod.null()])
            .optional()
            .describe(
                'How often to sync. The fastest sync frequency is 5 minutes.\n\n\* `never` - never\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
            ),
        sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
        description: zod.string().nullish(),
        primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
        cdc_table_mode: zod
            .union([CdcTableModeEnumApi, zod.null()])
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
        available_columns: zod
            .array(
                zod.object({
                    name: zod.string(),
                    data_type: zod.string().optional(),
                    is_nullable: zod.boolean().optional(),
                })
            )
            .optional()
            .describe(
                "Column metadata (name, data type, nullable) for this schema. For SQL sources this is the source-side schema discovered via `refresh_schemas`; for other sources (and once synced) it falls back to the synced table's columns. Empty only before the first successful sync\/refresh."
            ),
        source: zod
            .object({
                id: zod.string().optional(),
                source_type: zod.string().optional(),
                access_method: zod.string().optional(),
                supports_column_selection: zod.boolean().optional(),
                supports_row_filters: zod.boolean().optional(),
                user_access_level: zod.string().nullish(),
                api_version: zod.string().nullish(),
                supported_api_versions: zod.array(zod.string()).optional(),
            })
            .nullish()
            .describe(
                "Lightweight parent-source summary (id, source_type, access_method, column-selection support, the requesting user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so read-only views can render without fetching the full source and all its schemas."
            ),
        api_version: zod
            .string()
            .max(patchedExternalDataSchemaApiApiVersionMax)
            .nullish()
            .describe(
                "Vendor API version override for this schema. `null` (default) syncs on the source's pinned version. Must be one of the source type's supported versions. User-managed: version-migration tooling never changes it. Not available for webhook-sync schemas."
            ),
        api_version_deprecation: zod
            .union([ExternalDataSourceApiVersionDeprecationApi, zod.null()])
            .optional()
            .describe(
                "Set when this schema's version override is deprecated by the vendor; null when there is no override or it is not deprecated. The source-level field covers the source pin."
            ),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
    })
    .describe('A schema of an external data source: its sync configuration and the warehouse table it syncs into.')

export type PatchedExternalDataSchemaApi = zod.input<typeof PatchedExternalDataSchemaApi>
export type PatchedExternalDataSchemaApiOutput = zod.output<typeof PatchedExternalDataSchemaApi>

export const PaginatedExternalDataSourceSerializersListApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type PaginatedExternalDataSourceSerializersListApi = zod.input<
    typeof PaginatedExternalDataSourceSerializersListApi
>
export type PaginatedExternalDataSourceSerializersListApiOutput = zod.output<
    typeof PaginatedExternalDataSourceSerializersListApi
>

export const ExternalDataSourceCreateApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExternalDataSourceCreateApi = zod.input<typeof ExternalDataSourceCreateApi>
export type ExternalDataSourceCreateApiOutput = zod.output<typeof ExternalDataSourceCreateApi>

export const ExternalDataSourceCreateResponseApi = zod.object({
    id: zod.uuid().describe('ID of the created external data source.'),
})

export type ExternalDataSourceCreateResponseApi = zod.input<typeof ExternalDataSourceCreateResponseApi>
export type ExternalDataSourceCreateResponseApiOutput = zod.output<typeof ExternalDataSourceCreateResponseApi>

export const ExternalDataSourceSerializersApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExternalDataSourceSerializersApi = zod.input<typeof ExternalDataSourceSerializersApi>
export type ExternalDataSourceSerializersApiOutput = zod.output<typeof ExternalDataSourceSerializersApi>

export const PatchedExternalDataSourceSerializersApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type PatchedExternalDataSourceSerializersApi = zod.input<typeof PatchedExternalDataSourceSerializersApi>
export type PatchedExternalDataSourceSerializersApiOutput = zod.output<typeof PatchedExternalDataSourceSerializersApi>

export const ExternalDataSourceBulkUpdateSchemaApi = zod.object({
    id: zod.uuid().describe('Schema identifier to update.'),
    should_sync: zod.boolean().optional().describe('Whether the schema should be queryable\/synced.'),
    sync_type: zod
        .union([SyncTypeEnumApi, zod.null()])
        .optional()
        .describe(
            'Requested sync mode for the schema (incremental, full_refresh, append, cdc, or xmin).\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc\n\* `xmin` - xmin'
        ),
    incremental_field: zod.string().nullish().describe('Incremental cursor field for incremental or append syncs.'),
    incremental_field_type: zod.string().nullish().describe('Type of the incremental cursor field.'),
    sync_frequency: zod.string().nullish().describe('Human-readable sync frequency value.'),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC anchor time for scheduled syncs.'),
    cdc_table_mode: zod
        .union([CdcTableModeEnumApi, zod.null()])
        .optional()
        .describe(
            'How CDC-backed tables should be exposed.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
        ),
    enabled_columns: zod.array(zod.string()).nullish().describe('Columns to sync. Null means sync all columns.'),
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

export type ExternalDataSourceBulkUpdateSchemaApi = zod.input<typeof ExternalDataSourceBulkUpdateSchemaApi>
export type ExternalDataSourceBulkUpdateSchemaApiOutput = zod.output<typeof ExternalDataSourceBulkUpdateSchemaApi>

export const PatchedExternalDataSourceBulkUpdateSchemasApi = zod.object({
    schemas: zod
        .array(ExternalDataSourceBulkUpdateSchemaApi)
        .optional()
        .describe('Schema updates to apply in a single batch.'),
})

export type PatchedExternalDataSourceBulkUpdateSchemasApi = zod.input<
    typeof PatchedExternalDataSourceBulkUpdateSchemasApi
>
export type PatchedExternalDataSourceBulkUpdateSchemasApiOutput = zod.output<
    typeof PatchedExternalDataSourceBulkUpdateSchemasApi
>

export const AuthMethodEnumApi = zod
    .enum(['oauth', 'credentials'])
    .describe('\* `oauth` - oauth\n\* `credentials` - credentials')

export type AuthMethodEnumApi = zod.input<typeof AuthMethodEnumApi>
export type AuthMethodEnumApiOutput = zod.output<typeof AuthMethodEnumApi>

export const SourceConnectLinkApi = zod.object({
    source_type: zod.string().describe('The source type the link is for.'),
    auth_method: AuthMethodEnumApi.describe(
        "What the user will do on the connect page: 'oauth' = authorize an account in their browser; 'credentials' = enter connection details (or pick OAuth where the source offers both). Either way secrets never pass through the agent, and the result is always a stored credential id.\n\n\* `oauth` - oauth\n\* `credentials` - credentials"
    ),
    connect_url: zod
        .string()
        .describe(
            "Full URL to share with the user. It opens the source's connection form in PostHog — credentials never pass through the agent or the chat."
        ),
    instructions: zod.string().describe('Next steps for the agent to relay to the user.'),
})

export type SourceConnectLinkApi = zod.input<typeof SourceConnectLinkApi>
export type SourceConnectLinkApiOutput = zod.output<typeof SourceConnectLinkApi>

export const ExternalDataSourceConnectionOptionApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExternalDataSourceConnectionOptionApi = zod.input<typeof ExternalDataSourceConnectionOptionApi>
export type ExternalDataSourceConnectionOptionApiOutput = zod.output<typeof ExternalDataSourceConnectionOptionApi>

export const DatabaseSchemaRequestApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type DatabaseSchemaRequestApi = zod.input<typeof DatabaseSchemaRequestApi>
export type DatabaseSchemaRequestApiOutput = zod.output<typeof DatabaseSchemaRequestApi>

export const DirectConnectionSourceOptionApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type DirectConnectionSourceOptionApi = zod.input<typeof DirectConnectionSourceOptionApi>
export type DirectConnectionSourceOptionApiOutput = zod.output<typeof DirectConnectionSourceOptionApi>

export const draftCustomManifestRequestApiSourceNameDefault = ``

export const DraftCustomManifestRequestApi = zod.object({
    source_name: zod
        .string()
        .default(draftCustomManifestRequestApiSourceNameDefault)
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

export type DraftCustomManifestRequestApi = zod.input<typeof DraftCustomManifestRequestApi>
export type DraftCustomManifestRequestApiOutput = zod.output<typeof DraftCustomManifestRequestApi>

export const DraftStatusEnumApi = zod
    .enum(['ok', 'invalid', 'model_error'])
    .describe('\* `ok` - ok\n\* `invalid` - invalid\n\* `model_error` - model_error')

export type DraftStatusEnumApi = zod.input<typeof DraftStatusEnumApi>
export type DraftStatusEnumApiOutput = zod.output<typeof DraftStatusEnumApi>

export const DraftCustomManifestResponseApi = zod.object({
    draft_status: DraftStatusEnumApi.describe(
        "'ok' = a manifest validated; 'invalid' = a manifest was drafted but never validated within the budget (see error; manifest_json holds the last attempt to fix by hand); 'model_error' = the model returned no usable JSON.\n\n\* `ok` - ok\n\* `invalid` - invalid\n\* `model_error` - model_error"
    ),
    manifest_json: zod
        .string()
        .nullable()
        .describe('The drafted RESTAPIConfig manifest as a JSON string (non-secret), or null if none was produced.'),
    resource_names: zod
        .array(zod.string())
        .describe("Names of the resources (tables) the validated manifest exposes. Empty unless draft_status is 'ok'."),
    attempts: zod.number().describe('How many draft→validate→repair rounds were run.'),
    error: zod
        .string()
        .nullable()
        .describe("The last validation error when draft_status is not 'ok'; null on success."),
})

export type DraftCustomManifestResponseApi = zod.input<typeof DraftCustomManifestResponseApi>
export type DraftCustomManifestResponseApiOutput = zod.output<typeof DraftCustomManifestResponseApi>

export const IntegrationAccountApi = zod
    .object({
        value: zod
            .string()
            .describe(
                'The identifier stored in the source config and used for API calls (numeric account id as a string, a site url, etc.).'
            ),
        display_name: zod.string().describe('Primary human-readable label for the account.'),
        is_primary: zod
            .boolean()
            .describe(
                "True when this account belongs to the connected user's own (primary) account context, rather than one they merely have access to. Sorted\/marked first."
            ),
        badges: zod.array(zod.string()).describe("Short status chips for the account, e.g. ['Active'] or ['Pause']."),
        group: zod
            .string()
            .nullable()
            .describe('Optional grouping label for hierarchical platforms (e.g. the owning customer\/manager name).'),
        secondary_text: zod
            .string()
            .nullable()
            .describe('Extra identifier shown in parentheses and searchable, e.g. the alphanumeric account number.'),
    })
    .describe(
        'A selectable account\/resource exposed by an OAuth integration, in the shared shape every ad\nplatform produces (see ``IntegrationAccount`` in the data-imports common module). One serializer\nand one frontend selector work across all platforms.'
    )

export type IntegrationAccountApi = zod.input<typeof IntegrationAccountApi>
export type IntegrationAccountApiOutput = zod.output<typeof IntegrationAccountApi>

export const IntegrationAccountsResponseApi = zod.object({
    accounts: zod.array(IntegrationAccountApi).describe('All accounts the connected integration can access.'),
})

export type IntegrationAccountsResponseApi = zod.input<typeof IntegrationAccountsResponseApi>
export type IntegrationAccountsResponseApiOutput = zod.output<typeof IntegrationAccountsResponseApi>

export const SourcePreviewRequestApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type SourcePreviewRequestApi = zod.input<typeof SourcePreviewRequestApi>
export type SourcePreviewRequestApiOutput = zod.output<typeof SourcePreviewRequestApi>

export const SourcePreviewColumnApi = zod.object({
    name: zod.string().describe('Column name as it appears in the previewed rows.'),
    type: zod
        .string()
        .describe(
            'JSON type inferred from the first non-null value: string, integer, number, boolean, object, array, or null.'
        ),
})

export type SourcePreviewColumnApi = zod.input<typeof SourcePreviewColumnApi>
export type SourcePreviewColumnApiOutput = zod.output<typeof SourcePreviewColumnApi>

export const SourcePreviewResponseApi = zod.object({
    rows: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe('Up to `limit` sample rows, after data_selector extraction — the raw records the sync would ingest.'),
    row_count: zod.number().describe('Number of sample rows returned (≤ limit).'),
    columns: zod
        .array(SourcePreviewColumnApi)
        .describe('Columns observed across the sample rows, each with an inferred JSON type.'),
    error: zod
        .string()
        .nullable()
        .describe(
            'Set when the live read failed (e.g. the host was unreachable or returned an auth error); rows is then empty. Manifest, validation, and SSRF problems return HTTP 400 instead of populating this field.'
        ),
})

export type SourcePreviewResponseApi = zod.input<typeof SourcePreviewResponseApi>
export type SourcePreviewResponseApiOutput = zod.output<typeof SourcePreviewResponseApi>

export const SourceSetupApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type SourceSetupApi = zod.input<typeof SourceSetupApi>
export type SourceSetupApiOutput = zod.output<typeof SourceSetupApi>

export const SourceSetupWebhookApi = zod.object({
    success: zod
        .boolean()
        .describe(
            'Whether the webhook was registered with the external service. When true, webhook-capable tables (including webhook-only ones) sync via real-time webhooks; when false, tables fall back to the polling sync defaults and webhook-only tables stay disabled.'
        ),
    webhook_url: zod.string().nullable().describe('The PostHog endpoint the external service delivers events to.'),
    error: zod
        .string()
        .nullable()
        .describe('Why webhook registration failed (e.g. the credentials lack webhook permissions).'),
    pending_inputs: zod
        .array(zod.string())
        .describe(
            'Webhook input names the user still needs to provide (e.g. a signing secret the external API did not return on create). Submit them via the update_webhook_inputs endpoint.'
        ),
})

export type SourceSetupWebhookApi = zod.input<typeof SourceSetupWebhookApi>
export type SourceSetupWebhookApiOutput = zod.output<typeof SourceSetupWebhookApi>

export const SourceSetupResponseApi = zod.object({
    id: zod.uuid().describe('ID of the created external data source.'),
    webhook: SourceSetupWebhookApi.optional().describe(
        'Outcome of automatic webhook registration. Only present for sources that support webhooks (e.g. Stripe) and have webhook-capable tables.'
    ),
})

export type SourceSetupResponseApi = zod.input<typeof SourceSetupResponseApi>
export type SourceSetupResponseApiOutput = zod.output<typeof SourceSetupResponseApi>

export const SourceCredentialCreateApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type SourceCredentialCreateApi = zod.input<typeof SourceCredentialCreateApi>
export type SourceCredentialCreateApiOutput = zod.output<typeof SourceCredentialCreateApi>

export const SourceCredentialApi = zod.object({
    credential_id: zod
        .uuid()
        .describe("Stored credential id. Pass to the setup endpoint as {'credential_id': <id>} to create the source."),
    source_type: zod.string().describe('The source type the stored credentials are for.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the credentials were stored.'),
    expires_at: zod.iso
        .datetime({ offset: true })
        .describe('When the stored credentials expire. Unconsumed credentials are unusable past this time.'),
})

export type SourceCredentialApi = zod.input<typeof SourceCredentialApi>
export type SourceCredentialApiOutput = zod.output<typeof SourceCredentialApi>

export const ExternalDataSourceTypeEnumApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExternalDataSourceTypeEnumApi = zod.input<typeof ExternalDataSourceTypeEnumApi>
export type ExternalDataSourceTypeEnumApiOutput = zod.output<typeof ExternalDataSourceTypeEnumApi>

export const AccessMethodEnumApi = zod
    .enum(['warehouse', 'direct'])
    .describe('\* `warehouse` - warehouse\n\* `direct` - direct')

export type AccessMethodEnumApi = zod.input<typeof AccessMethodEnumApi>
export type AccessMethodEnumApiOutput = zod.output<typeof AccessMethodEnumApi>

export const ExternalDataSourceCreateCreatedViaEnumApi = zod
    .enum(['web', 'api', 'mcp'])
    .describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp')

export type ExternalDataSourceCreateCreatedViaEnumApi = zod.input<typeof ExternalDataSourceCreateCreatedViaEnumApi>
export type ExternalDataSourceCreateCreatedViaEnumApiOutput = zod.output<
    typeof ExternalDataSourceCreateCreatedViaEnumApi
>

export const ExternalDataSourceSerializersCreatedViaEnumApi = zod
    .enum(['web', 'api', 'mcp', 'wizard', 'self_driving'])
    .describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp\n\* `wizard` - wizard\n\* `self_driving` - self_driving')

export type ExternalDataSourceSerializersCreatedViaEnumApi = zod.input<
    typeof ExternalDataSourceSerializersCreatedViaEnumApi
>
export type ExternalDataSourceSerializersCreatedViaEnumApiOutput = zod.output<
    typeof ExternalDataSourceSerializersCreatedViaEnumApi
>

export const EngineEnumApi = zod
    .enum(['duckdb', 'postgres', 'mysql', 'snowflake', 'redshift', 'clickhouse'])
    .describe(
        '\* `duckdb` - duckdb\n\* `postgres` - postgres\n\* `mysql` - mysql\n\* `snowflake` - snowflake\n\* `redshift` - redshift\n\* `clickhouse` - clickhouse'
    )

export type EngineEnumApi = zod.input<typeof EngineEnumApi>
export type EngineEnumApiOutput = zod.output<typeof EngineEnumApi>

export const ExternalDataSourceRevenueAnalyticsConfigApi = zod.object({
    enabled: zod.boolean().optional(),
    include_invoiceless_charges: zod.boolean().optional(),
})

export type ExternalDataSourceRevenueAnalyticsConfigApi = zod.input<typeof ExternalDataSourceRevenueAnalyticsConfigApi>
export type ExternalDataSourceRevenueAnalyticsConfigApiOutput = zod.output<
    typeof ExternalDataSourceRevenueAnalyticsConfigApi
>
