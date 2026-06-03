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
 * * `json` - json
 * `markdown` - markdown
 */
export type ContentStorageEnumApi = (typeof ContentStorageEnumApi)[keyof typeof ContentStorageEnumApi]

export const ContentStorageEnumApi = {
    Json: 'json',
    Markdown: 'markdown',
} as const

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
    /** Canonical storage format for the notebook body. `json` is the legacy ProseMirror format; `markdown` stores markdown natively.

  * `json` - json
  * `markdown` - markdown */
    readonly content_storage: ContentStorageEnumApi
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
    /** Notebook content as a ProseMirror JSON document structure. For markdown notebooks this is a rendered cache of `markdown_content`. */
    content?: unknown
    /** Canonical storage format for the notebook body. `json` is the legacy ProseMirror format; `markdown` stores markdown natively.

  * `json` - json
  * `markdown` - markdown */
    content_storage?: ContentStorageEnumApi
    /**
     * Canonical markdown document for markdown-backed notebooks.
     * @nullable
     */
    markdown_content?: string | null
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
    /** Notebook content as a ProseMirror JSON document structure. For markdown notebooks this is a rendered cache of `markdown_content`. */
    content?: unknown
    /** Canonical storage format for the notebook body. `json` is the legacy ProseMirror format; `markdown` stores markdown natively.

  * `json` - json
  * `markdown` - markdown */
    content_storage?: ContentStorageEnumApi
    /**
     * Canonical markdown document for markdown-backed notebooks.
     * @nullable
     */
    markdown_content?: string | null
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

export interface NotebookCollabSaveApi {
    /** Unique identifier for the client session. */
    client_id: string
    /** The collab version the client's steps are based on. */
    version: number
    /** List of ProseMirror step JSON objects to apply. */
    steps: unknown[]
    /** The resulting ProseMirror document after applying the steps locally. */
    content: unknown
    /** Canonical markdown document after applying the steps locally. Markdown-backed clients send this so collaborative editing can persist markdown without server-side JSON-to-markdown conversion. */
    markdown_content?: string
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

/**
 * * `json_to_markdown` - json_to_markdown
 * `markdown_to_json` - markdown_to_json
 */
export type NotebookDebugConvertDirectionEnumApi =
    (typeof NotebookDebugConvertDirectionEnumApi)[keyof typeof NotebookDebugConvertDirectionEnumApi]

export const NotebookDebugConvertDirectionEnumApi = {
    JsonToMarkdown: 'json_to_markdown',
    MarkdownToJson: 'markdown_to_json',
} as const

export interface NotebookDebugConvertApi {
    /** Conversion direction to run.

  * `json_to_markdown` - json_to_markdown
  * `markdown_to_json` - markdown_to_json */
    direction: NotebookDebugConvertDirectionEnumApi
    /** Optional ProseMirror JSON document to convert instead of the saved notebook content. */
    content?: unknown
    /** Optional markdown document to convert instead of the saved notebook markdown_content. */
    markdown_content?: string
    /** When true, persist the conversion result to the notebook and bump the version. */
    persist?: boolean
}

export interface NotebookDebugConvertResponseApi {
    /** Storage format represented by the conversion result.

  * `json` - json
  * `markdown` - markdown */
    content_storage: ContentStorageEnumApi
    /** Converted ProseMirror JSON document. */
    content: unknown
    /** Converted markdown document. */
    markdown_content: string
    /** Plain text derived from the converted document. */
    text_content: string
}

export interface NotebookMarkdownSaveApi {
    /** The notebook version this markdown update is based on. */
    version: number
    /** Canonical markdown document to save for a markdown-backed notebook. */
    markdown_content: string
    /** Plain text for search indexing. If omitted, the server derives it from markdown_content. */
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
