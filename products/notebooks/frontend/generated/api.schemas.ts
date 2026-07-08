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
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
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

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
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

/**
 * Parent resource this notebook is attached to, or `null`. Returns `{type: 'account', id: <uuid>}` for account-linked notebooks; used by the frontend to route breadcrumbs back to the resource's list.
 * @nullable
 */
export type NotebookApiParentResource = {
    readonly type: 'account'
    readonly id: string
} | null

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
    content?: unknown
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
    /**
     * Parent resource this notebook is attached to, or `null`. Returns `{type: 'account', id: <uuid>}` for account-linked notebooks; used by the frontend to route breadcrumbs back to the resource's list.
     * @nullable
     */
    readonly parent_resource: NotebookApiParentResource
    _create_in_folder?: string
}

/**
 * Parent resource this notebook is attached to, or `null`. Returns `{type: 'account', id: <uuid>}` for account-linked notebooks; used by the frontend to route breadcrumbs back to the resource's list.
 * @nullable
 */
export type PatchedNotebookApiParentResource = {
    readonly type: 'account'
    readonly id: string
} | null

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
    content?: unknown
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
    /**
     * Parent resource this notebook is attached to, or `null`. Returns `{type: 'account', id: <uuid>}` for account-linked notebooks; used by the frontend to route breadcrumbs back to the resource's list.
     * @nullable
     */
    readonly parent_resource?: PatchedNotebookApiParentResource
    _create_in_folder?: string
}

export interface NotebookCollabCursorApi {
    /**
     * ProseMirror selection head position (rich v1 notebooks).
     * @minimum 0
     */
    head?: number
    /**
     * Index of the caret's block node in the markdown notebook document (markdown notebooks).
     * @minimum 0
     */
    node_index?: number
    /**
     * Caret offset in the plain text of the focused editable element, in UTF-16 code units.
     * @minimum 0
     */
    offset?: number
    /**
     * Index of the focused list item when the caret is inside a list block.
     * @minimum 0
     */
    list_item_index?: number
}

export interface NotebookMarkdownSaveApi {
    /** Unique identifier for the client session, used to skip self-echo on the update stream. */
    client_id: string
    /** The notebook version the submitted content is based on (optimistic concurrency baseline). */
    version: number
    /** The full markdown notebook document: a ProseMirror doc wrapping a single markdown node. */
    content: unknown
    /** Plain text for search indexing. */
    text_content?: string
    /** Updated notebook title. */
    title?: string
    /** The author's caret in the saved markdown, broadcast with the update so other clients can move the author's remote caret together with the text change. */
    cursor?: NotebookCollabCursorApi
}

export interface NotebookCollabPresenceApi {
    /**
     * Unique identifier for the client session, used to skip self-echo on the update stream.
     * @maxLength 200
     */
    client_id: string
    /**
     * The notebook version the cursor position is relative to.
     * @minimum 0
     */
    version: number
    /** The caller's caret position, broadcast to other clients on this notebook's collab stream. */
    cursor: NotebookCollabCursorApi
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
    /**
     * ProseMirror cursor head position after applying steps.
     * @nullable
     */
    cursor_head?: number | null
}

export interface NotebookMarkdownApi {
    /** The notebook content rendered as markdown. Markdown notebooks return their stored markdown source; legacy rich-text notebooks are converted from their ProseMirror document. */
    readonly markdown: string
}

export type NotebooksListParams = {
    /**
     * Filter for notebooks that match a provided filter.
     *                 Each match pair is separated by a colon,
     *                 multiple match pairs can be sent separated by a space or a comma
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
