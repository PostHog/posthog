/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `PostHogWarehouse` - PostHog warehouse
 * * `Redshift` - Redshift
 * * `Snowflake` - Snowflake
 * * `BigQuery` - BigQuery
 * * `Postgres` - Postgres
 * * `Databricks` - Databricks
 * * `AzureBlob` - Azure Blob
 * * `S3` - S3
 */
export type ExternalDataDestinationTypeEnumApi =
    (typeof ExternalDataDestinationTypeEnumApi)[keyof typeof ExternalDataDestinationTypeEnumApi]

export const ExternalDataDestinationTypeEnumApi = {
    PostHogWarehouse: 'PostHogWarehouse',
    Redshift: 'Redshift',
    Snowflake: 'Snowflake',
    BigQuery: 'BigQuery',
    Postgres: 'Postgres',
    Databricks: 'Databricks',
    AzureBlob: 'AzureBlob',
    S3: 'S3',
} as const

/**
 * One source that writes to a destination. Shape only — never used to deserialize.
 */
export interface SyncedSourceApi {
    /** The source's id. */
    id: string
    /** How the source is labelled in the UI, prefix included. */
    name: string
    /** Which connector this is, e.g. Stripe or Postgres. */
    source_type: string
    /** True when only some of the source's tables reach this destination, through their own override. */
    via_table_override: boolean
}

/**
 * * `healthy` - Healthy
 * * `failing` - Failing
 * * `paused` - Paused
 */
export type ExternalDataDestinationStatusEnumApi =
    (typeof ExternalDataDestinationStatusEnumApi)[keyof typeof ExternalDataDestinationStatusEnumApi]

export const ExternalDataDestinationStatusEnumApi = {
    Healthy: 'healthy',
    Failing: 'failing',
    Paused: 'paused',
} as const

export interface ExternalDataDestinationApi {
    readonly id: string
    /** Where synced rows are written. The PostHog warehouse is managed for you, so you cannot create one here.
     *
     * * `PostHogWarehouse` - PostHog warehouse
     * * `Redshift` - Redshift
     * * `Snowflake` - Snowflake
     * * `BigQuery` - BigQuery
     * * `Postgres` - Postgres
     * * `Databricks` - Databricks
     * * `AzureBlob` - Azure Blob
     * * `S3` - S3 */
    type: ExternalDataDestinationTypeEnumApi
    /**
     * Human-readable name shown when picking destinations for a source or table.
     * @maxLength 400
     */
    name: string
    /** Settings for this destination: target database, schema or dataset, bucket and prefix, file format. Credentials are not stored here. They live on the linked integration. */
    config?: unknown
    /**
     * Integration holding this destination's credentials. Required for every type except the PostHog warehouse.
     * @nullable
     */
    integration?: number | null
    /** Whether this is the managed PostHog warehouse destination. */
    readonly is_posthog_warehouse: boolean
    readonly created_at: string
    /** @nullable */
    readonly created_by: number | null
    /** @nullable */
    readonly updated_at: string | null
    /** Sources whose tables sync to this destination, so you can see what a change or a deletion would affect. Includes sources that reach it through a single table's override, and — for the PostHog warehouse — sources that write there by default because nothing else was configured. */
    readonly synced_sources: readonly SyncedSourceApi[]
    /** Whether delivery to this destination works. `healthy`: the last delivery worked. `failing`: the last delivery failed. `paused`: PostHog stopped syncing to it after repeated configuration errors. Edit the destination to turn it back on.
     *
     * * `healthy` - Healthy
     * * `failing` - Failing
     * * `paused` - Paused */
    readonly status: ExternalDataDestinationStatusEnumApi
    /**
     * The last delivery error, safe to show to the user. Null if no delivery has failed.
     * @nullable
     */
    readonly latest_error: string | null
    /**
     * When the last delivery error occurred.
     * @nullable
     */
    readonly latest_error_at: string | null
}

export interface PaginatedExternalDataDestinationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExternalDataDestinationApi[]
}

export interface PatchedExternalDataDestinationApi {
    readonly id?: string
    /** Where synced rows are written. The PostHog warehouse is managed for you, so you cannot create one here.
     *
     * * `PostHogWarehouse` - PostHog warehouse
     * * `Redshift` - Redshift
     * * `Snowflake` - Snowflake
     * * `BigQuery` - BigQuery
     * * `Postgres` - Postgres
     * * `Databricks` - Databricks
     * * `AzureBlob` - Azure Blob
     * * `S3` - S3 */
    type?: ExternalDataDestinationTypeEnumApi
    /**
     * Human-readable name shown when picking destinations for a source or table.
     * @maxLength 400
     */
    name?: string
    /** Settings for this destination: target database, schema or dataset, bucket and prefix, file format. Credentials are not stored here. They live on the linked integration. */
    config?: unknown
    /**
     * Integration holding this destination's credentials. Required for every type except the PostHog warehouse.
     * @nullable
     */
    integration?: number | null
    /** Whether this is the managed PostHog warehouse destination. */
    readonly is_posthog_warehouse?: boolean
    readonly created_at?: string
    /** @nullable */
    readonly created_by?: number | null
    /** @nullable */
    readonly updated_at?: string | null
    /** Sources whose tables sync to this destination, so you can see what a change or a deletion would affect. Includes sources that reach it through a single table's override, and — for the PostHog warehouse — sources that write there by default because nothing else was configured. */
    readonly synced_sources?: readonly SyncedSourceApi[]
    /** Whether delivery to this destination works. `healthy`: the last delivery worked. `failing`: the last delivery failed. `paused`: PostHog stopped syncing to it after repeated configuration errors. Edit the destination to turn it back on.
     *
     * * `healthy` - Healthy
     * * `failing` - Failing
     * * `paused` - Paused */
    readonly status?: ExternalDataDestinationStatusEnumApi
    /**
     * The last delivery error, safe to show to the user. Null if no delivery has failed.
     * @nullable
     */
    readonly latest_error?: string | null
    /**
     * When the last delivery error occurred.
     * @nullable
     */
    readonly latest_error_at?: string | null
}

export interface AddSourcesRequestApi {
    /**
     * IDs of up to 50 existing sources to attach to this destination.
     * @maxItems 50
     */
    source_ids: string[]
    /** Start a full resync for each enabled table newly attached. */
    resync?: boolean
}

export interface SkippedSourceApi {
    /** ID of the source that was not attached. */
    id: string
    /** Name of the source that was not attached. */
    name: string
    /** Why the source was not attached. */
    reason: string
}

export interface ResyncFailureApi {
    /** ID of the table whose resync did not start. */
    schema_id: string
    /** Why the resync did not start. */
    detail: string
}

export interface AddSourcesResponseApi {
    /** Sources newly attached to this destination. */
    attached: SyncedSourceApi[]
    /** Sources that were not attached and their reasons. */
    skipped: SkippedSourceApi[]
    /** Number of tables sent for a full resync. */
    tables_resyncing: number
    /** Tables whose resync did not start. The sources are still attached. */
    resync_failures: ResyncFailureApi[]
}

/**
 * * `full_refresh` - full_refresh
 * * `incremental` - incremental
 * * `append` - append
 * * `webhook` - webhook
 * * `cdc` - cdc
 * * `xmin` - xmin
 */
export type ExternalDataSchemaSyncTypeEnumApi =
    (typeof ExternalDataSchemaSyncTypeEnumApi)[keyof typeof ExternalDataSchemaSyncTypeEnumApi]

export const ExternalDataSchemaSyncTypeEnumApi = {
    FullRefresh: 'full_refresh',
    Incremental: 'incremental',
    Append: 'append',
    Webhook: 'webhook',
    Cdc: 'cdc',
    Xmin: 'xmin',
} as const

/**
 * * `integer` - integer
 * * `numeric` - numeric
 * * `datetime` - datetime
 * * `date` - date
 * * `timestamp` - timestamp
 * * `objectid` - objectid
 * * `xid` - xid
 */
export type IncrementalFieldTypeEnumApi = (typeof IncrementalFieldTypeEnumApi)[keyof typeof IncrementalFieldTypeEnumApi]

export const IncrementalFieldTypeEnumApi = {
    Integer: 'integer',
    Numeric: 'numeric',
    Datetime: 'datetime',
    Date: 'date',
    Timestamp: 'timestamp',
    Objectid: 'objectid',
    Xid: 'xid',
} as const

/**
 * * `never` - never
 * * `5min` - 5min
 * * `15min` - 15min
 * * `30min` - 30min
 * * `1hour` - 1hour
 * * `6hour` - 6hour
 * * `12hour` - 12hour
 * * `24hour` - 24hour
 * * `7day` - 7day
 * * `30day` - 30day
 */
export type ExternalDataSchemaSyncFrequencyEnumApi =
    (typeof ExternalDataSchemaSyncFrequencyEnumApi)[keyof typeof ExternalDataSchemaSyncFrequencyEnumApi]

export const ExternalDataSchemaSyncFrequencyEnumApi = {
    Never: 'never',
    '5min': '5min',
    '15min': '15min',
    '30min': '30min',
    '1hour': '1hour',
    '6hour': '6hour',
    '12hour': '12hour',
    '24hour': '24hour',
    '7day': '7day',
    '30day': '30day',
} as const

/**
 * * `consolidated` - consolidated
 * * `cdc_only` - cdc_only
 * * `both` - both
 */
