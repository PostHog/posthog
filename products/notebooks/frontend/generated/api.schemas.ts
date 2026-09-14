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
    /** The variable's current value. A 'date' is an absolute date or datetime in ISO 8601 form ('2025-01-31', '2025-01-31T09:00:00Z'); relative expressions such as '-7d' are rejected. */
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
    /** True when this call restarted a live kernel to apply a new size. Restarting discards every materialized dataframe, so cells that referenced one must run again. */
    restarted: boolean
    /** True when a kernel is live and this call did not restart it, so the running sandbox may not match the saved config. A resize restarts the kernel and reports False on success, or True if that restart fails. An idle-timeout change and a no-op on a live kernel also report True. */
    restart_required: boolean
    /** What this sandbox shape costs per hour in USD while it is alive, at this region's rates. It tracks the running sandbox while a kernel is live, otherwise the configured shape. After a failed resize this stays the running sandbox's rate, not the size that failed to apply. */
    hourly_price: number
    /**
     * Compute preset the configured shape matches, or null when it was tuned by hand.
     * @nullable
     */
    preset_key?: string | null
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
    /** What this sandbox shape costs per hour in USD while it is alive, at this region's rates. Charged on the sandbox's lifetime, not on how much of it a cell uses. Resizing through the kernel config endpoint restarts a live kernel, so this tracks the running sandbox. */
    hourly_price: number
    /**
     * Compute preset for the shape hourly_price describes: the running sandbox while a kernel is live, otherwise the configured shape. Null when that shape was tuned by hand and matches no preset.
     * @nullable
     */
    preset_key?: string | null
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
    /** True when this run has to provision a sandbox because none is live for the caller, checked here rather than inferred from a client's cached kernel status. Tell the user what that costs. */
    starts_sandbox: boolean
    /**
     * What the sandbox this run provisions costs per hour in USD. Null when the run needs no new sandbox, or when the backend is not charged.
     * @nullable
     */
    sandbox_hourly_price?: number | null
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
    /** The notebook's declared variables, in display order. A SQL cell reads one as a `{name}` placeholder and a Python cell as a global; a cell that reads an undeclared name fails to run. */
    variables: NotebookVariableApi[]
    /** Every cell in document order, with its dependency edges and derived run state. */
    cells: NotebookCellStateApi[]
}

export interface WidgetCancelRequestApi {
    /** Generation job to cancel. */
    generation_id: string
}

export interface WidgetErrorApi {
    /** Stable machine-readable error code. */
    code: string
    /** Actionable error detail. */
    detail: string
}

export interface WidgetFrameColumnApi {
    /** Column name. */
    name: string
    /** Column type reported by the completed notebook run. */
    type: string
}

export interface WidgetFrameApi {
    /** Logical dataframe name. */
    name: string
    /** Completed notebook run used for every page in this iframe load. */
    runId: string
    /** Dataframe columns in display order. */
    columns: WidgetFrameColumnApi[]
    /** Requested page of dataframe rows. */
    rows: unknown[][]
    /**
     * Rows available in the completed run.
     * @minimum 0
     */
    totalRowCount: number
    /**
     * Rows returned in this response.
     * @minimum 0
     */
    includedRowCount: number
    /**
     * Zero-based offset of this page.
     * @minimum 0
     */
    offset: number
    /**
     * Offset for the next page, if any.
     * @minimum 0
     * @nullable
     */
    nextOffset: number | null
    /** Whether more rows exist after this page. */
    truncated: boolean
}

/**
 * * `claude-haiku-4-5` - claude-haiku-4-5
 * * `claude-sonnet-4-6` - claude-sonnet-4-6
 * * `claude-sonnet-5` - claude-sonnet-5
 * * `claude-opus-5` - claude-opus-5
 */
export type WidgetGenerateRequestModelEnumApi =
    (typeof WidgetGenerateRequestModelEnumApi)[keyof typeof WidgetGenerateRequestModelEnumApi]

