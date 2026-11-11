/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface ReleaseOwnerDTOApi {
    id: number
    first_name: string
}

export interface ReleaseDTOApi {
    /** True when the release links flags the caller cannot see. Their IDs are left out of feature_flag_ids. */
    readonly has_hidden_flags: boolean
    id: string
    name: string
    description: string
    owner: ReleaseOwnerDTOApi | null
    feature_flag_ids: number[]
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
     * IDs of the feature flags that control who gets the release.
     * @items.minimum 1
     * @items.maximum 2147483647
     */
    feature_flag_ids?: number[]
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
     * IDs of the feature flags that control who gets the release.
     * @items.minimum 1
     * @items.maximum 2147483647
     */
    feature_flag_ids?: number[]
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