export type CdcTableModeEnumApi = (typeof CdcTableModeEnumApi)[keyof typeof CdcTableModeEnumApi]

export const CdcTableModeEnumApi = {
    Consolidated: 'consolidated',
    CdcOnly: 'cdc_only',
    Both: 'both',
} as const

/**
 * * `missing_primary_key` - Missing primary key
 * * `duplicate_primary_key` - Duplicate primary key
 */
export type IncrementalSyncBlockedReasonEnumApi =
    (typeof IncrementalSyncBlockedReasonEnumApi)[keyof typeof IncrementalSyncBlockedReasonEnumApi]

export const IncrementalSyncBlockedReasonEnumApi = {
    MissingPrimaryKey: 'missing_primary_key',
    DuplicatePrimaryKey: 'duplicate_primary_key',
} as const

export interface RowFilterColumnApi {
    /** Column name to use as `column` in a row filter. */
    name: string
    /** Column type, which decides the format of the filter value. */
    data_type: string
    /** Operators a row filter on this column may use. */
    operators: string[]
}

export interface ExternalDataSourceApiVersionDeprecationApi {
    /** The deprecated vendor API version this source is pinned to. */
    version: string
    /**
     * Date the vendor stops serving this version; null if not announced.
     * @nullable
     */
    sunset_at: string | null
    /** The source's current default vendor API version — the migration target. */
    default_version: string
}

/**
 * @nullable
 */
export type ExternalDataSchemaApiTable = { [key: string]: unknown } | null

export type ExternalDataSchemaApiRowFiltersItem = {
    column: string
    /** One of: > >= < <= = != IN "NOT IN". */
    operator: string
    /** Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`). */
    value: unknown
}

export type ExternalDataSchemaApiAvailableColumnsItem = {
    name: string
    data_type?: string
    is_nullable?: boolean
}

/**
 * Lightweight parent-source summary (id, source_type, access_method, column-selection support, the requesting user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so read-only views can render without fetching the full source and all its schemas.
 * @nullable
 */
export type ExternalDataSchemaApiSource = {
    readonly id?: string
    readonly source_type?: string
    readonly access_method?: string
    readonly supports_column_selection?: boolean
    readonly supports_row_filters?: boolean
    readonly requires_exact_column_metadata?: boolean
    /** @nullable */
    readonly user_access_level?: string | null
    /** @nullable */
    readonly api_version?: string | null
    readonly supported_api_versions?: string[]
} | null

/**
 * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
 */
export interface ExternalDataSchemaApi {
    readonly id: string
    readonly name: string
    /** @nullable */
    readonly label: string | null
    /** @nullable */
    readonly table: ExternalDataSchemaApiTable
    should_sync?: boolean
    /** @nullable */
    readonly last_synced_at: string | null
    /**
     * The latest error that occurred when syncing this schema.
     * @nullable
     */
    readonly latest_error: string | null
    readonly incremental: boolean
    /** @nullable */
    readonly status: string | null
    /** Sync strategy: incremental, full_refresh, append, cdc, or xmin.
     *
     * * `full_refresh` - full_refresh
     * * `incremental` - incremental
     * * `append` - append
     * * `webhook` - webhook
     * * `cdc` - cdc
     * * `xmin` - xmin */
    sync_type?: ExternalDataSchemaSyncTypeEnumApi | null
    /**
     * Column name used to track sync progress.
     * @nullable
     */
    incremental_field?: string | null
    /** Data type of the incremental field.
     *
     * * `integer` - integer
     * * `numeric` - numeric
     * * `datetime` - datetime
     * * `date` - date
     * * `timestamp` - timestamp
     * * `objectid` - objectid
     * * `xid` - xid */
    incremental_field_type?: IncrementalFieldTypeEnumApi | null
    /**
     * Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).
     * @minimum 0
     * @maximum 5184000
     * @nullable
     */
    incremental_field_lookback_seconds?: number | null
    /** How often to sync. The fastest sync frequency is 5 minutes.
     *
     * * `never` - never
     * * `5min` - 5min
     * * `15min` - 15min
     * * `30min` - 30min
     * * `1hour` - 1hour
     * * `6hour` - 6hour
     * * `12hour` - 12hour
     * * `24hour` - 24hour
     * * `7day` - 7day
     * * `30day` - 30day */
    sync_frequency?: ExternalDataSchemaSyncFrequencyEnumApi | null
    /**
     * UTC time of day to run the sync (HH:MM:SS).
     * @nullable
     */
    sync_time_of_day?: string | null
    /**
     * Days between scheduled full refreshes, from 1 to 90, or null for none. A full refresh wipes the table and re-imports every row, so rows deleted at the source are removed. It runs on the first scheduled sync once the interval has passed, counted from when it was saved or from the last full resync (or, when full_refresh_time_of_day is set, from the slot of that time the last refresh served), and can start up to an hour early. Queries keep returning the current rows until a full refresh finishes, and workflows and destinations that run on new rows of the table run again for every row. Available for incremental, append, and xmin syncs only, and never shorter than the sync frequency.
     * @minimum 1
     * @maximum 90
     * @nullable
     */
    full_refresh_interval_days?: number | null
    /**
     * UTC time of day (HH:MM:SS) that scheduled full refreshes are due, for example outside working hours. The refresh runs on the first scheduled sync from up to an hour before this time, so on a table that syncs every few hours it can run hours later. Each interval counts from the slot of this time that the last refresh or save served, where a slot less than an hour away counts as served. Saving a new time restarts the clock, so the first refresh after a save can come up to a day before a full interval has passed. Null counts the interval from when it was saved or from the last full resync. Cleared when full_refresh_interval_days is null.
     * @nullable
     */
    full_refresh_time_of_day?: string | null
    /**
     * When the next scheduled full refresh is due. The first scheduled sync that starts at most an hour before this time re-imports the table. Saving a new interval or time, or any full resync, moves it one interval ahead, onto full_refresh_time_of_day when that is set.
     * @nullable
     */
    readonly next_full_refresh_at: string | null
    /** @nullable */
    readonly description: string | null
    /**
     * Column names for primary key deduplication.
     * @nullable
     */
    primary_key_columns?: string[] | null
    /** For CDC syncs: consolidated, cdc_only, or both.
     *
     * * `consolidated` - consolidated
     * * `cdc_only` - cdc_only
     * * `both` - both */
    cdc_table_mode?: CdcTableModeEnumApi | null
    /** Why the last sync run could not merge rows for this table, or `null` when no such failure is current, which includes a run that failed for another reason. A blocked table is disabled, and the resolution differs by reason. `missing_primary_key`: no key to merge on, so set `primary_key_columns` to a unique key, which is accepted because none was set before. `duplicate_primary_key`: the key in use does not identify one row, and that key cannot be swapped once data has synced, so either remove the duplicates at the source and set `should_sync` to true, or delete the synced data before setting a different key. Either reason also accepts a different `sync_type`: `append` is only safe for insert-only tables, because updated rows arrive again as duplicates, and `full_refresh` re-reads the whole table on every sync and bills every row. This reports the last run's failure, so it clears once a run succeeds or fails for another reason, not when an update lands.
     *
     * * `missing_primary_key` - Missing primary key
     * * `duplicate_primary_key` - Duplicate primary key */
    readonly incremental_sync_blocked: IncrementalSyncBlockedReasonEnumApi | null
    /**
     * Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.
     * @nullable
     */
    enabled_columns?: string[] | null
    /**
     * Predicates ANDed onto the source query so only matching rows sync. Each is `{column, operator, value}`; `null`/empty (default) syncs all rows. The operator must be one of `> >= < <= = != IN "NOT IN"` and the value must match the column's type (for `IN`/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). Applied on the next sync — not retroactive to already-synced rows.
     * @nullable
     */
    row_filters?: ExternalDataSchemaApiRowFiltersItem[] | null
    /**
     * Columns a row filter on this schema may use, with the operators each accepts. `null` means any column in `available_columns` with any operator, which is the case for SQL sources. A list means the source can filter on these columns only; an empty list means this schema accepts no row filter.
     * @nullable
     */
    readonly row_filter_columns: readonly RowFilterColumnApi[] | null
    /** Column metadata (name, data type, nullable) for this schema. For SQL sources this is the source-side schema discovered via `refresh_schemas`; for other sources (and once synced) it falls back to the synced table's columns. Empty only before the first successful sync/refresh. */
    readonly available_columns: readonly ExternalDataSchemaApiAvailableColumnsItem[]
    /** Whether exact source-side column metadata is available for safe source-query projection. */
    readonly source_column_metadata_available: boolean
    /**
     * Lightweight parent-source summary (id, source_type, access_method, column-selection support, the requesting user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so read-only views can render without fetching the full source and all its schemas.
     * @nullable
     */
    readonly source: ExternalDataSchemaApiSource
    /**
     * Vendor API version override for this schema. `null` (default) syncs on the source's pinned version. Must be one of the source type's supported versions. User-managed: version-migration tooling never changes it. Not available for webhook-sync schemas.
     * @maxLength 128
     * @nullable
     */
    api_version?: string | null
    /** Set when this schema's version override is deprecated by the vendor; null when there is no override or it is not deprecated. The source-level field covers the source pin. */
    readonly api_version_deprecation: ExternalDataSourceApiVersionDeprecationApi | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedExternalDataSchemaListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExternalDataSchemaApi[]
}

/**
 * @nullable
 */
export type PatchedExternalDataSchemaApiTable = { [key: string]: unknown } | null

