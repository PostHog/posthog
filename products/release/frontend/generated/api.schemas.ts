/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface LinkedSurveyDTOApi {
    id: string
    name: string
    created_at: string
    /** @nullable */
    start_date: string | null
    /** @nullable */
    end_date: string | null
    /** @nullable */
    linked_flag_id: number | null
    archived: boolean
}

export interface LinkedInsightDTOApi {
    /** True when the insight was deleted after it was linked. */
    readonly deleted: boolean
    id: number
    short_id: string
    name: string
    /** @nullable */
    created_at: string | null
    /** @nullable */
    last_modified_at: string | null
}

export interface LinkedSendDTOApi {
    id: string
    status: string
    created_at: string
}

export interface LinkedBroadcastDTOApi {
    /** The broadcast's most recent sends, newest first, at most 20. */
    readonly recent_sends: readonly LinkedSendDTOApi[]
    id: string
    name: string
    status: string
}

/**
 * * `at_least` - At least the target
 * * `at_most` - At most the target
 */
export type ReleaseGoalDirectionEnumApi = (typeof ReleaseGoalDirectionEnumApi)[keyof typeof ReleaseGoalDirectionEnumApi]

export const ReleaseGoalDirectionEnumApi = {
    AtLeast: 'at_least',
    AtMost: 'at_most',
} as const

export interface MetricGoalApi {
    /**
     * ID of the metric insight the goal is for.
     * @minimum 1
     * @maximum 2147483647
     */
    insight_id: number
    /** at_least when the metric should reach the value, at_most when it should stay at or below it.
     *
     * * `at_least` - At least the target
     * * `at_most` - At most the target */
    direction: ReleaseGoalDirectionEnumApi
    /** Target value of the metric. */
    value: number
}

export interface ReleaseOwnerDTOApi {
    id: number
    first_name: string
}

export interface ReleaseDTOApi {
    /** ID, name, dates, targeting flag and archived state of each linked survey the caller can see. */
    readonly surveys: readonly LinkedSurveyDTOApi[]
    /** ID, short ID, name and dates of each linked insight the caller can see, including deleted ones. */
    readonly insights: readonly LinkedInsightDTOApi[]
    /** ID, name and status of each linked broadcast the caller can see. Deleted broadcasts are left out. */
    readonly broadcasts: readonly LinkedBroadcastDTOApi[]
    /** IDs of the insights that are the release's metrics. The first is the primary metric. */
    readonly metric_insight_ids: readonly number[]
    /** Target for each metric that has one. Metrics without a goal are left out. */
    readonly metric_goals: readonly MetricGoalApi[]
    /** True when the release links flags the caller cannot see. Their IDs are left out of feature_flag_ids. */
    readonly has_hidden_flags: boolean
    id: string
    name: string
    description: string
    owner: ReleaseOwnerDTOApi | null
    feature_flag_ids: number[]
    broadcast_ids: string[]
    survey_ids: string[]
    insight_ids: number[]
    created_at: string
}

export interface PaginatedReleaseDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReleaseDTOApi[]
}

export interface WriteReleaseApi {
    /**
     * Name of the release.
     * @maxLength 255
     */
    name: string
    /** What changes for the people who get the release. */
    description?: string
    /**
     * ID of the user who owns the release. Must be a member of the project's organization.
     * @nullable
     */
    owner_id?: number | null
    /**
     * IDs of the feature flags that control who gets the release, at most 100.
     * @maxItems 100
     * @items.minimum 1
     * @items.maximum 2147483647
     */
    feature_flag_ids?: number[]
    /**
     * IDs of the broadcasts that announce the release, at most 100.
     * @maxItems 100
     */
    broadcast_ids?: string[]
    /**
     * IDs of the surveys that collect feedback on the release, at most 100.
     * @maxItems 100
     */
    survey_ids?: string[]
    /**
     * IDs of the saved insights that measure the release, at most 100.
     * @maxItems 100
     * @items.minimum 1
     * @items.maximum 2147483647
     */
    insight_ids?: number[]
    /**
     * IDs of the saved trends insights that are the release's metrics, at most 5. The first is the primary metric, the rest are secondary. Replaces the current list.
     * @maxItems 5
     * @items.minimum 1
     * @items.maximum 2147483647
     */
    metric_insight_ids?: number[]
    /**
     * Targets for the release's metrics, at most one per metric. Each insight_id must be one of the metric_insight_ids. Replaces the current goals.
     * @maxItems 5
     */
    metric_goals?: MetricGoalApi[]
}

export interface PatchedUpdateReleaseApi {
    /**
     * Name of the release.
     * @maxLength 255
     */
    name?: string
    /** What changes for the people who get the release. */
    description?: string
    /**
     * ID of the user who owns the release. Must be a member of the project's organization.
     * @nullable
     */
    owner_id?: number | null
    /**
     * IDs of the feature flags that control who gets the release, at most 100.
     * @maxItems 100
     * @items.minimum 1
     * @items.maximum 2147483647
     */
    feature_flag_ids?: number[]
    /**
     * IDs of the broadcasts that announce the release, at most 100.
     * @maxItems 100
     */
    broadcast_ids?: string[]
    /**
     * IDs of the surveys that collect feedback on the release, at most 100.
     * @maxItems 100
     */
    survey_ids?: string[]
    /**
     * IDs of the saved insights that measure the release, at most 100.
     * @maxItems 100
     * @items.minimum 1
     * @items.maximum 2147483647
     */
    insight_ids?: number[]
    /**
     * IDs of the saved trends insights that are the release's metrics, at most 5. The first is the primary metric, the rest are secondary. Replaces the current list.
     * @maxItems 5
     * @items.minimum 1
     * @items.maximum 2147483647
     */
    metric_insight_ids?: number[]
    /**
     * Targets for the release's metrics, at most one per metric. Each insight_id must be one of the metric_insight_ids. Replaces the current goals.
     * @maxItems 5
     */
    metric_goals?: MetricGoalApi[]
}

