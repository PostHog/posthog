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
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

export interface NotebookMinimalApi {
    /** UUID of the notebook. */
    readonly id: string
    /** Short alphanumeric identifier used in URLs and API lookups. */
    readonly short_id: string
    /**
     * Title of the notebook.
     * @nullable
     */
    readonly title: string | null
    /** Whether the notebook has been soft-deleted. */
    readonly deleted: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly last_modified_at: string
    readonly last_modified_by: UserBasicApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    _create_in_folder?: string
}

export interface PaginatedNotebookMinimalListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: NotebookMinimalApi[]
}

export interface NotebookApi {
    /** UUID of the notebook. */
    readonly id: string
    /** Short alphanumeric identifier used in URLs and API lookups. */
    readonly short_id: string
    /**
     * Title of the notebook.
     * @maxLength 256
     * @nullable
     */
    title?: string | null
    /** Notebook content as a ProseMirror JSON document structure. */
    content?: unknown | null
    /**
     * Plain text representation of the notebook content for search.
     * @nullable
     */
    text_content?: string | null
    /**
     * Version number for optimistic concurrency control. Must match the current version when updating content.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    version?: number
    /** Whether the notebook has been soft-deleted. */
    deleted?: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly last_modified_at: string
    readonly last_modified_by: UserBasicApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    _create_in_folder?: string
}

export interface PatchedNotebookApi {
    /** UUID of the notebook. */
    readonly id?: string
    /** Short alphanumeric identifier used in URLs and API lookups. */
    readonly short_id?: string
    /**
     * Title of the notebook.
     * @maxLength 256
     * @nullable
     */
    title?: string | null
    /** Notebook content as a ProseMirror JSON document structure. */
    content?: unknown | null
    /**
     * Plain text representation of the notebook content for search.
     * @nullable
     */
    text_content?: string | null
    /**
     * Version number for optimistic concurrency control. Must match the current version when updating content.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    version?: number
    /** Whether the notebook has been soft-deleted. */
    deleted?: boolean
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly last_modified_at?: string
    readonly last_modified_by?: UserBasicApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
    _create_in_folder?: string
}

export interface NotebookCollabSaveApi {
    /** Unique identifier for the client session. */
    client_id: string
    /** The collab version the client's steps are based on. */
    version: number
    /** List of ProseMirror step JSON objects to apply. */
    steps: unknown[]
    /** The resulting ProseMirror document after applying the steps locally. */
    content: unknown
    /** Plain text for search indexing. */
    text_content?: string
    /** Updated notebook title. */
    title?: string
}

export type NotebooksListParams = {
    /**
 * Filter for notebooks that match a provided filter.
                Each match pair is separated by a colon,
                multiple match pairs can be sent separated by a space or a comma
 */
    contains?: string
    /**
     * The UUID of the Notebook's creator
     */
    created_by?: string
    /**
     * Filter for notebooks created after this date & time
     */
    date_from?: string
    /**
     * Filter for notebooks created before this date & time
     */
    date_to?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * If any value is provided for this parameter, return notebooks created by the logged in user.
     */
    user?: string
}