export type PatchedExternalDataSchemaApiRowFiltersItem = {
    column: string
    /** One of: > >= < <= = != IN "NOT IN". */
    operator: string
    /** Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`). */
    value: unknown
}

export type PatchedExternalDataSchemaApiAvailableColumnsItem = {
    name: string
    data_type?: string
    is_nullable?: boolean
}

/**
 * Lightweight parent-source summary (id, source_type, access_method, column-selection support, the requesting user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so read-only views can render without fetching the full source and all its schemas.
 * @nullable
 */
export type PatchedExternalDataSchemaApiSource = {
    readonly id?: string
    readonly source_type?: string
    readonly access_method?: string
    readonly supports_column_selection?: boolean
    readonly supports_row_filters?: boolean
    readonly requires_exact_column_metadata?: boolean
    /** @nullable */
    readonly user_access_level?: string | null
    /** @nullable */
    readonly api_version?: string | null
    readonly supported_api_versions?: string[]
} | null

/**
 * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
 */
export interface PatchedExternalDataSchemaApi {
    readonly id?: string
    readonly name?: string
    /** @nullable */
    readonly label?: string | null
    /** @nullable */
    readonly table?: PatchedExternalDataSchemaApiTable
    should_sync?: boolean
    /** @nullable */
    readonly last_synced_at?: string | null
    /**
     * The latest error that occurred when syncing this schema.
     * @nullable
     */
    readonly latest_error?: string | null
    readonly incremental?: boolean
    /** @nullable */
    readonly status?: string | null
    /** Sync strategy: incremental, full_refresh, append, cdc, or xmin.
     *
     * * `full_refresh` - full_refresh
     * * `incremental` - incremental
     * * `append` - append
     * * `webhook` - webhook
     * * `cdc` - cdc
     * * `xmin` - xmin */
    sync_type?: ExternalDataSchemaSyncTypeEnumApi | null
    /**
     * Column name used to track sync progress.
     * @nullable
     */
    incremental_field?: string | null
    /** Data type of the incremental field.
     *
     * * `integer` - integer
     * * `numeric` - numeric
     * * `datetime` - datetime
     * * `date` - date
     * * `timestamp` - timestamp
     * * `objectid` - objectid
     * * `xid` - xid */
    incremental_field_type?: IncrementalFieldTypeEnumApi | null
    /**
     * Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).
     * @minimum 0
     * @maximum 5184000
     * @nullable
     */
    incremental_field_lookback_seconds?: number | null
    /** How often to sync. The fastest sync frequency is 5 minutes.
     *
     * * `never` - never
     * * `5min` - 5min
     * * `15min` - 15min
     * * `30min` - 30min
     * * `1hour` - 1hour
     * * `6hour` - 6hour
     * * `12hour` - 12hour
     * * `24hour` - 24hour
     * * `7day` - 7day
     * * `30day` - 30day */
    sync_frequency?: ExternalDataSchemaSyncFrequencyEnumApi | null
    /**
     * UTC time of day to run the sync (HH:MM:SS).
     * @nullable
     */
    sync_time_of_day?: string | null
    /**
     * Days between scheduled full refreshes, from 1 to 90, or null for none. A full refresh wipes the table and re-imports every row, so rows deleted at the source are removed. It runs on the first scheduled sync once the interval has passed, counted from when it was saved or from the last full resync (or, when full_refresh_time_of_day is set, from the slot of that time the last refresh served), and can start up to an hour early. Queries keep returning the current rows until a full refresh finishes, and workflows and destinations that run on new rows of the table run again for every row. Available for incremental, append, and xmin syncs only, and never shorter than the sync frequency.
     * @minimum 1
     * @maximum 90
     * @nullable
     */
    full_refresh_interval_days?: number | null
    /**
     * UTC time of day (HH:MM:SS) that scheduled full refreshes are due, for example outside working hours. The refresh runs on the first scheduled sync from up to an hour before this time, so on a table that syncs every few hours it can run hours later. Each interval counts from the slot of this time that the last refresh or save served, where a slot less than an hour away counts as served. Saving a new time restarts the clock, so the first refresh after a save can come up to a day before a full interval has passed. Null counts the interval from when it was saved or from the last full resync. Cleared when full_refresh_interval_days is null.
     * @nullable
     */
    full_refresh_time_of_day?: string | null
    /**
     * When the next scheduled full refresh is due. The first scheduled sync that starts at most an hour before this time re-imports the table. Saving a new interval or time, or any full resync, moves it one interval ahead, onto full_refresh_time_of_day when that is set.
     * @nullable
     */
    readonly next_full_refresh_at?: string | null
    /** @nullable */
    readonly description?: string | null
    /**
     * Column names for primary key deduplication.
     * @nullable
     */
    primary_key_columns?: string[] | null
    /** For CDC syncs: consolidated, cdc_only, or both.
     *
     * * `consolidated` - consolidated
     * * `cdc_only` - cdc_only
     * * `both` - both */
    cdc_table_mode?: CdcTableModeEnumApi | null
    /** Why the last sync run could not merge rows for this table, or `null` when no such failure is current, which includes a run that failed for another reason. A blocked table is disabled, and the resolution differs by reason. `missing_primary_key`: no key to merge on, so set `primary_key_columns` to a unique key, which is accepted because none was set before. `duplicate_primary_key`: the key in use does not identify one row, and that key cannot be swapped once data has synced, so either remove the duplicates at the source and set `should_sync` to true, or delete the synced data before setting a different key. Either reason also accepts a different `sync_type`: `append` is only safe for insert-only tables, because updated rows arrive again as duplicates, and `full_refresh` re-reads the whole table on every sync and bills every row. This reports the last run's failure, so it clears once a run succeeds or fails for another reason, not when an update lands.
     *
     * * `missing_primary_key` - Missing primary key
     * * `duplicate_primary_key` - Duplicate primary key */
    readonly incremental_sync_blocked?: IncrementalSyncBlockedReasonEnumApi | null
    /**
     * Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.
     * @nullable
     */
    enabled_columns?: string[] | null
    /**
     * Predicates ANDed onto the source query so only matching rows sync. Each is `{column, operator, value}`; `null`/empty (default) syncs all rows. The operator must be one of `> >= < <= = != IN "NOT IN"` and the value must match the column's type (for `IN`/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). Applied on the next sync — not retroactive to already-synced rows.
     * @nullable
     */
    row_filters?: PatchedExternalDataSchemaApiRowFiltersItem[] | null
    /**
     * Columns a row filter on this schema may use, with the operators each accepts. `null` means any column in `available_columns` with any operator, which is the case for SQL sources. A list means the source can filter on these columns only; an empty list means this schema accepts no row filter.
     * @nullable
     */
    readonly row_filter_columns?: readonly RowFilterColumnApi[] | null
    /** Column metadata (name, data type, nullable) for this schema. For SQL sources this is the source-side schema discovered via `refresh_schemas`; for other sources (and once synced) it falls back to the synced table's columns. Empty only before the first successful sync/refresh. */
    readonly available_columns?: readonly PatchedExternalDataSchemaApiAvailableColumnsItem[]
    /** Whether exact source-side column metadata is available for safe source-query projection. */
    readonly source_column_metadata_available?: boolean
    /**
     * Lightweight parent-source summary (id, source_type, access_method, column-selection support, the requesting user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so read-only views can render without fetching the full source and all its schemas.
     * @nullable
     */
    readonly source?: PatchedExternalDataSchemaApiSource
    /**
     * Vendor API version override for this schema. `null` (default) syncs on the source's pinned version. Must be one of the source type's supported versions. User-managed: version-migration tooling never changes it. Not available for webhook-sync schemas.
     * @maxLength 128
     * @nullable
     */
    api_version?: string | null
    /** Set when this schema's version override is deprecated by the vendor; null when there is no override or it is not deprecated. The source-level field covers the source pin. */
    readonly api_version_deprecation?: ExternalDataSourceApiVersionDeprecationApi | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
}

/**
 * Response shape for a table's destination override.
 */
export interface SchemaDestinationsApi {
    /**
     * The table's own destinations, or null when it follows its source.
     * @nullable
     */
    destination_ids: string[] | null
    /** Whether this table follows its source rather than having its own destinations. */
    inherits_from_source: boolean
    /** Where the table actually syncs, after inheritance is resolved. */
    effective_destination_ids?: string[]
}

export interface PatchedDestinationLinkApi {
    /**
     * Destinations to sync to. On a table, null clears the override so the table follows its source again.
     * @nullable
     */
    destination_ids?: string[] | null
}

/**
 * * `web` - web
 * * `api` - api
 * * `mcp` - mcp
 * * `wizard` - wizard
 * * `self_driving` - self_driving
 */
export type ExternalDataSourceCreatedViaEnumApi =
    (typeof ExternalDataSourceCreatedViaEnumApi)[keyof typeof ExternalDataSourceCreatedViaEnumApi]

export const ExternalDataSourceCreatedViaEnumApi = {
    Web: 'web',
    Api: 'api',
    Mcp: 'mcp',
    Wizard: 'wizard',
    SelfDriving: 'self_driving',
} as const

/**
 * * `warehouse` - warehouse
 * * `direct` - direct
 */
export type ExternalDataSourceAccessMethodEnumApi =
    (typeof ExternalDataSourceAccessMethodEnumApi)[keyof typeof ExternalDataSourceAccessMethodEnumApi]

