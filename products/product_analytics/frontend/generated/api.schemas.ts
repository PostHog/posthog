/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface PaginatedColumnConfigurationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ColumnConfigurationApi[]
}

export interface ColumnConfigurationApi {
    readonly id: string
    /** @maxLength 255 */
    context_key: string
    columns?: string[]
    readonly created_at: string
    readonly updated_at: string
}

export interface PatchedColumnConfigurationApi {
    readonly id?: string
    /** @maxLength 255 */
    context_key?: string
    columns?: string[]
    readonly created_at?: string
    readonly updated_at?: string
}

export interface PaginatedElementListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ElementApi[]
}

export interface ElementApi {
    /**
     * @maxLength 10000
     * @nullable
     */
    text?: string | null
    /**
     * @maxLength 1000
     * @nullable
     */
    tag_name?: string | null
    /** @nullable */
    attr_class?: string[] | null
    /**
     * @maxLength 10000
     * @nullable
     */
    href?: string | null
    /**
     * @maxLength 10000
     * @nullable
     */
    attr_id?: string | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    nth_child?: number | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    nth_of_type?: number | null
    attributes?: unknown
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    order?: number | null
}

export interface PatchedElementApi {
    /**
     * @maxLength 10000
     * @nullable
     */
    text?: string | null
    /**
     * @maxLength 1000
     * @nullable
     */
    tag_name?: string | null
    /** @nullable */
    attr_class?: string[] | null
    /**
     * @maxLength 10000
     * @nullable
     */
    href?: string | null
    /**
     * @maxLength 10000
     * @nullable
     */
    attr_id?: string | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    nth_child?: number | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    nth_of_type?: number | null
    attributes?: unknown
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    order?: number | null
}

export type EnvironmentsColumnConfigurationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EnvironmentsElementsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ElementsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