export interface MergeReleasesApi {
    /**
     * IDs of the releases to merge into this one. Their flags, broadcasts, surveys and insights move to this release, then they are deleted.
     * @minItems 1
     * @maxItems 100
     */
    release_ids: string[]
    /**
     * New name for the merged release. Keeps the current name when left out.
     * @maxLength 255
     */
    name?: string
}

export interface BroadcastOptionApi {
    /** ID of the broadcast. */
    id: string
    /** Name of the broadcast. */
    name: string
    /** Status of the broadcast, such as draft or active. */
    status: string
}

export interface CatalogUserApi {
    /** ID of the user. */
    id: number
    /** UUID of the user. */
    uuid: string
    /** First name of the user. */
    first_name: string
    /** Last name of the user. */
    last_name: string
    /** Email address of the user. */
    email: string
}

export interface CatalogFlagApi {
    /** ID of the feature flag. */
    id: number
    /** Key of the feature flag. */
    key: string
    /** True when the flag is enabled. */
    active: boolean
    /** When the flag was created. */
    created_at: string
    /** Who created the flag, if known. */
    created_by: CatalogUserApi | null
}

export interface CatalogFlagsResponseApi {
    /** Flags the caller can see, in the requested order. */
    results: CatalogFlagApi[]
    /** True when more flags follow this page. */
    has_more: boolean
}

export interface CatalogReleaseApi {
    /** ID of the release. */
    id: string
    /** Name of the release. */
    name: string
    /** When the release was created. */
    created_at: string
    /** Who owns the release, if anyone. */
    owner: CatalogUserApi | null
}

export interface CatalogReleasesResponseApi {
    /** Releases of the project, in the requested order. */
    results: CatalogReleaseApi[]
    /**
     * Pass as cursor to fetch the next page. Null when no more releases follow.
     * @nullable
     */
    next_cursor: string | null
}

export interface ReleaseRefApi {
    /** ID of the release. */
    id: string
    /** Name of the release. */
    name: string
}

export interface ReleaseSuggestionApi {
    /** ID of the release. */
    id: string
    /** Name of the release. */
    name: string
    /** Words the flag shares with the release's name, description or linked flags. */
    matched_terms: string[]
}

export interface FlagReleasesApi {
    /** ID of the feature flag. */
    feature_flag_id: number
    /** True when this project puts each new flag in a release of its own about a minute after it is created, unless the flag is already in a release. */
    auto_release: boolean
    /** Releases that already link this flag. */
    current: ReleaseRefApi[]
    /** Up to 5 existing releases this flag probably belongs to, best match first. Empty when nothing matches. */
    suggestions: ReleaseSuggestionApi[]
}

export interface ImportAllResponseApi {
    /** How many releases the import created. */
    created_count: number
}

export type ReleasesListParams = {
    /**
     * Number of results to return per page.
     * @maximum 1000
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ReleasesBroadcastSearchRetrieveParams = {
    /**
     * Part of the broadcast name to match.
     * @maxLength 200
     */
    search?: string
}

export type ReleasesCatalogFlagsRetrieveParams = {
    /**
     * Comma-separated user IDs. Only flags created by one of them are listed.
     * @maxLength 1000
     */
    created_by?: string
    /**
     * How many flags to return, at most 100.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * How many flags to skip.
     * @minimum 0
     */
    offset?: number
    /**
     * Sort by creation time: -created_at for newest first, created_at for oldest first.
     *
     * * `-created_at` - Newest first
     * * `created_at` - Oldest first
     * @minLength 1
     */
    order?: string
    /**
     * Part of the flag key or name to match.
     * @maxLength 200
     */
    search?: string
}

export type ReleasesCatalogReleasesRetrieveParams = {
    /**
     * next_cursor of the previous page.
     * @maxLength 100
     */
    cursor?: string
    /**
     * Only releases that link this feature flag.
     * @minimum 1
     */
    feature_flag_id?: number
    /**
     * How many releases to return, at most 100.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Sort by creation time: -created_at for newest first, created_at for oldest first.
     *
     * * `-created_at` - Newest first
     * * `created_at` - Oldest first
     * @minLength 1
     */
    order?: string
    /**
     * Comma-separated user IDs. Only releases owned by one of them are listed.
     * @maxLength 1000
     */
    owner?: string
    /**
     * Part of the release name to match.
     * @maxLength 200
     */
    search?: string
}

export type ReleasesFlagSuggestionsRetrieveParams = {
    /**
     * ID of the feature flag to find releases for.
     * @minimum 1
     */
    feature_flag_id: number
}