export const ExternalDataSourceAccessMethodEnumApi = {
    Warehouse: 'warehouse',
    Direct: 'direct',
} as const

/**
 * * `duckdb` - duckdb
 * * `postgres` - postgres
 * * `mysql` - mysql
 * * `snowflake` - snowflake
 * * `redshift` - redshift
 * * `clickhouse` - clickhouse
 * * `motherduck` - motherduck
 * * `trino` - trino
 */
export type EngineEnumApi = (typeof EngineEnumApi)[keyof typeof EngineEnumApi]

export const EngineEnumApi = {
    Duckdb: 'duckdb',
    Postgres: 'postgres',
    Mysql: 'mysql',
    Snowflake: 'snowflake',
    Redshift: 'redshift',
    Clickhouse: 'clickhouse',
    Motherduck: 'motherduck',
    Trino: 'trino',
} as const

export interface ExternalDataSourceRevenueAnalyticsConfigApi {
    enabled?: boolean
    include_invoiceless_charges?: boolean
}

export type ExternalDataSourceSerializersApiSchemasItem = { [key: string]: unknown }

/**
 * Mixin for serializers to add user access control fields
 */
export interface ExternalDataSourceSerializersApi {
    readonly id: string
    readonly created_at: string
    /** @nullable */
    readonly created_by: string | null
    /** How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.
     *
     * * `web` - web
     * * `api` - api
     * * `mcp` - mcp
     * * `wizard` - wizard
     * * `self_driving` - self_driving */
    created_via?: ExternalDataSourceCreatedViaEnumApi | null
    readonly status: string
    client_secret: string
    account_id: string
    /** The source type (e.g. 'Postgres', 'Stripe'). */
    readonly source_type: string
    /** @nullable */
    readonly latest_error: string | null
    /**
     * @maxLength 100
     * @nullable
     */
    prefix?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    readonly access_method: ExternalDataSourceAccessMethodEnumApi
    /** Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources. */
    direct_query_enabled?: boolean
    /** Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources. */
    auto_sync_new_schemas?: boolean
    /**
     * Optional fnmatch-style globs (`*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.
     * @maxItems 100
     * @nullable
     * @items.maxLength 250
     */
    auto_sync_schema_patterns?: string[] | null
    /** Backend engine detected for the direct connection.
     *
     * * `duckdb` - duckdb
     * * `postgres` - postgres
     * * `mysql` - mysql
     * * `snowflake` - snowflake
     * * `redshift` - redshift
     * * `clickhouse` - clickhouse
     * * `motherduck` - motherduck
     * * `trino` - trino */
    readonly engine: EngineEnumApi | null
    /** @nullable */
    readonly last_run_at: string | null
    readonly schemas: readonly ExternalDataSourceSerializersApiSchemasItem[]
    job_inputs?: unknown
    readonly revenue_analytics_config: ExternalDataSourceRevenueAnalyticsConfigApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    readonly supports_webhooks: boolean
    /** Whether this source supports per-column sync selection via `enabled_columns`. */
    readonly supports_column_selection: boolean
    /**
     * Vendor API version this source is pinned to (an opaque vendor label, e.g. a Stripe date version). Null resolves to the source type's default version at sync time.
     * @nullable
     */
    readonly api_version: string | null
    /** Set when the vendor has deprecated the API version this source is pinned to; null otherwise. Drives the in-product deprecation warning. */
    readonly api_version_deprecation: ExternalDataSourceApiVersionDeprecationApi | null
    /**
     * Set on an update response when the change was saved but the connection check from the API could not reach the database. Null otherwise.
     * @nullable
     */
    readonly connection_warning: string | null
}

export interface PaginatedExternalDataSourceSerializersListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExternalDataSourceSerializersApi[]
}

/**
 * Connection credentials. Keys depend on source_type. Add a 'schemas' array to pick which tables sync; omit it and every discovered table syncs with default settings.
 */
export type ExternalDataSourceCreateApiPayload = { [key: string]: unknown }

/**
 * * `web` - web
 * * `api` - api
 * * `mcp` - mcp
 */
export type ExternalDataSourceCreateCreatedViaEnumApi =
    (typeof ExternalDataSourceCreateCreatedViaEnumApi)[keyof typeof ExternalDataSourceCreateCreatedViaEnumApi]

export const ExternalDataSourceCreateCreatedViaEnumApi = {
    Web: 'web',
    Api: 'api',
    Mcp: 'mcp',
} as const

export interface ExternalDataSourceCreateApi {
    /** The source type (e.g. 'Postgres', 'Stripe'). */
    source_type: string
    /** Connection credentials. Keys depend on source_type. Add a 'schemas' array to pick which tables sync; omit it and every discovered table syncs with default settings. */
    payload: ExternalDataSourceCreateApiPayload
    /**
     * Prefix added to the table names PostHog creates in HogQL. Does not filter which tables are imported.
     * @maxLength 100
     * @nullable
     */
    prefix?: string | null
    /**
     * Human-readable description.
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** Connection mode: 'warehouse' (import) or 'direct' (live query).
     *
     * * `warehouse` - warehouse
     * * `direct` - direct */
    access_method?: ExternalDataSourceAccessMethodEnumApi
    /** Where the request came from: `web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls. `wizard` and `self_driving` cannot be set directly — they are derived server-side for wizard- and PostHog Desktop-driven MCP calls. Defaults to `api`.
     *
     * * `web` - web
     * * `api` - api
     * * `mcp` - mcp */
    created_via?: ExternalDataSourceCreateCreatedViaEnumApi
    /** Whether a synced source should also be live-queryable via direct connection. Defaults to false; ignored for pure direct-query sources. */
    direct_query_enabled?: boolean
    /** Destinations every table on this source writes to. Set here rather than afterwards, so the opening sync already carries them. Omit to write to the PostHog warehouse only. */
    destination_ids?: string[]
}

export interface ExternalDataSourceCreateResponseApi {
    /** ID of the created external data source. */
    id: string
}

export type PatchedExternalDataSourceSerializersApiSchemasItem = { [key: string]: unknown }

/**
 * Mixin for serializers to add user access control fields
 */
export interface PatchedExternalDataSourceSerializersApi {
    readonly id?: string
    readonly created_at?: string
    /** @nullable */
    readonly created_by?: string | null
    /** How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls, `wizard` for the setup wizard and `self_driving` for the PostHog Desktop app (both derived server-side from the caller's user agent). Ignored on update.
     *
     * * `web` - web
     * * `api` - api
     * * `mcp` - mcp
     * * `wizard` - wizard
     * * `self_driving` - self_driving */
    created_via?: ExternalDataSourceCreatedViaEnumApi | null
    readonly status?: string
    client_secret?: string
    account_id?: string
    /** The source type (e.g. 'Postgres', 'Stripe'). */
    readonly source_type?: string
    /** @nullable */
    readonly latest_error?: string | null
    /**
     * @maxLength 100
     * @nullable
     */
    prefix?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    readonly access_method?: ExternalDataSourceAccessMethodEnumApi
    /** Whether this synced source is also live-queryable via direct connection. Defaults to false for new sources; ignored for pure direct-query sources. */
    direct_query_enabled?: boolean
    /** Automatically enable syncing for schemas discovered on this source after creation, on both the scheduled discovery pass and manual schema refreshes. Defaults to false. Not supported for direct-query sources. */
    auto_sync_new_schemas?: boolean
    /**
     * Optional fnmatch-style globs (`*` and `?` wildcards) restricting which newly discovered schema names auto-sync, matched case-insensitively against both the qualified and bare table name. Null or empty means every new schema qualifies. Only used when `auto_sync_new_schemas` is true.
     * @maxItems 100
     * @nullable
     * @items.maxLength 250
     */
    auto_sync_schema_patterns?: string[] | null
    /** Backend engine detected for the direct connection.
     *
     * * `duckdb` - duckdb
     * * `postgres` - postgres
     * * `mysql` - mysql
     * * `snowflake` - snowflake
     * * `redshift` - redshift
     * * `clickhouse` - clickhouse
     * * `motherduck` - motherduck
     * * `trino` - trino */
    readonly engine?: EngineEnumApi | null
    /** @nullable */
    readonly last_run_at?: string | null
    readonly schemas?: readonly PatchedExternalDataSourceSerializersApiSchemasItem[]
    job_inputs?: unknown
    readonly revenue_analytics_config?: ExternalDataSourceRevenueAnalyticsConfigApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
    readonly supports_webhooks?: boolean
    /** Whether this source supports per-column sync selection via `enabled_columns`. */
    readonly supports_column_selection?: boolean
    /**
     * Vendor API version this source is pinned to (an opaque vendor label, e.g. a Stripe date version). Null resolves to the source type's default version at sync time.
     * @nullable
     */
    readonly api_version?: string | null
    /** Set when the vendor has deprecated the API version this source is pinned to; null otherwise. Drives the in-product deprecation warning. */
    readonly api_version_deprecation?: ExternalDataSourceApiVersionDeprecationApi | null
    /**
     * Set on an update response when the change was saved but the connection check from the API could not reach the database. Null otherwise.
     * @nullable
     */
    readonly connection_warning?: string | null
}

export type ExternalDataSourceBulkUpdateSchemaApiRowFiltersItem = {
    column: string
    /** One of: > >= < <= = != IN "NOT IN". */
    operator: string
    /** Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`). */
    value: unknown
}