export const WidgetGenerateRequestModelEnumApi = {
    ClaudeHaiku45: 'claude-haiku-4-5',
    ClaudeSonnet46: 'claude-sonnet-4-6',
    ClaudeSonnet5: 'claude-sonnet-5',
    ClaudeOpus5: 'claude-opus-5',
} as const

/**
 * * `initial` - initial
 * * `regenerate` - regenerate
 * * `improve` - improve
 */
export type GenerationOperationEnumApi = (typeof GenerationOperationEnumApi)[keyof typeof GenerationOperationEnumApi]

export const GenerationOperationEnumApi = {
    Initial: 'initial',
    Regenerate: 'regenerate',
    Improve: 'improve',
} as const

export interface WidgetGenerateRequestApi {
    /**
     * Instructions for the generated widget. Initial and improvement instructions accept up to 20,000 characters; regeneration accepts complete instructions up to 50,000 characters.
     * @maxLength 50000
     */
    prompt: string
    /** Idempotency key for this generation job. */
    generation_id: string
    /** AI model used to generate the widget.
     *
     * * `claude-haiku-4-5` - claude-haiku-4-5
     * * `claude-sonnet-4-6` - claude-sonnet-4-6
     * * `claude-sonnet-5` - claude-sonnet-5
     * * `claude-opus-5` - claude-opus-5 */
    model?: WidgetGenerateRequestModelEnumApi
    /** Whether to generate from scratch or improve the current source.
     *
     * * `initial` - initial
     * * `regenerate` - regenerate
     * * `improve` - improve */
    generation_operation?: GenerationOperationEnumApi
    /** Current widget version the improvement is based on. Required for improve operations. */
    expected_current_version_id?: string
}

/**
 * * `awaiting_generation` - awaiting_generation
 * * `generating` - generating
 * * `building` - building
 * * `ready` - ready
 * * `failed` - failed
 * * `incompatible` - incompatible
 */
export type LifecycleStatusEnumApi = (typeof LifecycleStatusEnumApi)[keyof typeof LifecycleStatusEnumApi]

export const LifecycleStatusEnumApi = {
    AwaitingGeneration: 'awaiting_generation',
    Generating: 'generating',
    Building: 'building',
    Ready: 'ready',
    Failed: 'failed',
    Incompatible: 'incompatible',
} as const

/**
 * * `generating_source` - generating_source
 * * `reviewing_source` - reviewing_source
 * * `publishing_source` - publishing_source
 * * `unknown` - unknown
 */
export type FailurePhaseEnumApi = (typeof FailurePhaseEnumApi)[keyof typeof FailurePhaseEnumApi]

export const FailurePhaseEnumApi = {
    GeneratingSource: 'generating_source',
    ReviewingSource: 'reviewing_source',
    PublishingSource: 'publishing_source',
    Unknown: 'unknown',
} as const

/**
 * * `queued` - queued
 * * `generating` - generating
 * * `publishing` - publishing
 */
export type WidgetJobStatusEnumApi = (typeof WidgetJobStatusEnumApi)[keyof typeof WidgetJobStatusEnumApi]

export const WidgetJobStatusEnumApi = {
    Queued: 'queued',
    Generating: 'generating',
    Publishing: 'publishing',
} as const

export interface WidgetJobApi {
    /** Generation job identifier. */
    id: string
    /** Current durable job state.
     *
     * * `queued` - queued
     * * `generating` - generating
     * * `publishing` - publishing */
    status: WidgetJobStatusEnumApi
    /** Current generation phase. */
    phase: string
    /** AI model processing the job. */
    model: string
    /** When the job was queued. */
    created_at: string
    /**
     * When a worker started the job.
     * @nullable
     */
    started_at: string | null
}

/**
 * * `none` - none
 * * `low` - low
 * * `medium` - medium
 * * `high` - high
 * * `critical` - critical
 */
export type GeneratedWidgetVersionSecurityReviewSeverityEnumApi =
    (typeof GeneratedWidgetVersionSecurityReviewSeverityEnumApi)[keyof typeof GeneratedWidgetVersionSecurityReviewSeverityEnumApi]

