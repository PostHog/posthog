/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface WarehouseSuggestionCertifyPayloadApi {
    /** Name of the view or table to certify. */
    subject_name: string
}

export interface WarehouseSuggestionDeprecatePayloadApi {
    /** Name of the unread view to deprecate. */
    subject_name: string
    /** Time its refreshes take in a month, in seconds. */
    refresh_seconds_per_month: number
    /** Bytes its refreshes read in a month. */
    refresh_bytes_per_month: number
}

export interface WarehouseSuggestionVisibleSourcesApi {
    /** Names of the sources the caller may see. */
    names: string[]
    /** How many more sources exist that the caller may not see. */
    hidden_count: number
}

/**
 * * `full` - Full
 * * `incremental` - Incremental
 */
export type WarehouseSuggestionRefreshModeEnumApi =
    (typeof WarehouseSuggestionRefreshModeEnumApi)[keyof typeof WarehouseSuggestionRefreshModeEnumApi]

export const WarehouseSuggestionRefreshModeEnumApi = {
    Full: 'full',
    Incremental: 'incremental',
} as const

/**
 * * `source_sync` - Source sync
 * * `fastest_schedule` - Fastest schedule
 * * `read_rate` - Read rate
 * * `savings` - Savings
 */
export type WarehouseSuggestionRefreshIntervalBasisEnumApi =
    (typeof WarehouseSuggestionRefreshIntervalBasisEnumApi)[keyof typeof WarehouseSuggestionRefreshIntervalBasisEnumApi]

export const WarehouseSuggestionRefreshIntervalBasisEnumApi = {
    SourceSync: 'source_sync',
    FastestSchedule: 'fastest_schedule',
    ReadRate: 'read_rate',
    Savings: 'savings',
} as const

export interface WarehouseSuggestionMaterializePayloadApi {
    /** Sources that are always current, such as PostHog tables and direct connections. */
    live_sources: WarehouseSuggestionVisibleSourcesApi
    /** Sources with no sync schedule, so their freshness is unknown. */
    unknown_sources: WarehouseSuggestionVisibleSourcesApi
    /** incremental: each refresh reads only rows with a new incremental_key value and updates rows by unique_key. full: each refresh rebuilds the whole table. Incremental is proposed only when the keys are certain from the query.
     *
     * * `full` - Full
     * * `incremental` - Incremental */
    refresh_mode: WarehouseSuggestionRefreshModeEnumApi
    /** Why the interval is not shorter. source_sync: the view's sources sync no faster. fastest_schedule: PostHog refreshes views no more often. read_rate: people read the view no more often. savings: a shorter interval would cost more than it saves. Null on suggestions made before this was recorded.
     *
     * * `source_sync` - Source sync
     * * `fastest_schedule` - Fastest schedule
     * * `read_rate` - Read rate
     * * `savings` - Savings */
    refresh_interval_basis: WarehouseSuggestionRefreshIntervalBasisEnumApi | null
    /** Name of the view to materialize. */
    subject_name: string
    /** Proposed refresh interval, in seconds. */
    refresh_interval_seconds: number
    /** Query time materializing saves in a month, in seconds. */
    saves_seconds_per_month: number
    /** Bytes materializing saves from scanning in a month. */
    saves_bytes_per_month: number
    /**
     * How old the view's data can be today, in seconds. Null when its sources are live.
     * @nullable
     */
    freshness_today_seconds: number | null
    /** How old the data can be once materialized, in seconds. */
    freshness_after_seconds: number
    /**
     * Output column whose advancing value marks new rows. A proposal only uses a date or datetime column the query groups by. Null for a full refresh.
     * @nullable
     */
    incremental_key?: string | null
    /** Output columns that identify a row, so a refresh updates rows instead of adding duplicates. Empty for a full refresh. */
    unique_key?: string[]
    /** How far before the last refresh's highest incremental_key value each refresh reads again, in seconds. The last incremental_key value is always read again. */
    lookback_seconds?: number
}

