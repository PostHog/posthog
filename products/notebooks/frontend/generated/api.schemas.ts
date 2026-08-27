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
 * * `student` - Student
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
    Student: 'student',
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

/**
 * One notebook-level variable. Shared by the notebook's own `variables` field and a run body.
 */
export interface NotebookVariableApi {
    /**
     * Identifier the cell reads: `{name}` in a SQL cell, a plain global in a Python cell.
     * @maxLength 200
     */
    name: string
    /** How to coerce the value: 'string', 'number', 'boolean', or 'date'. Unknown types read as 'string'. */
    type: string
    /** The variable's current value. A 'date' accepts an absolute date or a relative expression ('-7d', 'mStart'), resolved against the project timezone. */
    value?: unknown
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
    /** Notebook-level variables, in display order. A SQL cell reads one as a `{name}` placeholder and a Python cell as a global. Names must be unique. */
    variables?: NotebookVariableApi[]
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
    /** Notebook-level variables, in display order. A SQL cell reads one as a `{name}` placeholder and a Python cell as a global. Names must be unique. */
    variables?: NotebookVariableApi[]
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

export interface NotebookKernelConfigApi {
    /** CPU cores for the notebook's sandbox kernel; must be a supported option. */
    cpu_cores?: number
    /** Memory in GB for the notebook's sandbox kernel; must be a supported option. */
    memory_gb?: number
    /** Seconds of inactivity before the sandbox kernel shuts down. */
    idle_timeout_seconds?: number
}

export interface NotebookKernelConfigResponseApi {
    /**
     * Configured CPU cores; null means the default applies.
     * @nullable
     */
    cpu_cores?: number | null
    /**
     * Configured memory in GB; null means the default applies.
     * @nullable
     */
    memory_gb?: number | null
    /**
     * Configured idle timeout in seconds; null means the default.
     * @nullable
     */
    idle_timeout_seconds?: number | null
    /** True when a kernel is currently active: config applies at sandbox provision time, so the running kernel keeps its old resources until restarted (restarting loses materialized dataframes). */
    restart_required: boolean
}

export interface NotebookSQLV2FrameApi {
    /** Name a SQL node can SELECT from. */
    name: string
    /** Where the object came from: 'frame' (a dataframe a node produced), or 'table'/'view' (created by SQL DDL in a DuckDB node). */
    kind: string
    /** DuckDB type per column, as [name, type] pairs. */
    columns?: string[][]
    /**
     * Rows available, or null when counting would require a table scan (a DDL view).
     * @nullable
     */
    row_count?: number | null
    /** True when row_count is DuckDB's optimizer estimate rather than a count. The estimate does not track deletes, so it must never be presented as exact. */
    row_count_is_estimate?: boolean
}

export interface NotebookKernelStatusResponseApi {
    /**
     * Sandbox backend the kernel runs on: 'modal' or 'docker'.
     * @nullable
     */
    backend?: string | null
    /** Live-checked kernel state: 'starting', 'running', 'stopped', 'timed_out', 'discarded', or 'error'. */
    status: string
    /**
     * When the kernel last executed anything.
     * @nullable
     */
    last_used_at?: string | null
    /**
     * Most recent provisioning or runtime error, if any.
     * @nullable
     */
    last_error?: string | null
    /**
     * Kernel runtime row identifier.
     * @nullable
     */
    runtime_id?: string | null
    /**
     * Jupyter kernel identifier.
     * @nullable
     */
    kernel_id?: string | null
    /**
     * Kernel process id inside the sandbox.
     * @nullable
     */
    kernel_pid?: number | null
    /**
     * Sandbox container identifier.
     * @nullable
     */
    sandbox_id?: string | null
    /** Dataframes and DuckDB tables a cell can currently reference, with column names and types. Empty unless the kernel is running and the caller has query access. */
    frames: NotebookSQLV2FrameApi[]
    /** CPU cores the sandbox is configured with. */
    cpu_cores: number
    /** Memory in GB the sandbox is configured with. */
    memory_gb: number
    /**
     * Disk size in GB the sandbox is configured with.
     * @nullable
     */
    disk_size_gb?: number | null
    /**
     * Seconds of inactivity before the sandbox shuts down.
     * @nullable
     */
    idle_timeout_seconds?: number | null
}

/**
 * * `hogql` - hogql
 * * `local` - local
 */
export type NotebookSQLV2RefKindEnumApi = (typeof NotebookSQLV2RefKindEnumApi)[keyof typeof NotebookSQLV2RefKindEnumApi]

export const NotebookSQLV2RefKindEnumApi = {
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
    kind?: NotebookSQLV2RefKindEnumApi
}

/**
 * Available upstream nodes, keyed by dataframe name. A SQL node inlines referenced hogql refs as CTEs — unless it references a local ref, which reroutes the run to the sandbox's DuckDB; a python node materializes the hogql refs its code reads as pandas frames.
 */
export type NotebookSQLV2RunRequestApiRefs = { [key: string]: NotebookSQLV2RefApi }

/**
 * * `hogql` - hogql
 * * `python` - python
 */
export type NotebookSQLV2NodeTypeEnumApi =
    (typeof NotebookSQLV2NodeTypeEnumApi)[keyof typeof NotebookSQLV2NodeTypeEnumApi]

export const NotebookSQLV2NodeTypeEnumApi = {
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
    node_type?: NotebookSQLV2NodeTypeEnumApi
    /** The node's source — SQL for a hogql node, Python for a python node. Must not be blank. */
    code: string
    /** Kernel nodes only: the dataframe variable to bind the result to in the kernel namespace (a python node falls back to the last expression for its preview). */
    output_name?: string
    /** Available upstream nodes, keyed by dataframe name. A SQL node inlines referenced hogql refs as CTEs — unless it references a local ref, which reroutes the run to the sandbox's DuckDB; a python node materializes the hogql refs its code reads as pandas frames. */
    refs?: NotebookSQLV2RunRequestApiRefs
    /** Notebook-level variables in scope for this run. A SQL node has each `{name}` bound to its value before dispatch; a Python node gets them as globals in the kernel namespace. A SQL node reading a `{name}` that is absent here fails the dispatch. */
    variables?: NotebookVariableApi[]
    /**
     * SQL nodes only: id of a direct-query-capable external data source to run against instead of PostHog's ClickHouse. Omit to query PostHog.
     * @nullable
     */
    connection_id?: string | null
    /** Send the code to the selected connection verbatim instead of compiling it from HogQL first. Ignored without connection_id, and incompatible with references to other cells. */
    send_raw_query?: boolean
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

/**
 * Phase durations in seconds. From the sandbox: input_wait_s (waiting on the data plane), download_s (presigned frame downloads), kernel_boot_s (ensuring the ipykernel is up), exec_s (kernel cell execution), sandbox_total_s (the whole sandbox-side run). From the direct lane: queued_s (enqueue to Celery pickup), clickhouse_s (pickup to completion). Feeds the node-run metrics.
 */
export type NotebookSQLV2EnvelopeApiTimings = { [key: string]: number }

export interface NotebookSQLV2EnvelopeApi {
    /** Run outcome: 'ok', 'error', or 'interrupted' (user-requested stop). */
    status: string
    /** DuckDB objects a SQL node can SELECT from as of this run, for the schema browser. Only kernel runs (python/duckdb) report these; a hogql run never enters the kernel. */
    frames?: NotebookSQLV2FrameApi[]
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
    /** Phase durations in seconds. From the sandbox: input_wait_s (waiting on the data plane), download_s (presigned frame downloads), kernel_boot_s (ensuring the ipykernel is up), exec_s (kernel cell execution), sandbox_total_s (the whole sandbox-side run). From the direct lane: queued_s (enqueue to Celery pickup), clickhouse_s (pickup to completion). Feeds the node-run metrics. */
    timings?: NotebookSQLV2EnvelopeApiTimings
}

export interface NotebookSQLV2RunStatusResponseApi {
    /** Run state: 'running' (keep polling), or terminal — 'done', 'failed', or 'interrupted'. */
    status: string
    /** The result envelope once the run is 'done' or 'interrupted' (an interrupted run keeps the stdout/stderr captured before the stop); null while running and for failed runs. */
    result?: NotebookSQLV2EnvelopeApi | null
    /**
     * Why the run failed when it never produced an envelope (dispatch or watchdog failure); execution errors arrive inside the envelope's error field instead.
     * @nullable
     */
    error?: string | null
    /** SQL (hogql) runs only: the full capped row set for client-side paging, present while the query manager's transient result is alive (~20 minutes). Absent afterwards and for kernel (python/duckdb) runs, which keep only the envelope's first_page preview. */
    rows?: unknown[][]
}

export interface NotebookSQLV2InterruptResponseApi {
    /** The run's status after the interrupt request. Already-terminal runs return their outcome unchanged (idempotent noop); a stopped kernel run reports its terminal state through the normal result poll. */
    status: string
    /** Present when the interrupt could not take effect yet, e.g. the run has not reached the kernel. */
    detail?: string
}

export interface NotebookKernelStateApi {
    /** Kernel runtime state: 'starting', 'running', 'stopped', 'timed_out', 'discarded', or 'error'. */
    status: string
    /**
     * CPU cores the notebook's sandbox is configured with.
     * @nullable
     */
    cpu_cores?: number | null
    /**
     * Memory in GB the notebook's sandbox is configured with.
     * @nullable
     */
    memory_gb?: number | null
    /**
     * Seconds of inactivity before the sandbox shuts down.
     * @nullable
     */
    idle_timeout_seconds?: number | null
}

export interface NotebookCellLastRunApi {
    /** Identifier of the cell's most recent run. */
    run_id: string
    /** The run's own state: 'running', 'done', 'failed', or 'interrupted'. */
    status: string
    /** When the run last changed state. */
    finished_at: string
    /**
     * Rows in the result, when the run produced one.
     * @nullable
     */
    row_count?: number | null
    /**
     * Result column names.
     * @nullable
     */
    columns?: string[] | null
    /**
     * Error message when the run failed.
     * @nullable
     */
    error?: string | null
}

export interface NotebookCellStateApi {
    /** Durable cell identity, used by the cell run and edit endpoints. */
    node_id: string
    /** Cell kind: 'sql', 'python', or 'saved_insight' (embedded insight, never runs). */
    cell_type: string
    /** Name other cells reference this cell's result by; blank means display-only. */
    dataframe_name: string
    /** The cell's source, truncated with a marker past 8KB. */
    code: string
    /** Derived cell state: 'never_run', 'running', 'done', 'failed', 'interrupted', or 'stale' — stale means re-running now would execute different code than the last completed run (the cell or an upstream dependency changed). */
    status: string
    /** node_ids of cells whose dataframes this cell's code references. */
    depends_on: string[]
    /** node_ids of cells that reference this cell's dataframe. */
    dependents: string[]
    /** Summary of the most recent run; null when never run. */
    last_run?: NotebookCellLastRunApi | null
}

export interface NotebookSQLV2StateResponseApi {
    /** The notebook's short id. */
    notebook_id: string
    /**
     * The notebook's title.
     * @nullable
     */
    title: string | null
    /**
     * Document version, the optimistic-concurrency baseline for edits.
     * @nullable
     */
    version: number | null
    /**
     * The full markdown source — prose and cell tags. Null for legacy rich-text notebooks, which carry their document in `content` instead.
     * @nullable
     */
    markdown: string | null
    /** Legacy rich-text notebooks only: the raw ProseMirror document. Omitted for markdown notebooks — their document is the `markdown` field. */
    content?: unknown
    /** The notebook's kernel runtime state and compute config. */
    kernel: NotebookKernelStateApi
    /** Every cell in document order, with its dependency edges and derived run state. */
    cells: NotebookCellStateApi[]
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