export const GeneratedWidgetVersionSecurityReviewSeverityEnumApi = {
    None: 'none',
    Low: 'low',
    Medium: 'medium',
    High: 'high',
    Critical: 'critical',
} as const

/**
 * * `low` - low
 * * `medium` - medium
 * * `high` - high
 * * `critical` - critical
 */
export type ErrorTrackingIssueSeverityRuleEnumApi =
    (typeof ErrorTrackingIssueSeverityRuleEnumApi)[keyof typeof ErrorTrackingIssueSeverityRuleEnumApi]

export const ErrorTrackingIssueSeverityRuleEnumApi = {
    Low: 'low',
    Medium: 'medium',
    High: 'high',
    Critical: 'critical',
} as const

export interface WidgetSecurityFindingApi {
    /** Severity of this potential security issue.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `critical` - critical */
    severity: ErrorTrackingIssueSeverityRuleEnumApi
    /** Short description of the potential security issue. */
    title: string
    /** Why the source may be unsafe and what it could do. */
    details: string
}

export interface WidgetSecurityReviewApi {
    /** Highest severity found, or none when the review found no issues.
     *
     * * `none` - none
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `critical` - critical */
    severity: GeneratedWidgetVersionSecurityReviewSeverityEnumApi
    /** Concise result from the automated security review. */
    summary: string
    /** Potential security issues found in the source. */
    findings: WidgetSecurityFindingApi[]
    /** Fast AI model used for the security review. */
    model: string
    /** Version of the security review instructions and parser. */
    review_version: string
    /** When this exact widget source was reviewed. */
    reviewed_at: string
}

export interface WidgetStatusApi {
    /** Current widget and preview state.
     *
     * * `awaiting_generation` - awaiting_generation
     * * `generating` - generating
     * * `building` - building
     * * `ready` - ready
     * * `failed` - failed
     * * `incompatible` - incompatible */
    lifecycle_status: LifecycleStatusEnumApi
    /**
     * Actionable failure detail.
     * @nullable
     */
    error_detail?: string | null
    /**
     * Stable failure code for support and diagnostics.
     * @nullable
     */
    error_code?: string | null
    /** Generation step that failed, if a generation job failed.
     *
     * * `generating_source` - generating_source
     * * `reviewing_source` - reviewing_source
     * * `publishing_source` - publishing_source
     * * `unknown` - unknown */
    failure_phase?: FailurePhaseEnumApi | null
    /**
     * Short-lived URL for the selected widget version's preview.
     * @nullable
     */
    artifact_url?: string | null
    /** Logical dataframe slots available to the selected version. */
    frame_names: string[]
    /**
     * Selected immutable widget version.
     * @nullable
     */
    current_version_id: string | null
    /**
     * Reusable widget identity.
     * @nullable
     */
    widget_id: string | null
    /**
     * Placement in this notebook.
     * @nullable
     */
    instance_id: string | null
    /** Whether the widget has generated history. */
    has_versions: boolean
    /** Active generation job, if any. */
    active_job: WidgetJobApi | null
    /** Automated review for the selected source, or null for a legacy unreviewed version. */
    security_review: WidgetSecurityReviewApi | null
    /**
     * Hex SHA-256 over the exact immutable artifact manifest selected for display.
     * @nullable
     */
    build_hash: string | null
}

export interface WidgetRevertRequestApi {
    /** Earlier version to restore as a new version. */
    version_id: string
    /** Current version used for optimistic concurrency. */
    expected_current_version_id: string
}

export interface WidgetSourceApi {
    /** Read-only source code for the current widget version. */
    source: string
}

/**
 * * `initial` - initial
 * * `regenerate` - regenerate
 * * `improve` - improve
 * * `revert` - revert
 */
export type GeneratedWidgetVersionOperationEnumApi =
    (typeof GeneratedWidgetVersionOperationEnumApi)[keyof typeof GeneratedWidgetVersionOperationEnumApi]