export interface ExternalDataSourceBulkUpdateSchemaApi {
    /** Schema identifier to update. */
    id: string
    /** Whether the schema should be queryable/synced. */
    should_sync?: boolean
    /** Requested sync mode for the schema (incremental, full_refresh, append, cdc, or xmin).
     *
     * * `full_refresh` - full_refresh
     * * `incremental` - incremental
     * * `append` - append
     * * `webhook` - webhook
     * * `cdc` - cdc
     * * `xmin` - xmin */
    sync_type?: ExternalDataSchemaSyncTypeEnumApi | null
    /**
     * Incremental cursor field for incremental or append syncs.
     * @nullable
     */
    incremental_field?: string | null
    /**
     * Type of the incremental cursor field.
     * @nullable
     */
    incremental_field_type?: string | null
    /**
     * Human-readable sync frequency value.
     * @nullable
     */
    sync_frequency?: string | null
    /**
     * UTC anchor time for scheduled syncs.
     * @nullable
     */
    sync_time_of_day?: string | null
    /**
     * Days between scheduled full refreshes, from 1 to 90, or null for none. A full refresh wipes the table and re-imports every row. Re-imported rows count toward usage, and workflows and destinations that run on new rows of the table run again for every row. Incremental, append, and xmin syncs only, and never shorter than the sync frequency.
     * @minimum 1
     * @maximum 90
     * @nullable
     */
    full_refresh_interval_days?: number | null
    /**
     * UTC time of day (HH:MM:SS) that scheduled full refreshes are due, for example outside working hours. The refresh runs on the first scheduled sync from up to an hour before this time, so on a table that syncs every few hours it can run hours later. Each interval counts from the slot of this time that the last refresh or save served, where a slot less than an hour away counts as served. Saving a new time restarts the clock, so the first refresh after a save can come up to a day before a full interval has passed. Null counts the interval from when it was saved or from the last full resync. Cleared when full_refresh_interval_days is null.
     * @nullable
     */
    full_refresh_time_of_day?: string | null
    /**
     * Column names for primary key deduplication.
     * @nullable
     */
    primary_key_columns?: string[] | null
    /** How CDC-backed tables should be exposed.
     *
     * * `consolidated` - consolidated
     * * `cdc_only` - cdc_only
     * * `both` - both */
    cdc_table_mode?: CdcTableModeEnumApi | null
    /**
     * Columns to sync. Null means sync all columns.
     * @nullable
     */
    enabled_columns?: string[] | null
    /**
     * Row-filter predicates ANDed onto the source query. Null/empty means sync all rows.
     * @nullable
     */
    row_filters?: ExternalDataSourceBulkUpdateSchemaApiRowFiltersItem[] | null
    /** When true and the schema has no sync method configured yet (and this update does not set one), discover the table on the source and fill in default sync settings: incremental sync with an auto-selected tracking column where supported, otherwise append, otherwise full refresh. Ignored for schemas that already have a sync method. */
    apply_sync_defaults?: boolean
}

export interface ExternalDataSourceBulkUpdateSchemasApi {
    /** Schema updates to apply in a single batch. */
    schemas: ExternalDataSourceBulkUpdateSchemaApi[]
}

/**
 * * `posthog` - posthog
 * * `self_managed` - self_managed
 */
export type ManagementModeEnumApi = (typeof ManagementModeEnumApi)[keyof typeof ManagementModeEnumApi]

export const ManagementModeEnumApi = {
    Posthog: 'posthog',
    SelfManaged: 'self_managed',
} as const

export interface CdcStatusApi {
    /** Whether CDC is enabled on this source. */
    enabled: boolean
    /** Who owns the slot and publication: PostHog or the customer.
     *
     * * `posthog` - posthog
     * * `self_managed` - self_managed */
    management_mode?: ManagementModeEnumApi
    /** Replication slot PostHog consumes from. Empty when unset. */
    slot_name?: string
    /** Publication PostHog reads changes from. Empty when unset. */
    publication_name?: string
    /** Lag in MB above which the UI warns. */
    lag_warning_threshold_mb?: number
    /** Lag in MB above which the UI alerts. */
    lag_critical_threshold_mb?: number
    /** True when a non-retryable failure paused the extraction schedule; the UI then offers Resume instead of Repair. Degrades to false when the schedule lookup fails. */
    schedule_paused?: boolean
    /** Whether the replication slot exists on the source, when the source was reachable. */
    slot_exists?: boolean
    /** Whether the publication exists on the source, when the source was reachable. */
    publication_exists?: boolean
    /**
     * Current slot lag in bytes, when the source was reachable.
     * @nullable
     */
    lag_bytes?: number | null
    /** Tables in the publication, when the source was reachable and a publication exists. */
    published_tables?: string[]
}

export interface CreateWebhookResponseApi {
    /** Whether the webhook was created and registered with the source. */
    success: boolean
    /**
     * The PostHog endpoint the external service delivers events to.
     * @nullable
     */
    webhook_url: string | null
    /**
     * Why creation failed, when success is false.
     * @nullable
     */
    error: string | null
    /** Inputs the external service needs before delivery works. Submit via update_webhook_inputs. */
    pending_inputs: string[]
}

export interface DeleteWebhookResponseApi {
    /** Whether the webhook delivery function was deleted. */
    success: boolean
    /** Whether the webhook was also removed from the external service. False when the source config was already gone and only the local function was cleaned up, or when the external call failed. */
    external_deleted: boolean
    /**
     * Why the external deletion failed, when external_deleted is false.
     * @nullable
     */
    error: string | null
}

/**
 * Response shape for a source's destination set.
 */
export interface SourceDestinationsApi {
    /** Destinations every table on this source syncs to. */
    destination_ids: string[]
}

export interface CdcEnableResponseApi {
    /** Whether CDC was enabled on the source. */
    success: boolean
    /** Whether the extraction and cleanup schedules could be created. False means CDC is enabled but scheduling failed; the schedule self-heals on the first CDC schema toggle. */
    schedules_ready: boolean
}

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export interface SimpleExternalDataSchemaApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    /**
     * @maxLength 400
     * @nullable
     */
    label?: string | null
    should_sync?: boolean
    /** @nullable */
    last_synced_at?: string | null
    sync_type?: ExternalDataSchemaSyncTypeEnumApi | BlankEnumApi | null
}

export interface ExternalDataJobSerializersApi {
    readonly id: string
    readonly created_at: string
    /** @nullable */
    readonly created_by: number | null
    /** @nullable */
    readonly finished_at: string | null
    readonly status: string
    readonly schema: SimpleExternalDataSchemaApi
    /** @nullable */
    readonly rows_synced: number | null
    /**
     * The latest error that occurred during this run.
     * @nullable
     */
    readonly latest_error: string | null
    /** @nullable */
    readonly workflow_run_id: string | null
    /**
     * For CDC syncs with `cdc_table_mode='both'`, distinguishes the two ExternalDataJob rows produced per sync: `incremental_merge` (consolidated table) vs `scd2_append` (cdc-only history table). `null` for non-CDC syncs. Read from `schema_snapshot`.
     * @nullable
     */
    readonly cdc_write_mode: string | null
    /**
     * Whether the rows synced by this job count toward billing. `false` for system-initiated runs the customer isn't charged for (e.g. rebuilding a table after an internal issue). `null` on legacy rows and means billable.
     * @nullable
     */
    readonly billable: boolean | null
    /** Destinations this run delivered to, snapshotted when it started. Empty on runs that predate destinations, which wrote to the PostHog warehouse alone. `rows_synced` counts the rows read from the source once, not once per destination. */
    readonly destination_ids: readonly string[]
}

export interface UpdateWebhookInputsResponseApi {
    /** Whether the inputs were saved and pushed to the external service. */
    success: boolean
}

/**
 * Resource name to external schema id, as configured on the webhook function.
 */
export type WebhookInfoResponseApiSchemaMapping = { [key: string]: string }

/**
 * * `hog` - hog
 * * `liquid` - liquid
 */
export type HogFunctionTemplatingEnumApi =
    (typeof HogFunctionTemplatingEnumApi)[keyof typeof HogFunctionTemplatingEnumApi]

export const HogFunctionTemplatingEnumApi = {
    Hog: 'hog',
    Liquid: 'liquid',
} as const

export interface InputsItemApi {
    value?: unknown
    templating?: HogFunctionTemplatingEnumApi
    readonly bytecode: readonly unknown[]
    readonly bytecode_contract: string
    readonly order: number
    readonly transpiled: unknown
}

/**
 * Current webhook function inputs keyed by the source's declared webhook field names.
 */
export type WebhookInfoResponseApiInputs = { [key: string]: InputsItemApi }

/**
 * Delivery health reported by the pipeline: `state` and `tokens` counters.
 */
export type WebhookHogFunctionApiStatus = { [key: string]: unknown }

export interface WebhookHogFunctionApi {
    /** ID of the webhook delivery hog function. */
    id: string
    /** Name of the webhook delivery hog function. */
    name: string
    /** Whether the webhook delivery function is enabled. */
    enabled: boolean
    /** When the webhook delivery function was created (ISO 8601). */
    created_at: string
    /** Delivery health reported by the pipeline: `state` and `tokens` counters. */
    status: WebhookHogFunctionApiStatus
}

