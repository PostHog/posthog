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
}

export interface BroadcastOptionApi {
    /** ID of the broadcast. */
    id: string
    /** Name of the broadcast. */
    name: string
    /** Status of the broadcast, such as draft or active. */
    status: string
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