export interface WarehouseSuggestionUnmaterializePayloadApi {
    /** Name of the rarely read materialized view to turn back into a plain view. */
    subject_name: string
    /** Time its refreshes take in a month, in seconds. */
    refresh_seconds_per_month: number
    /** Bytes its refreshes read in a month. */
    refresh_bytes_per_month: number
    /** Estimated time its reads would take in a month if each read computed the view, in seconds. The estimate uses a full refresh per read, so it leans high. */
    live_seconds_per_month: number
    /** Estimated bytes its reads would scan in a month if each read computed the view. */
    live_bytes_per_month: number
    /** How long one read would take once the view is computed on read, in seconds. Nine in ten of its refreshes finished within this time. */
    read_seconds: number
}

export type WarehouseSuggestionPayloadApi =
    | WarehouseSuggestionCertifyPayloadApi
    | WarehouseSuggestionDeprecatePayloadApi
    | WarehouseSuggestionMaterializePayloadApi
    | WarehouseSuggestionUnmaterializePayloadApi

/**
 * Queries people ran per place they ran them, such as sql_editor, dashboard, insight or mcp.
 */
export type WarehouseSuggestionEvidenceApiRequestsBySurface = { [key: string]: number }

export interface WarehouseSuggestionEvidenceApi {
    /** Days of the 30-day usage window that PostHog has read history for. It counts days with reads in any project, so it shows how much history exists, not how active this project is. */
    days_with_data?: number
    /** Queries people ran that read the subject in the usage window. */
    human_requests?: number
    /** Distinct people who ran those queries. */
    human_users?: number
    /** Days on which people read the subject. */
    human_days?: number
    /** Queries PostHog ran on its own that read the subject, such as cache warming and alerts. */
    background_requests?: number
    /** Queries people ran per place they ran them, such as sql_editor, dashboard, insight or mcp. */
    requests_by_surface?: WarehouseSuggestionEvidenceApiRequestsBySurface
    /** When any query last read the subject, including queries PostHog ran on its own. */
    last_read_at?: string
}

export interface WarehouseSuggestionReviewerApi {
    /** User id. */
    id: number
    /** User first name. */
    first_name: string
    /** User email. */
    email: string
}

/**
 * * `certify` - Certify
 * * `deprecate` - Deprecate
 * * `materialize` - Materialize
 * * `unmaterialize` - Unmaterialize
 */
export type WarehouseSuggestionKindEnumApi =
    (typeof WarehouseSuggestionKindEnumApi)[keyof typeof WarehouseSuggestionKindEnumApi]

export const WarehouseSuggestionKindEnumApi = {
    Certify: 'certify',
    Deprecate: 'deprecate',
    Materialize: 'materialize',
    Unmaterialize: 'unmaterialize',
} as const

/**
 * * `saved_query` - Saved query
 * * `table` - Table
 */
export type WarehouseSuggestionSubjectKindEnumApi =
    (typeof WarehouseSuggestionSubjectKindEnumApi)[keyof typeof WarehouseSuggestionSubjectKindEnumApi]

export const WarehouseSuggestionSubjectKindEnumApi = {
    SavedQuery: 'saved_query',
    Table: 'table',
} as const

/**
 * * `proposed` - Proposed
 * * `accepted` - Accepted
 * * `dismissed` - Dismissed
 * * `expired` - Expired
 * * `auto_resolved` - Auto-resolved
 */
export type WarehouseSuggestionStatusEnumApi =
    (typeof WarehouseSuggestionStatusEnumApi)[keyof typeof WarehouseSuggestionStatusEnumApi]

export const WarehouseSuggestionStatusEnumApi = {
    Proposed: 'proposed',
    Accepted: 'accepted',
    Dismissed: 'dismissed',
    Expired: 'expired',
    AutoResolved: 'auto_resolved',
} as const

/**
 * * `not_useful` - Not useful
 * * `not_now` - Not now
 * * `other` - Other
 */
export type WarehouseSuggestionDismissalReasonEnumApi =
    (typeof WarehouseSuggestionDismissalReasonEnumApi)[keyof typeof WarehouseSuggestionDismissalReasonEnumApi]

export const WarehouseSuggestionDismissalReasonEnumApi = {
    NotUseful: 'not_useful',
    NotNow: 'not_now',
    Other: 'other',
} as const

/**
 * * `live` - Live
 * * `deleted` - Deleted
 * * `unused` - Unused
 */
export type WarehouseSuggestionAssetOutcomeEnumApi =
    (typeof WarehouseSuggestionAssetOutcomeEnumApi)[keyof typeof WarehouseSuggestionAssetOutcomeEnumApi]