export interface WebhookExternalStatusApi {
    /** Whether the webhook exists on the external service. */
    exists: boolean
    /**
     * The webhook URL on the external service.
     * @nullable
     */
    url: string | null
    /**
     * Events the external webhook is subscribed to.
     * @nullable
     */
    enabled_events: string[] | null
    /**
     * Delivery health as the external service reports it (e.g. 'enabled').
     * @nullable
     */
    status: string | null
    /**
     * Description the external service holds for it.
     * @nullable
     */
    description: string | null
    /**
     * When the external webhook was created.
     * @nullable
     */
    created_at: string | null
    /**
     * Vendor API version the endpoint delivers at, when pinned.
     * @nullable
     */
    api_version: string | null
    /**
     * Read error the external service returned, if any.
     * @nullable
     */
    error: string | null
}

export interface WebhookInfoResponseApi {
    /** Whether the source type supports webhooks at all. When false, the other fields are absent. */
    supports_webhooks: boolean
    /** Whether a PostHog webhook delivery function exists for this source yet. */
    exists: boolean
    /**
     * Set when the connection's credentials can never create the webhook, so only manual setup is left. Null means 'not known to be blocked'.
     * @nullable
     */
    auto_creation_blocked_reason: string | null
    /** The webhook delivery function, present once the webhook exists. */
    hog_function: WebhookHogFunctionApi | null
    /**
     * The PostHog endpoint the external service delivers events to.
     * @nullable
     */
    webhook_url: string | null
    /** Resource name to external schema id, as configured on the webhook function. */
    schema_mapping: WebhookInfoResponseApiSchemaMapping
    /** Current webhook function inputs keyed by the source's declared webhook field names. */
    inputs?: WebhookInfoResponseApiInputs
    /** Live webhook state as the external service reports it, when it could be read. */
    external_status: WebhookExternalStatusApi | null
    /** Desired provider events not yet on the webhook (manual setup, or created before a new table). */
    missing_events?: string[]
    /** Required webhook field names with no value yet. Deliveries are dropped while any is missing. */
    missing_inputs?: string[]
}

export interface CdcPrerequisitesResponseApi {
    /** Whether the source satisfies every CDC prerequisite. */
    valid: boolean
    /** Unmet prerequisites, empty when valid is true. */
    errors: string[]
}

/**
 * * `oauth` - oauth
 * * `credentials` - credentials
 */
export type AuthMethodEnumApi = (typeof AuthMethodEnumApi)[keyof typeof AuthMethodEnumApi]

export const AuthMethodEnumApi = {
    Oauth: 'oauth',
    Credentials: 'credentials',
} as const

export interface SourceConnectLinkApi {
    /** The source type the link is for. */
    source_type: string
    /** What the user will do on the connect page: 'oauth' = authorize an account in their browser; 'credentials' = enter connection details (or pick OAuth where the source offers both). Either way secrets never pass through the agent, and the result is always a stored credential id.
     *
     * * `oauth` - oauth
     * * `credentials` - credentials */
    auth_method: AuthMethodEnumApi
    /** Full URL to share with the user. It opens the source's connection form in PostHog — credentials never pass through the agent or the chat. */
    connect_url: string
    /** Next steps for the agent to relay to the user. */
    instructions: string
}

export interface ExternalDataSourceConnectionOptionApi {
    readonly id: string
    /**
     * Default database schema used to group tables in the SQL editor.
     * @nullable
     */
    readonly schema_name: string | null
    /** @nullable */
    readonly prefix: string | null
    /** Backend engine detected for the direct connection.
     *
     * * `duckdb` - duckdb
     * * `postgres` - postgres
     * * `mysql` - mysql
     * * `snowflake` - snowflake
     * * `redshift` - redshift
     * * `clickhouse` - clickhouse
     * * `motherduck` - motherduck
     * * `trino` - trino */
    readonly engine: EngineEnumApi | null
    /** The source type (e.g. 'Postgres', 'MySQL', 'Snowflake'). */
    readonly source_type: string
    /** 'direct' for pure live-query sources; 'warehouse' for synced sources with direct query enabled.
     *
     * * `warehouse` - warehouse
     * * `direct` - direct */
    readonly access_method: ExternalDataSourceAccessMethodEnumApi
    /** Whether HogQL queries compile for this connection. When false, only raw SQL (sendRawQuery) works. */
    readonly supports_hogql: boolean
    /** Whether this option is the built-in PostHog managed warehouse connection. */
    readonly is_builtin_managed_warehouse: boolean
    /**
     * User-set description of the source, shown as its display name in the connection picker when set.
     * @nullable
     */
    readonly description: string | null
}

/**
 * Values of the sibling fields named by the picker's `credentialFields`. Any other key is rejected.
 */
export type CredentialAccountsRequestApiCredentials = { [key: string]: string }

/**
 * Body for listing accounts from credentials the user has typed but not yet submitted.
 */
export interface CredentialAccountsRequestApi {
    /** The data warehouse source type whose picker is asking (e.g. 'AppleSearchAds'). */
    source_type: string
    /** Values of the sibling fields named by the picker's `credentialFields`. Any other key is rejected. */
    credentials: CredentialAccountsRequestApiCredentials
    /**
     * Vendor API version the source is pinned to. Defaults to the source's current default.
     * @nullable
     */
    api_version?: string | null
}

/**
 * A selectable account/resource exposed by an OAuth integration, in the shared shape every ad
 * platform produces (see ``IntegrationAccount`` in the data-imports common module). One serializer
 * and one frontend selector work across all platforms.
 */
export interface IntegrationAccountApi {
    /** The identifier stored in the source config and used for API calls (numeric account id as a string, a site url, etc.). */
    value: string
    /** Primary human-readable label for the account. */
    display_name: string
    /** True when this account belongs to the connected user's own (primary) account context, rather than one they merely have access to. Sorted/marked first. */
    is_primary: boolean
    /** Short status chips for the account, e.g. ['Active'] or ['Pause']. */
    badges: string[]
    /**
     * Optional grouping label for hierarchical platforms (e.g. the owning customer/manager name).
     * @nullable
     */
    group: string | null
    /**
     * Extra identifier shown in parentheses and searchable, e.g. the alphanumeric account number.
     * @nullable
     */
    secondary_text: string | null
}

export interface IntegrationAccountsResponseApi {
    /** All accounts the connected integration can access. */
    accounts: IntegrationAccountApi[]
}

/**
 * Validate credentials and preview available tables from a remote database.
 *
 * The request body contains source_type plus flat source-specific credential fields
 * (e.g. host, port, database, user, password, schema for Postgres). The credential
 * fields vary per source_type and are validated dynamically by the source registry.
 *
 * For source_type "Custom" (a user-defined REST API) the body carries `manifest_json`
 * (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the
 * credential for the manifest's declared auth type — `auth_token` (bearer), `auth_api_key`
 * (api_key), or `auth_password` (http_basic); keep secrets in these auth_* keys, never
 * inline in manifest_json. The returned tables mirror the manifest's resources, with
 * detected primary keys and incremental cursors.
 */
export interface DatabaseSchemaRequestApi {
    /** The source type to validate against. */
    source_type: string
}

/**
 * A source type that can be added as a direct (live-query) connection, with display metadata.
 */
export interface DirectConnectionSourceOptionApi {
    /** The source type to start a direct-connection setup for (e.g. 'Postgres', 'ClickHouse'). */
    readonly source_type: string
    /** Human-readable name to show in the picker (falls back to the source type). */
    readonly label: string
    /**
     * Path to the source's icon asset, or null when the source ships no icon.
     * @nullable
     */
    readonly icon_path: string | null
}

export interface DraftCustomManifestRequestApi {
    /** Optional human name of the API being connected (e.g. 'Acme CRM'). Used only to orient the model. */
    source_name?: string
    /** URL of the API documentation to read. Provide this or docs_text; fetched server-side via the egress proxy. */
    docs_url?: string
    /** Raw API documentation or an OpenAPI/Swagger spec, pasted directly. Provide this or docs_url. */
    docs_text?: string
}

/**
 * * `ok` - ok
 * * `invalid` - invalid
 * * `model_error` - model_error
 */
export type DraftStatusEnumApi = (typeof DraftStatusEnumApi)[keyof typeof DraftStatusEnumApi]

export const DraftStatusEnumApi = {
    Ok: 'ok',
    Invalid: 'invalid',
    ModelError: 'model_error',
} as const

export interface DraftCustomManifestResponseApi {
    /** 'ok' = a manifest validated; 'invalid' = a manifest was drafted but never validated within the budget (see error; manifest_json holds the last attempt to fix by hand); 'model_error' = the model returned no usable JSON.
     *
     * * `ok` - ok
     * * `invalid` - invalid
     * * `model_error` - model_error */
    draft_status: DraftStatusEnumApi
    /**
     * The drafted RESTAPIConfig manifest as a JSON string (non-secret), or null if none was produced.
     * @nullable
     */
    manifest_json: string | null
    /** Names of the resources (tables) the validated manifest exposes. Empty unless draft_status is 'ok'. */
    resource_names: string[]
    /** How many draft→validate→repair rounds were run. */
    attempts: number
    /**
     * The last validation error when draft_status is not 'ok'; null on success.
     * @nullable
     */
    error: string | null
}

/**
 * Source config as flat keys. For source_type 'Custom': 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the manifest's declared auth type — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic). Secrets stay in these auth_* keys, never inline in the manifest.
 */
export type SourcePreviewRequestApiPayload = { [key: string]: unknown }