export const GeneratedWidgetVersionOperationEnumApi = {
    Initial: 'initial',
    Regenerate: 'regenerate',
    Improve: 'improve',
    Revert: 'revert',
} as const

/**
 * * `queued` - queued
 * * `building` - building
 * * `ready` - ready
 * * `failed` - failed
 */
export type BuildStatusEnumApi = (typeof BuildStatusEnumApi)[keyof typeof BuildStatusEnumApi]

export const BuildStatusEnumApi = {
    Queued: 'queued',
    Building: 'building',
    Ready: 'ready',
    Failed: 'failed',
} as const

export interface WidgetVersionApi {
    /** Immutable widget version identifier. */
    id: string
    /**
     * Version this one was based on.
     * @nullable
     */
    parent_version_id: string | null
    /**
     * One-based version number.
     * @minimum 1
     */
    version: number
    /** Action that created this version.
     *
     * * `initial` - initial
     * * `regenerate` - regenerate
     * * `improve` - improve
     * * `revert` - revert */
    version_operation: GeneratedWidgetVersionOperationEnumApi
    /** Instructions added by this version. */
    prompt_delta: string
    /**
     * Complete instructions represented by this version, up to 50,000 characters.
     * @maxLength 50000
     */
    effective_prompt: string
    /**
     * AI model, or null when this version did not run a model.
     * @nullable
     */
    model: string | null
    /** When this version was created. */
    created_at: string
    /** Preview build state.
     *
     * * `queued` - queued
     * * `building` - building
     * * `ready` - ready
     * * `failed` - failed */
    build_status: BuildStatusEnumApi | null
    /**
     * Preview URL when retained and ready.
     * @nullable
     */
    artifact_url: string | null
    /** Logical dataframe slots available to this version. */
    frame_names: string[]
    /** Whether this notebook instance currently displays this version. */
    is_current: boolean
    /** Automated review for this source, or null for a legacy unreviewed version. */
    security_review: WidgetSecurityReviewApi | null
    /**
     * Hex SHA-256 over this version's exact immutable artifact manifest.
     * @nullable
     */
    build_hash: string | null
}

export interface WidgetVersionPageApi {
    /** Versions ordered newest first. */
    results: WidgetVersionApi[]
    /**
     * Total versions.
     * @minimum 0
     */
    count: number
    /**
     * Offset for the next page.
     * @nullable
     */
    next_offset: number | null
}

export interface NotebookComputePresetApi {
    /** Stable identifier for the preset, e.g. 'balanced'. */
    key: string
    /** Preset name as a person reads it, e.g. 'Balanced'. */
    name: string
    /** What this preset suits, in one sentence. */
    description: string
    /** CPU cores the preset provisions. */
    cpu_cores: number
    /** Memory in GB the preset provisions. */
    memory_gb: number
    /** What this preset costs per hour in USD while it is alive. */
    hourly_price: number
}

export interface NotebookComputeOptionsResponseApi {
    /** Currency of every price in this response. Always 'USD'. */
    currency: string
    /** Price of one CPU core for one hour, in USD. */
    cpu_rate_per_core_hour: number
    /** Price of one GB of memory for one hour, in USD. */
    memory_rate_per_gb_hour: number
    /** Preset a sandbox starts with when the notebook sets no compute config. */
    default_preset_key: string
    /** Sandbox shapes offered as one-click options. */
    presets: NotebookComputePresetApi[]
    /** CPU core counts the kernel config endpoint accepts. */
    allowed_cpu_cores: number[]
    /** Memory sizes in GB the kernel config endpoint accepts. */
    allowed_memory_gb: number[]
    /** Idle timeouts in seconds the kernel config endpoint accepts. */
    allowed_idle_timeout_seconds: number[]
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

export type NotebooksWidgetFrameParams = {
    limit?: number
    offset?: number
    run_id?: string
    version_id?: string
}

export type NotebooksWidgetSourceParams = {
    /**
     * Immutable widget version whose source should be returned.
     */
    version_id?: string
}

export type NotebooksWidgetVersionsParams = {
    limit?: number
    offset?: number
}