export const WarehouseSuggestionAssetOutcomeEnumApi = {
    Live: 'live',
    Deleted: 'deleted',
    Unused: 'unused',
} as const

/**
 * What accepting this suggestion created. Null until accepted.
 * @nullable
 */
export type WarehouseSuggestionApiCreatedAsset = { [key: string]: unknown } | null

export interface WarehouseSuggestionApi {
    /** What accepting this suggestion would create or change. Shape depends on kind. */
    readonly payload: WarehouseSuggestionPayloadApi
    /** The read counts that led to this suggestion. A field is missing when the subject had no reads. */
    evidence: WarehouseSuggestionEvidenceApi
    /**
     * What accepting this suggestion created. Null until accepted.
     * @nullable
     */
    created_asset: WarehouseSuggestionApiCreatedAsset
    /** Who accepted or dismissed this suggestion. Null while it is open. */
    reviewed_by: WarehouseSuggestionReviewerApi | null
    /** What the suggestion proposes: certify, deprecate, materialize or unmaterialize the subject. unmaterialize turns a rarely read materialized view back into a plain view computed on read.
     *
     * * `certify` - Certify
     * * `deprecate` - Deprecate
     * * `materialize` - Materialize
     * * `unmaterialize` - Unmaterialize */
    kind: WarehouseSuggestionKindEnumApi
    /** Whether the subject is a saved query (view) or a warehouse table.
     *
     * * `saved_query` - Saved query
     * * `table` - Table */
    subject_kind: WarehouseSuggestionSubjectKindEnumApi
    /** proposed until someone accepts or dismisses it, or the job expires it.
     *
     * * `proposed` - Proposed
     * * `accepted` - Accepted
     * * `dismissed` - Dismissed
     * * `expired` - Expired
     * * `auto_resolved` - Auto-resolved */
    status: WarehouseSuggestionStatusEnumApi
    /** Why the suggestion was dismissed.
     *
     * * `not_useful` - Not useful
     * * `not_now` - Not now
     * * `other` - Other */
    dismissal_reason: WarehouseSuggestionDismissalReasonEnumApi | null
    /** What happened to the asset an accepted suggestion created.
     *
     * * `live` - Live
     * * `deleted` - Deleted
     * * `unused` - Unused */
    asset_outcome: WarehouseSuggestionAssetOutcomeEnumApi | null
    /** Suggestion identifier. */
    id: string
    /** Id of the view or table the suggestion is about. */
    subject_id: string
    /** Version of the payload shape for this kind. */
    payload_version: number
    /** Start of the usage window the evidence covers. */
    evidence_window_start: string
    /** End of the usage window the evidence covers. */
    evidence_window_end: string
    /** When the daily job last found evidence for this suggestion. */
    last_seen_at: string
    /**
     * When the suggestion was first shown. Null while it waits for a slot.
     * @nullable
     */
    surfaced_at: string | null
    /**
     * When the suggestion was accepted or dismissed.
     * @nullable
     */
    reviewed_at: string | null
    /**
     * Free-text note left when dismissing.
     * @nullable
     */
    dismissal_note: string | null
    /**
     * Query time an accepted materialize or unmaterialize suggestion saved over the last 30 days, scaled to a month: what the view would cost without the change minus what it costs now. For materialize, people's reads cost what they cost per read before acceptance, at today's read volume, and the cost now is those reads plus refreshes. For unmaterialize, the cost without the change is its refreshes, and the cost now is every read. Negative when the change costs more than it saves. Null until 30 days have passed since acceptance, when a materialized view has no refresh in that time, and for other kinds.
     * @nullable
     */
    realized_seconds_saved_per_month: number | null
    /**
     * Bytes read that an accepted materialize or unmaterialize suggestion saved over the last 30 days, scaled to a month, measured the same way as realized_seconds_saved_per_month.
     * @nullable
     */
    realized_bytes_saved_per_month: number | null
    /** Whether the caller has edit access to the subject and so may accept, dismiss or resume. */
    can_act: boolean
    /**
     * Warehouse source that syncs the subject table, for linking to its schema page. Null for views and for tables no source syncs.
     * @nullable
     */
    subject_source_id?: string | null
    /**
     * Source schema that syncs the subject table, for linking to its schema page. Null for views and for tables no source syncs.
     * @nullable
     */
    subject_schema_id?: string | null
}

export interface PaginatedWarehouseSuggestionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: WarehouseSuggestionApi[]
}

export interface AcceptWarehouseSuggestionApi {
    /**
     * Materialize only: refresh interval to use instead of the proposed one, in seconds. Omit to keep the proposed interval.
     * @minimum 1
     * @maximum 2592000
     */
    refresh_interval_seconds?: number
    /** Materialize only: incremental or full, instead of the proposed refresh_mode. Omit to keep the proposed one. Switching to incremental needs incremental_key and unique_key when the payload has none.
     *
     * * `full` - Full
     * * `incremental` - Incremental */
    refresh_mode?: WarehouseSuggestionRefreshModeEnumApi
    /** Materialize only, incremental refresh only: an output column whose value only grows as rows arrive, such as a date, a datetime or an increasing number, instead of the proposed one. view-check-incremental lists the columns that qualify. Omit to keep the proposed key. */
    incremental_key?: string
    /** Materialize only, incremental refresh only: output columns that identify a row, instead of the proposed ones. Must include every GROUP BY column. Omit to keep the proposed key. */
    unique_key?: string[]
    /**
     * Materialize only, incremental refresh only: how far before the last refresh's highest incremental_key value each refresh reads again, in seconds, so late rows are picked up. Omit to keep the proposed lookback.
     * @minimum 0
     * @maximum 2592000
     */
    lookback_seconds?: number
    /** Deprecate only: true to keep a materialized view refreshing after it is deprecated. By default, accepting a deprecate suggestion also stops the view's refreshes and deletes its stored table, unless other views or syncs depend on it. */
    keep_materialized?: boolean
}

export interface DismissWarehouseSuggestionApi {
    /** Why the suggestion is dismissed.
     *
     * * `not_useful` - Not useful
     * * `not_now` - Not now
     * * `other` - Other */
    reason: WarehouseSuggestionDismissalReasonEnumApi
    /**
     * Optional note about the dismissal.
     * @maxLength 1000
     */
    note?: string
}

export interface WarehouseSuggestionStatusApi {
    /** False when the project turned suggestions off. */
    enabled: boolean
    /** Whether the project reads its views often enough to get suggestions. */
    eligible: boolean
    /** Days of read history the last run had, up to the window. */
    days_with_data: number
    /** Days of read history a full window holds. */
    window_days: number
    /**
     * Why new suggestions stopped showing. Null while they show.
     * @nullable
     */
    paused_reason: string | null
    /**
     * When the daily job last ran for this project.
     * @nullable
     */
    refreshed_at: string | null
}

export type WarehouseSuggestionsListParams = {
    /**
     * Only return suggestions of this kind.
     *
     * * `certify` - Certify
     * * `deprecate` - Deprecate
     * * `materialize` - Materialize
     * * `unmaterialize` - Unmaterialize
     * @minLength 1
     */
    kind?: WarehouseSuggestionsListKind
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Only return suggestions in this status.
     *
     * * `proposed` - Proposed
     * * `accepted` - Accepted
     * * `dismissed` - Dismissed
     * * `expired` - Expired
     * * `auto_resolved` - Auto-resolved
     * @minLength 1
     */
    status?: WarehouseSuggestionsListStatus
    /**
     * Only return suggestions about the view or table with this ID.
     */
    subject_id?: string
}

export type WarehouseSuggestionsListKind =
    (typeof WarehouseSuggestionsListKind)[keyof typeof WarehouseSuggestionsListKind]

export const WarehouseSuggestionsListKind = {
    Certify: 'certify',
    Deprecate: 'deprecate',
    Materialize: 'materialize',
    Unmaterialize: 'unmaterialize',
} as const

export type WarehouseSuggestionsListStatus =
    (typeof WarehouseSuggestionsListStatus)[keyof typeof WarehouseSuggestionsListStatus]

export const WarehouseSuggestionsListStatus = {
    Proposed: 'proposed',
    Accepted: 'accepted',
    Dismissed: 'dismissed',
    Expired: 'expired',
    AutoResolved: 'auto_resolved',
} as const
