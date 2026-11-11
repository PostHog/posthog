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
     * Name of the feature.
     * @maxLength 255
     */
    name: string
    /** What the feature does for the people who get it. */
    description?: string
    /**
     * ID of the user who owns the release of this feature.
     * @nullable
     */
    owner_id?: number | null
    /** IDs of the feature flags that gate this feature. */
    feature_flag_ids?: number[]
}

export interface PatchedWriteReleaseApi {
    /**
     * Name of the feature.
     * @maxLength 255
     */
    name?: string
    /** What the feature does for the people who get it. */
    description?: string
    /**
     * ID of the user who owns the release of this feature.
     * @nullable
     */
    owner_id?: number | null
    /** IDs of the feature flags that gate this feature. */
    feature_flag_ids?: number[]
}

export type ReleasesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