export interface SourcePreviewRequestApi {
    /** The source type to preview. Only 'Custom' (a user-defined REST API) is supported today. */
    source_type: string
    /** Source config as flat keys. For source_type 'Custom': 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the manifest's declared auth type — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic). Secrets stay in these auth_* keys, never inline in the manifest. */
    payload?: SourcePreviewRequestApiPayload
    /** Which manifest resource (table) to read a sample from — one of the resource names in manifest_json. */
    resource_name: string
    /**
     * Maximum sample rows to return (1–50). Defaults to 10.
     * @minimum 1
     * @maximum 50
     */
    limit?: number
}

export type SourcePreviewResponseApiRowsItem = { [key: string]: unknown }

export interface SourcePreviewColumnApi {
    /** Column name as it appears in the previewed rows. */
    name: string
    /** JSON type inferred from the first non-null value: string, integer, number, boolean, object, array, or null. */
    type: string
}

export interface SourcePreviewResponseApi {
    /** Up to `limit` sample rows, after data_selector extraction — the raw records the sync would ingest. */
    rows: SourcePreviewResponseApiRowsItem[]
    /** Number of sample rows returned (≤ limit). */
    row_count: number
    /** Columns observed across the sample rows, each with an inferred JSON type. */
    columns: SourcePreviewColumnApi[]
    /**
     * Set when the live read failed (e.g. the host was unreachable or returned an auth error); rows is then empty. Manifest, validation, and SSRF problems return HTTP 400 instead of populating this field.
     * @nullable
     */
    error: string | null
}

/**
 * Connection details as flat keys for the source_type (discover required fields with the wizard tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection details the user stored via the connect-link page (discover ids with the stored_credentials endpoint) — they are merged in server-side and deleted once consumed. An already-connected OAuth integration can be passed via its id key instead (e.g. {'hubspot_integration_id': 123}). For source_type 'Custom' (a user-defined REST API) the keys are 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the auth type the manifest declares — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic); keep secrets in these auth_* keys, never inline in the manifest. A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible sync defaults.
 */
export type SourceSetupApiPayload = { [key: string]: unknown }

export interface SourceSetupApi {
    /** The source type to set up (e.g. 'Stripe', 'Postgres', 'Hubspot'). */
    source_type: string
    /** Connection details as flat keys for the source_type (discover required fields with the wizard tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection details the user stored via the connect-link page (discover ids with the stored_credentials endpoint) — they are merged in server-side and deleted once consumed. An already-connected OAuth integration can be passed via its id key instead (e.g. {'hubspot_integration_id': 123}). For source_type 'Custom' (a user-defined REST API) the keys are 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the auth type the manifest declares — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic); keep secrets in these auth_* keys, never inline in the manifest. A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible sync defaults. */
    payload?: SourceSetupApiPayload
    /**
     * Prefix added to the table names PostHog creates in HogQL, e.g. 'stripe' produces stripe_charges. Does not filter which tables are imported. Defaults to the source type.
     * @maxLength 100
     * @nullable
     */
    prefix?: string | null
    /**
     * Human-readable description.
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** Whether a synced source should also be live-queryable via direct connection. Defaults to false; ignored for pure direct-query sources. */
    direct_query_enabled?: boolean
}

export interface SourceSetupWebhookApi {
    /** Whether the webhook was registered with the external service. When true, webhook-capable tables (including webhook-only ones) sync via real-time webhooks; when false, tables fall back to the polling sync defaults and webhook-only tables stay disabled. */
    success: boolean
    /**
     * The PostHog endpoint the external service delivers events to.
     * @nullable
     */
    webhook_url: string | null
    /**
     * Why webhook registration failed (e.g. the credentials lack webhook permissions).
     * @nullable
     */
    error: string | null
    /** Webhook input names the user still needs to provide (e.g. a signing secret the external API did not return on create). Submit them via the update_webhook_inputs endpoint. */
    pending_inputs: string[]
}

export interface SourceSetupResponseApi {
    /** ID of the created external data source. */
    id: string
    /** Outcome of automatic webhook registration. Only present for sources that support webhooks (e.g. Stripe) and have webhook-capable tables. */
    webhook?: SourceSetupWebhookApi
}

/**
 * Connection details as flat keys for the source_type — the same fields the create flow accepts (host, port, password, API key, …). Checked against a live connection before being stored.
 */
export type SourceCredentialCreateApiPayload = { [key: string]: unknown }

export interface SourceCredentialCreateApi {
    /** The source type these credentials are for (e.g. 'Stripe', 'Postgres'). */
    source_type: string
    /** Connection details as flat keys for the source_type — the same fields the create flow accepts (host, port, password, API key, …). Checked against a live connection before being stored. */
    payload: SourceCredentialCreateApiPayload
}

export interface SourceCredentialApi {
    /** Stored credential id. Pass to the setup endpoint as {'credential_id': <id>} to create the source. */
    credential_id: string
    /** The source type the stored credentials are for. */
    source_type: string
    /** When the credentials were stored. */
    created_at: string
    /** When the stored credentials expire. Unconsumed credentials are unusable past this time. */
    expires_at: string
}

export type DataWarehouseSourceCategoryApi =
    (typeof DataWarehouseSourceCategoryApi)[keyof typeof DataWarehouseSourceCategoryApi]

export const DataWarehouseSourceCategoryApi = {
    Databases: 'Databases',
    FileStorage: 'File storage',
    Advertising: 'Advertising',
    MarketingEmail: 'Marketing & email',
    Crm: 'CRM',
    Sales: 'Sales',
    CustomerSupport: 'Customer support',
    PaymentsBilling: 'Payments & billing',
    FinanceAccounting: 'Finance & accounting',
    Analytics: 'Analytics',
    EngineeringMonitoring: 'Engineering & monitoring',
    Productivity: 'Productivity',
    HRRecruiting: 'HR & recruiting',
    Communication: 'Communication',
    ECommerce: 'E-commerce',
} as const

export type SourceFieldInputConfigTypeEnumApi =
    (typeof SourceFieldInputConfigTypeEnumApi)[keyof typeof SourceFieldInputConfigTypeEnumApi]

export const SourceFieldInputConfigTypeEnumApi = {
    Text: 'text',
    Email: 'email',
    Search: 'search',
    Url: 'url',
    Password: 'password',
    Time: 'time',
    Number: 'number',
    Textarea: 'textarea',
} as const

export interface SourceFieldInputConfigApi {
    caption?: string | null
    label: string
    name: string
    placeholder: string
    required: boolean
    /** Marks this field as containing sensitive data. The value is stripped from API responses regardless of the rendering `type` (so a multi-line PEM blob can use `textarea` and still be redacted). Required: source authors must explicitly classify every field. */
    secret: boolean
    type: SourceFieldInputConfigTypeEnumApi
}

export type SourceFieldSelectConfigConverterApi =
    (typeof SourceFieldSelectConfigConverterApi)[keyof typeof SourceFieldSelectConfigConverterApi]

export const SourceFieldSelectConfigConverterApi = {
    StrToInt: 'str_to_int',
    StrToBool: 'str_to_bool',
    StrToOptionalInt: 'str_to_optional_int',
} as const

export interface SourceFieldOauthConfigApi {
    kind: string
    label: string
    name: string
    required: boolean
    requiredScopes?: string | null
    type: 'oauth'
}

export interface SourceFieldOauthAccountSelectConfigApi {
    caption?: string | null
    /** Keep the field in the config tree (so its value parses and survives job_inputs redaction) without rendering it in the source form. Used for legacy fields that a newer field supersedes. */
    hidden?: boolean | null
    /** Name of the OAuth integration id field this account selector reads from. */
    integrationField: string
    /** Integration kind to validate and route the account fetch through. */
    integrationKind: string
    label: string
    /** Allow selecting multiple values; the field's payload value becomes string[]. */
    multiple?: boolean | null
    name: string
    placeholder?: string | null
    required?: boolean | null
    type: 'oauth-account-select'
}

/**
 * Account picker for a source whose credentials are typed into the form, not held by an
 * `Integration` row. Same `IntegrationAccount` shape and same picker as `oauth-account-select`;
 * only where the credentials come from differs.
 *
 * `credentialFields` is the security boundary. The listing endpoint accepts those field names and
 * no others, so the picker cannot be used to push arbitrary connection details into a source's
 * client.
 */
export interface SourceFieldCredentialAccountSelectConfigApi {
    caption?: string | null
    /** Names of the sibling fields whose values the account listing needs. The form sends exactly these, and the listing endpoint accepts exactly these. */
    credentialFields: string[]
    /** Name of an OAuth integration id field that lists the same accounts, for a source offering both a typed-in credential and a connected account. The form sends this instead of `credentialFields` when it holds a value, and the listing endpoint accepts it on the same allowlist. */
    integrationField?: string | null
    label: string
    name: string
    placeholder?: string | null
    required?: boolean | null
    type: 'credential-account-select'
}

export interface SourceFieldFileUploadJsonFormatConfigApi {
    format?: '.json'
    keys: '*' | string[]
}

export interface SourceFieldFileUploadConfigApi {
    fileFormat: SourceFieldFileUploadJsonFormatConfigApi
    label: string
    name: string
    required: boolean
    type: 'file-upload'
}

export interface SourceFieldSSHTunnelConfigApi {
    label: string
    name: string
    type: 'ssh-tunnel'
}

