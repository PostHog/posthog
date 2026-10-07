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

export interface WarehouseSuggestionMaterializePayloadApi {
    /** Sources that are always current, such as PostHog tables and direct connections. */
    live_sources: WarehouseSuggestionVisibleSourcesApi
    /** Sources with no sync schedule, so their freshness is unknown. */
    unknown_sources: WarehouseSuggestionVisibleSourcesApi
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
}

export type WarehouseSuggestionPayloadApi =
    | WarehouseSuggestionCertifyPayloadApi
    | WarehouseSuggestionDeprecatePayloadApi
    | WarehouseSuggestionMaterializePayloadApi

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
 */
export type WarehouseSuggestionKindEnumApi =
    (typeof WarehouseSuggestionKindEnumApi)[keyof typeof WarehouseSuggestionKindEnumApi]

export const WarehouseSuggestionKindEnumApi = {
    Certify: 'certify',
    Deprecate: 'deprecate',
    Materialize: 'materialize',
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
 * The usage numbers that led to this suggestion.
 */
export type WarehouseSuggestionApiEvidence = { [key: string]: unknown }

/**
 * What accepting this suggestion created. Null until accepted.
 * @nullable
 */
export type WarehouseSuggestionApiCreatedAsset = { [key: string]: unknown } | null

export interface WarehouseSuggestionApi {
    /** What accepting this suggestion would create or change. Shape depends on kind. */
    readonly payload: WarehouseSuggestionPayloadApi
    /** The usage numbers that led to this suggestion. */
    evidence: WarehouseSuggestionApiEvidence
    /**
     * What accepting this suggestion created. Null until accepted.
     * @nullable
     */
    created_asset: WarehouseSuggestionApiCreatedAsset
    /** Who accepted or dismissed this suggestion. Null while it is open. */
    reviewed_by: WarehouseSuggestionReviewerApi | null
    /** What the suggestion proposes: certify, deprecate or materialize the subject.
     *
     * * `certify` - Certify
     * * `deprecate` - Deprecate
     * * `materialize` - Materialize */
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
    /** How strongly the evidence supports the suggestion. Higher comes first. */
    score: number
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
    /** Whether the caller has edit access to the subject and so may accept, dismiss or resume. */
    can_act: boolean
}

export interface PaginatedWarehouseSuggestionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: WarehouseSuggestionApi[]
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
}

export type WarehouseSuggestionsListKind =
    (typeof WarehouseSuggestionsListKind)[keyof typeof WarehouseSuggestionsListKind]

export const WarehouseSuggestionsListKind = {
    Certify: 'certify',
    Deprecate: 'deprecate',
    Materialize: 'materialize',
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
