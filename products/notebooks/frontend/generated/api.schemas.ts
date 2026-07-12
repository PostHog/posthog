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

/**
 * * `hogql` - hogql
 * * `local` - local
 */
export type NotebookCellRunRefKindEnumApi =
    (typeof NotebookCellRunRefKindEnumApi)[keyof typeof NotebookCellRunRefKindEnumApi]

export const NotebookCellRunRefKindEnumApi = {
    Hogql: 'hogql',
    Local: 'local',
} as const

export interface NotebookSQLV2RefApi {
    /** ProseMirror node id of the upstream node this name points at. */
    node_id: string
    /** What the name resolves to: 'hogql' is a SQL node's query definition (resolved to its last-run HogQL); 'local' is a dataframe a Python node bound in the kernel namespace.
     *
     * * `hogql` - hogql
     * * `local` - local */
    kind?: NotebookCellRunRefKindEnumApi
}

/**
 * Available upstream nodes, keyed by dataframe name. A SQL node inlines referenced hogql refs as CTEs — unless it references a local ref, which reroutes the run to the sandbox's DuckDB; a python node materializes the hogql refs its code reads as pandas frames.
 */
export type NotebookSQLV2RunRequestApiRefs = { [key: string]: NotebookSQLV2RefApi }

/**
 * * `hogql` - hogql
 * * `python` - python
 */
export type NotebookCellRunNodeTypeEnumApi =
    (typeof NotebookCellRunNodeTypeEnumApi)[keyof typeof NotebookCellRunNodeTypeEnumApi]

export const NotebookCellRunNodeTypeEnumApi = {
    Hogql: 'hogql',
    Python: 'python',
} as const

export interface NotebookSQLV2RunRequestApi {
    /** ProseMirror node id of the SQLV2 node being run. */
    node_id: string
    /** Execution kind. 'hogql' is a SQL node — pushed to ClickHouse, or rerouted to the sandbox's DuckDB when it references a local frame; 'python' runs the code in the sandbox kernel, materializing referenced upstream nodes as pandas frames first.
     *
     * * `hogql` - hogql
     * * `python` - python */
    node_type?: NotebookCellRunNodeTypeEnumApi
    /** The node's source — SQL for a hogql node, Python for a python node. Must not be blank. */
    code: string
    /** Kernel nodes only: the dataframe variable to bind the result to in the kernel namespace (a python node falls back to the last expression for its preview). */
    output_name?: string
    /** Available upstream nodes, keyed by dataframe name. A SQL node inlines referenced hogql refs as CTEs — unless it references a local ref, which reroutes the run to the sandbox's DuckDB; a python node materializes the hogql refs its code reads as pandas frames. */
    refs?: NotebookSQLV2RunRequestApiRefs
}

export interface NotebookSQLV2RunResponseApi {
    /** Identifier of the dispatched run. Poll the run result endpoint with it until the status is terminal. */
    run_id: string
}

export interface NotebookSQLV2MediaApi {
    /** MIME type of the media, e.g. 'image/png' for a matplotlib figure. */
    mime_type: string
    /** Base64-encoded media bytes. */
    data: string
}

export interface NotebookSQLV2EnvelopeApi {
    /** Run outcome: 'ok', 'error', or 'interrupted' (user-requested stop). */
    status: string
    /** Captured stdout from a Python node run. */
    stdout?: string
    /** Captured stderr (including tracebacks) from a Python node run. */
    stderr?: string
    /** Rich outputs from a Python node run, e.g. matplotlib figures as PNGs. */
    media?: NotebookSQLV2MediaApi[]
    /** Result column names. */
    columns?: string[]
    /** ClickHouse type per column, as [name, type] pairs; used by the visualization tab. */
    types?: string[][]
    /** Number of rows in the result. */
    row_count?: number
    /** Whether ClickHouse has more rows beyond first_page (detected by fetching limit+1). */
    has_more?: boolean
    /** First page of result rows for display; each row is a list of cell values. */
    first_page?: unknown[][]
    /**
     * Identifier of the materialized result, used as the paging key.
     * @nullable
     */
    result_id?: string | null
    /**
     * Error message when status is 'error'.
     * @nullable
     */
    error?: string | null
}

export interface NotebookSQLV2RunStatusResponseApi {
    /** Run state: 'running' while executing (keep polling), or terminal 'done', 'failed', or 'interrupted' (user-requested stop). */
    status: string
    /** The result envelope once the run is done or interrupted: columns, a bounded first_page of rows, row_count, and for python cells the captured stdout/stderr and any figures. Null while running or failed. */
    result?: NotebookSQLV2EnvelopeApi | null
    /**
     * Error message when the run failed or was interrupted; null otherwise.
     * @nullable
     */
    error?: string | null
}

export interface NotebookSQLV2InterruptResponseApi {
    /** The run's status after the interrupt request: usually still 'running' (the terminal 'interrupted' state arrives via the run result endpoint), or already-terminal state when nothing was stopped. */
    status: string
    /**
     * Set when nothing was stopped, e.g. the run has not reached the kernel yet; retry shortly.
     * @nullable
     */
    detail?: string | null
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