export interface SourceFieldSelectConfigOptionApi {
    fields?:
        | (
              | SourceFieldInputConfigApi
              | SourceFieldSwitchGroupConfigApi
              | SourceFieldSelectConfigApi
              | SourceFieldOauthConfigApi
              | SourceFieldOauthAccountSelectConfigApi
              | SourceFieldCredentialAccountSelectConfigApi
              | SourceFieldFileUploadConfigApi
              | SourceFieldSSHTunnelConfigApi
          )[]
        | null
    label: string
    value: string
}

export interface SourceFieldSelectConfigApi {
    caption?: string | null
    converter?: SourceFieldSelectConfigConverterApi | null
    defaultValue: string
    label: string
    /** Allow selecting multiple values; the field's payload value becomes string[]. */
    multiple?: boolean | null
    name: string
    options: SourceFieldSelectConfigOptionApi[]
    required: boolean
    type: 'select'
}

export interface SourceFieldSwitchGroupConfigApi {
    caption?: string | null
    default: string | number | boolean
    fields: (
        | SourceFieldInputConfigApi
        | SourceFieldSwitchGroupConfigApi
        | SourceFieldSelectConfigApi
        | SourceFieldOauthConfigApi
        | SourceFieldOauthAccountSelectConfigApi
        | SourceFieldCredentialAccountSelectConfigApi
        | SourceFieldFileUploadConfigApi
        | SourceFieldSSHTunnelConfigApi
    )[]
    label: string
    name: string
    type: 'switch-group'
}

export type ReleaseStatusApi = (typeof ReleaseStatusApi)[keyof typeof ReleaseStatusApi]

export const ReleaseStatusApi = {
    Alpha: 'alpha',
    Beta: 'beta',
    Ga: 'ga',
} as const

export interface SuggestedTableApi {
    table: string
    tooltip?: string | null
}

export interface SourceVersionDeprecationApi {
    version: string
    /** ISO date the vendor stops serving this version, or null when no date is announced. */
    sunsetAt?: string | null
}

export interface SourceDocumentedTableApi {
    name: string
    label: string
    description?: string | null
    sync_methods: string[]
    incremental_fields: string[]
    primary_keys: string[]
}

/**
 * A `SourceConfig` plus the runtime metadata the two catalog endpoints add per source.
 */
export interface SourceConfigResponseApi {
    caption?: string | null
    /** Catalog bucket this source is grouped under in the new-source wizard. Optional at the type level so partial/in-progress sources don't break, but every registered source must set one (enforced by a test). */
    category?: DataWarehouseSourceCategoryApi | null
    disabledReason?: string | null
    docsUrl?: string | null
    existingSource?: boolean | null
    featureFlag?: string | null
    /** Whether this source should be prominently displayed in onboarding flows */
    featured?: boolean | null
    fields: (
        | SourceFieldInputConfigApi
        | SourceFieldSwitchGroupConfigApi
        | SourceFieldSelectConfigApi
        | SourceFieldOauthConfigApi
        | SourceFieldOauthAccountSelectConfigApi
        | SourceFieldCredentialAccountSelectConfigApi
        | SourceFieldFileUploadConfigApi
        | SourceFieldSSHTunnelConfigApi
    )[]
    iconClassName?: string | null
    iconPath: string
    /** Extra search terms (alternate spellings, acronyms) for the catalog search, e.g. GoogleAnalytics → ["ga4", "ga"]. Matched alongside name/label/category. */
    keywords?: string[] | null
    label?: string | null
    name: string
    permissionsCaption?: string | null
    releaseStatus?: ReleaseStatusApi | null
    /** Tables to suggest enabling, with optional tooltip explaining why */
    suggestedTables?: SuggestedTableApi[] | null
    /** Whether the source-creation wizard should expose the per-column projection picker. Mirrors `SQLSource.supports_column_selection` so the wizard doesn't show a picker for drivers that ignore `enabled_columns` at sync time. */
    supportsColumnSelection: boolean
    unreleasedSource?: boolean | null
    webhookFields?:
        | (
              | SourceFieldInputConfigApi
              | SourceFieldSwitchGroupConfigApi
              | SourceFieldSelectConfigApi
              | SourceFieldOauthConfigApi
              | SourceFieldOauthAccountSelectConfigApi
              | SourceFieldCredentialAccountSelectConfigApi
              | SourceFieldFileUploadConfigApi
              | SourceFieldSSHTunnelConfigApi
          )[]
        | null
    /** If true, the source does not support automatic webhook registration via API (e.g. Slack, where the user must paste the URL into the source's app settings). Adjusts the setup UI copy to avoid promising automatic registration. */
    webhookManualOnly?: boolean | null
    webhookSetupCaption?: string | null
    /** Vendor API version labels this source supports. */
    versions: string[]
    /** Version used when a source instance pins none. */
    defaultVersion: string
    /** Vendor API docs or changelog URL, or null when the vendor publishes none. */
    apiDocsUrl?: string | null
    deprecatedVersions: SourceVersionDeprecationApi[]
    /** Credential-free documented table catalog, empty for SQL and file sources with user-defined schemas. The public endpoint sets it; the wizard omits it to keep its payload small. */
    tables?: SourceDocumentedTableApi[] | null
}

/**
 * Map of source type identifier to its config, as both catalog endpoints return it.
 */
export interface SourceConfigMapResponseApi {
    [key: string]: SourceConfigResponseApi
}

export interface WarehouseColumnStatisticsApi {
    readonly id: string
    /** ID of the data warehouse table this column belongs to. */
    readonly table: string
    /** Name of the column these statistics describe. */
    readonly column_name: string
    /** ClickHouse type the statistics were computed against (e.g. Int64, DateTime64). */
    readonly column_type: string
    /** Total number of rows in the table when these statistics were computed. */
    readonly row_count: number
    /** Number of NULL values in this column, or null if the Delta log carried no count. */
    readonly null_count: number
    /** Fraction of values that are NULL (null_count / row_count), between 0 and 1. */
    readonly null_fraction: number
    /** Minimum value in the column, as a string. Null when unavailable. For string columns this may be truncated by the underlying Delta statistics, so treat string bounds as approximate. */
    readonly min_value: string
    /** Maximum value in the column, as a string. Null when unavailable (see min_value). */
    readonly max_value: string
    /** Whether the Delta log carried min/max statistics for this column (false for some nested/binary types). */
    readonly has_min_max: boolean
    /** When these statistics were last computed. */
    readonly computed_at: string
    /** Delta table version the statistics were computed against. */
    readonly computed_for_delta_version: number
    /** How the statistics were produced. Currently always 'delta_log'. */
    readonly stats_basis: string
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedWarehouseColumnStatisticsListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: WarehouseColumnStatisticsApi[]
}

export type ExternalDataDestinationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ExternalDataSchemasListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type ExternalDataSchemasCancelCreate200 = {
    detail?: string
}

export type ExternalDataSchemasCancelCreate400 = {
    detail?: string
}

export type ExternalDataSchemasLogsRetrieveParams = {
    /**
     * Only return entries after this ISO 8601 timestamp. Defaults to 7 days ago; pass an explicit value to read further back.
     */
    after?: string
    /**
     * Only return entries before this ISO 8601 timestamp.
     */
    before?: string
    /**
     * Filter logs to a specific execution instance.
     * @minLength 1
     */
    instance_id?: string
    /**
     * Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR.
     * @minLength 1
     */
    level?: string
    /**
     * Maximum number of log entries to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Case-insensitive substring search across log messages.
     * @minLength 1
     */
    search?: string
}

export type ExternalDataSchemasReloadCreate400 = {
    detail?: string
}

export type ExternalDataSchemasResyncCreate400 = {
    detail?: string
}

export type ExternalDataSourcesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type ExternalDataSourcesJobsListParams = {
    /**
     * ISO timestamp — only return jobs created after this date.
     */
    after?: string
    /**
     * ISO timestamp — only return jobs created before this date.
     */
    before?: string
    /**
     * Filter jobs by table schema names.
     */
    schemas?: string[]
    /**
     * A search term.
     */
    search?: string
}

export type ExternalDataSourcesRepairCdcCreate200 = {
    success?: boolean
    schemas_reset?: number
}

export type ExternalDataSourcesResumeCdcCreate200 = {
    success?: boolean
}

export type ExternalDataSourcesConnectLinkRetrieveParams = {
    /**
     * The source type to generate a connect link for (e.g. 'Stripe', 'Postgres', 'Hubspot').
     */
    source_type: string
}

export type ExternalDataSourcesOauthAccountsRetrieveParams = {
    /**
     * The OAuth integration id whose accounts should be listed.
     */
    integration_id: number
    /**
     * Optional case-insensitive filter over account name/value, for sources whose resource list is large (e.g. GitHub repositories).
     */
    search?: string
    /**
     * The data warehouse source type (e.g. 'BingAds', 'GoogleSearchConsole').
     */
    source_type: string
}

export type ExternalDataSourcesStoredCredentialsListParams = {
    /**
     * A search term.
     */
    search?: string
    /**
     * Only return stored credentials for this source type (e.g. 'Stripe', 'Postgres').
     */
    source_type?: string
}

export type ExternalDataSourcesWizardRetrieveParams = {
    /**
     * Comma-separated source type(s) to return config for, e.g. 'Postgres' or 'Postgres,Stripe'. Strongly recommended: the unfiltered response describes every supported source and is very large. Omit only to enumerate the available types.
     */
    source_type?: string
}

export type WarehouseColumnStatisticsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Only return statistics for this data warehouse table.
     */
    table_id?: string
}
