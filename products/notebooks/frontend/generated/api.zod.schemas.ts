/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const NotebookMinimalApi = zod.object({
    id: zod.uuid().describe('UUID of the notebook.'),
    short_id: zod.string().describe('Short alphanumeric identifier used in URLs and API lookups.'),
    title: zod.string().nullable().describe('Title of the notebook.'),
    deleted: zod.boolean().describe('Whether the notebook has been soft-deleted.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    last_modified_at: zod.iso.datetime({ offset: true }),
    last_modified_by: UserBasicApi,
    user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    _create_in_folder: zod.string().optional(),
})

export type NotebookMinimalApi = zod.input<typeof NotebookMinimalApi>
export type NotebookMinimalApiOutput = zod.output<typeof NotebookMinimalApi>

export const PaginatedNotebookMinimalListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(NotebookMinimalApi),
})

export type PaginatedNotebookMinimalListApi = zod.input<typeof PaginatedNotebookMinimalListApi>
export type PaginatedNotebookMinimalListApiOutput = zod.output<typeof PaginatedNotebookMinimalListApi>

export const notebookApiTitleMax = 256

export const notebookApiVersionMin = -2147483648
export const notebookApiVersionMax = 2147483647

export const NotebookApi = zod.object({
    id: zod.uuid().describe('UUID of the notebook.'),
    short_id: zod.string().describe('Short alphanumeric identifier used in URLs and API lookups.'),
    title: zod.string().max(notebookApiTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().optional().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebookApiVersionMin)
        .max(notebookApiVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    last_modified_at: zod.iso.datetime({ offset: true }),
    last_modified_by: UserBasicApi,
    user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    parent_resource: zod
        .object({
            type: zod.enum(['account']),
            id: zod.uuid(),
        })
        .nullable()
        .describe(
            "Parent resource this notebook is attached to, or `null`. Returns `{type: 'account', id: <uuid>}` for account-linked notebooks; used by the frontend to route breadcrumbs back to the resource's list."
        ),
    _create_in_folder: zod.string().optional(),
})

export type NotebookApi = zod.input<typeof NotebookApi>
export type NotebookApiOutput = zod.output<typeof NotebookApi>

export const patchedNotebookApiTitleMax = 256

export const patchedNotebookApiVersionMin = -2147483648
export const patchedNotebookApiVersionMax = 2147483647

export const PatchedNotebookApi = zod.object({
    id: zod.uuid().optional().describe('UUID of the notebook.'),
    short_id: zod.string().optional().describe('Short alphanumeric identifier used in URLs and API lookups.'),
    title: zod.string().max(patchedNotebookApiTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().optional().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(patchedNotebookApiVersionMin)
        .max(patchedNotebookApiVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    last_modified_at: zod.iso.datetime({ offset: true }).optional(),
    last_modified_by: UserBasicApi.optional(),
    user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
    parent_resource: zod
        .object({
            type: zod.enum(['account']),
            id: zod.uuid(),
        })
        .nullish()
        .describe(
            "Parent resource this notebook is attached to, or `null`. Returns `{type: 'account', id: <uuid>}` for account-linked notebooks; used by the frontend to route breadcrumbs back to the resource's list."
        ),
    _create_in_folder: zod.string().optional(),
})

export type PatchedNotebookApi = zod.input<typeof PatchedNotebookApi>
export type PatchedNotebookApiOutput = zod.output<typeof PatchedNotebookApi>

export const notebookCollabCursorApiHeadMin = 0

export const notebookCollabCursorApiNodeIndexMin = 0

export const notebookCollabCursorApiOffsetMin = 0

export const notebookCollabCursorApiListItemIndexMin = 0

export const NotebookCollabCursorApi = zod.object({
    head: zod
        .number()
        .min(notebookCollabCursorApiHeadMin)
        .optional()
        .describe('ProseMirror selection head position (rich v1 notebooks).'),
    node_index: zod
        .number()
        .min(notebookCollabCursorApiNodeIndexMin)
        .optional()
        .describe("Index of the caret's block node in the markdown notebook document (markdown notebooks)."),
    offset: zod
        .number()
        .min(notebookCollabCursorApiOffsetMin)
        .optional()
        .describe('Caret offset in the plain text of the focused editable element, in UTF-16 code units.'),
    list_item_index: zod
        .number()
        .min(notebookCollabCursorApiListItemIndexMin)
        .optional()
        .describe('Index of the focused list item when the caret is inside a list block.'),
})

export type NotebookCollabCursorApi = zod.input<typeof NotebookCollabCursorApi>
export type NotebookCollabCursorApiOutput = zod.output<typeof NotebookCollabCursorApi>

export const notebookMarkdownSaveApiTextContentDefault = ``

export const NotebookMarkdownSaveApi = zod.object({
    client_id: zod
        .string()
        .describe('Unique identifier for the client session, used to skip self-echo on the update stream.'),
    version: zod
        .number()
        .describe('The notebook version the submitted content is based on (optimistic concurrency baseline).'),
    content: zod
        .unknown()
        .describe('The full markdown notebook document: a ProseMirror doc wrapping a single markdown node.'),
    text_content: zod
        .string()
        .default(notebookMarkdownSaveApiTextContentDefault)
        .describe('Plain text for search indexing.'),
    title: zod.string().optional().describe('Updated notebook title.'),
    cursor: NotebookCollabCursorApi.optional().describe(
        "The author's caret in the saved markdown, broadcast with the update so other clients can move the author's remote caret together with the text change."
    ),
})

export type NotebookMarkdownSaveApi = zod.input<typeof NotebookMarkdownSaveApi>
export type NotebookMarkdownSaveApiOutput = zod.output<typeof NotebookMarkdownSaveApi>

export const notebookCollabPresenceApiClientIdMax = 200

export const notebookCollabPresenceApiVersionMin = 0

export const NotebookCollabPresenceApi = zod.object({
    client_id: zod
        .string()
        .max(notebookCollabPresenceApiClientIdMax)
        .describe('Unique identifier for the client session, used to skip self-echo on the update stream.'),
    version: zod
        .number()
        .min(notebookCollabPresenceApiVersionMin)
        .describe('The notebook version the cursor position is relative to.'),
    cursor: NotebookCollabCursorApi.describe(
        "The caller's caret position, broadcast to other clients on this notebook's collab stream."
    ),
})

export type NotebookCollabPresenceApi = zod.input<typeof NotebookCollabPresenceApi>
export type NotebookCollabPresenceApiOutput = zod.output<typeof NotebookCollabPresenceApi>

export const notebookCollabSaveApiTextContentDefault = ``

export const NotebookCollabSaveApi = zod.object({
    client_id: zod.string().describe('Unique identifier for the client session.'),
    version: zod.number().describe("The collab version the client's steps are based on."),
    steps: zod.array(zod.unknown()).describe('List of ProseMirror step JSON objects to apply.'),
    content: zod.unknown().describe('The resulting ProseMirror document after applying the steps locally.'),
    text_content: zod
        .string()
        .default(notebookCollabSaveApiTextContentDefault)
        .describe('Plain text for search indexing.'),
    title: zod.string().optional().describe('Updated notebook title.'),
    cursor_head: zod.number().nullish().describe('ProseMirror cursor head position after applying steps.'),
})

export type NotebookCollabSaveApi = zod.input<typeof NotebookCollabSaveApi>
export type NotebookCollabSaveApiOutput = zod.output<typeof NotebookCollabSaveApi>

export const NotebookKernelConfigApi = zod.object({
    cpu_cores: zod
        .number()
        .optional()
        .describe("CPU cores for the notebook's sandbox kernel; must be a supported option."),
    memory_gb: zod
        .number()
        .optional()
        .describe("Memory in GB for the notebook's sandbox kernel; must be a supported option."),
    idle_timeout_seconds: zod
        .number()
        .optional()
        .describe('Seconds of inactivity before the sandbox kernel shuts down.'),
})

export type NotebookKernelConfigApi = zod.input<typeof NotebookKernelConfigApi>
export type NotebookKernelConfigApiOutput = zod.output<typeof NotebookKernelConfigApi>

export const NotebookKernelConfigResponseApi = zod.object({
    cpu_cores: zod.number().nullish().describe('Configured CPU cores; null means the default applies.'),
    memory_gb: zod.number().nullish().describe('Configured memory in GB; null means the default applies.'),
    idle_timeout_seconds: zod
        .number()
        .nullish()
        .describe('Configured idle timeout in seconds; null means the default.'),
    restart_required: zod
        .boolean()
        .describe(
            'True when a kernel is currently active: config applies at sandbox provision time, so the running kernel keeps its old resources until restarted (restarting loses materialized dataframes).'
        ),
})

export type NotebookKernelConfigResponseApi = zod.input<typeof NotebookKernelConfigResponseApi>
export type NotebookKernelConfigResponseApiOutput = zod.output<typeof NotebookKernelConfigResponseApi>

export const notebookSQLV2FrameApiRowCountIsEstimateDefault = false

export const NotebookSQLV2FrameApi = zod.object({
    name: zod.string().describe('Name a SQL node can SELECT from.'),
    kind: zod
        .string()
        .describe(
            "Where the object came from: 'frame' (a dataframe a node produced), or 'table'\/'view' (created by SQL DDL in a DuckDB node)."
        ),
    columns: zod
        .array(zod.array(zod.string()).describe('A [column name, DuckDB type] pair.'))
        .optional()
        .describe('DuckDB type per column, as [name, type] pairs.'),
    row_count: zod
        .number()
        .nullish()
        .describe('Rows available, or null when counting would require a table scan (a DDL view).'),
    row_count_is_estimate: zod
        .boolean()
        .default(notebookSQLV2FrameApiRowCountIsEstimateDefault)
        .describe(
            "True when row_count is DuckDB's optimizer estimate rather than a count. The estimate does not track deletes, so it must never be presented as exact."
        ),
})

export type NotebookSQLV2FrameApi = zod.input<typeof NotebookSQLV2FrameApi>
export type NotebookSQLV2FrameApiOutput = zod.output<typeof NotebookSQLV2FrameApi>

export const NotebookKernelStatusResponseApi = zod.object({
    backend: zod.string().nullish().describe("Sandbox backend the kernel runs on: 'modal' or 'docker'."),
    status: zod
        .string()
        .describe("Live-checked kernel state: 'starting', 'running', 'stopped', 'timed_out', 'discarded', or 'error'."),
    last_used_at: zod.iso.datetime({ offset: true }).nullish().describe('When the kernel last executed anything.'),
    last_error: zod.string().nullish().describe('Most recent provisioning or runtime error, if any.'),
    runtime_id: zod.uuid().nullish().describe('Kernel runtime row identifier.'),
    kernel_id: zod.string().nullish().describe('Jupyter kernel identifier.'),
    kernel_pid: zod.number().nullish().describe('Kernel process id inside the sandbox.'),
    sandbox_id: zod.string().nullish().describe('Sandbox container identifier.'),
    frames: zod
        .array(NotebookSQLV2FrameApi)
        .describe(
            'Dataframes and DuckDB tables a cell can currently reference, with column names and types. Empty unless the kernel is running and the caller has query access.'
        ),
    cpu_cores: zod.number().describe('CPU cores the sandbox is configured with.'),
    memory_gb: zod.number().describe('Memory in GB the sandbox is configured with.'),
    disk_size_gb: zod.number().nullish().describe('Disk size in GB the sandbox is configured with.'),
    idle_timeout_seconds: zod.number().nullish().describe('Seconds of inactivity before the sandbox shuts down.'),
})

export type NotebookKernelStatusResponseApi = zod.input<typeof NotebookKernelStatusResponseApi>
export type NotebookKernelStatusResponseApiOutput = zod.output<typeof NotebookKernelStatusResponseApi>

export const NotebookSQLV2NodeTypeEnumApi = zod
    .enum(['hogql', 'python'])
    .describe('\* `hogql` - hogql\n\* `python` - python')

export type NotebookSQLV2NodeTypeEnumApi = zod.input<typeof NotebookSQLV2NodeTypeEnumApi>
export type NotebookSQLV2NodeTypeEnumApiOutput = zod.output<typeof NotebookSQLV2NodeTypeEnumApi>

export const NotebookSQLV2RefKindEnumApi = zod
    .enum(['hogql', 'local'])
    .describe('\* `hogql` - hogql\n\* `local` - local')

export type NotebookSQLV2RefKindEnumApi = zod.input<typeof NotebookSQLV2RefKindEnumApi>
export type NotebookSQLV2RefKindEnumApiOutput = zod.output<typeof NotebookSQLV2RefKindEnumApi>

export const notebookSQLV2RefApiKindDefault = `hogql`

export const NotebookSQLV2RefApi = zod.object({
    node_id: zod.string().describe('ProseMirror node id of the upstream node this name points at.'),
    kind: NotebookSQLV2RefKindEnumApi.default(notebookSQLV2RefApiKindDefault).describe(
        "What the name resolves to: 'hogql' is a SQL node's query definition (resolved to its last-run HogQL); 'local' is a dataframe a Python node bound in the kernel namespace.\n\n\* `hogql` - hogql\n\* `local` - local"
    ),
})

export type NotebookSQLV2RefApi = zod.input<typeof NotebookSQLV2RefApi>
export type NotebookSQLV2RefApiOutput = zod.output<typeof NotebookSQLV2RefApi>

export const notebookSQLV2RunRequestApiNodeTypeDefault = `hogql`
export const notebookSQLV2RunRequestApiOutputNameDefault = ``

export const NotebookSQLV2RunRequestApi = zod.object({
    node_id: zod.string().describe('ProseMirror node id of the SQLV2 node being run.'),
    node_type: NotebookSQLV2NodeTypeEnumApi.default(notebookSQLV2RunRequestApiNodeTypeDefault).describe(
        "Execution kind. 'hogql' is a SQL node — pushed to ClickHouse, or rerouted to the sandbox's DuckDB when it references a local frame; 'python' runs the code in the sandbox kernel, materializing referenced upstream nodes as pandas frames first.\n\n\* `hogql` - hogql\n\* `python` - python"
    ),
    code: zod
        .string()
        .describe("The node's source — SQL for a hogql node, Python for a python node. Must not be blank."),
    output_name: zod
        .string()
        .default(notebookSQLV2RunRequestApiOutputNameDefault)
        .describe(
            'Kernel nodes only: the dataframe variable to bind the result to in the kernel namespace (a python node falls back to the last expression for its preview).'
        ),
    refs: zod
        .record(zod.string(), NotebookSQLV2RefApi)
        .optional()
        .describe(
            "Available upstream nodes, keyed by dataframe name. A SQL node inlines referenced hogql refs as CTEs — unless it references a local ref, which reroutes the run to the sandbox's DuckDB; a python node materializes the hogql refs its code reads as pandas frames."
        ),
})

export type NotebookSQLV2RunRequestApi = zod.input<typeof NotebookSQLV2RunRequestApi>
export type NotebookSQLV2RunRequestApiOutput = zod.output<typeof NotebookSQLV2RunRequestApi>

export const NotebookSQLV2RunResponseApi = zod.object({
    run_id: zod
        .uuid()
        .describe(
            'Identifier of the dispatched run. Poll the run result endpoint with it until the status is terminal.'
        ),
})

export type NotebookSQLV2RunResponseApi = zod.input<typeof NotebookSQLV2RunResponseApi>
export type NotebookSQLV2RunResponseApiOutput = zod.output<typeof NotebookSQLV2RunResponseApi>

export const NotebookSQLV2MediaApi = zod.object({
    mime_type: zod.string().describe("MIME type of the media, e.g. 'image\/png' for a matplotlib figure."),
    data: zod.string().describe('Base64-encoded media bytes.'),
})

export type NotebookSQLV2MediaApi = zod.input<typeof NotebookSQLV2MediaApi>
export type NotebookSQLV2MediaApiOutput = zod.output<typeof NotebookSQLV2MediaApi>

export const notebookSQLV2EnvelopeApiStdoutDefault = ``
export const notebookSQLV2EnvelopeApiStderrDefault = ``
export const notebookSQLV2EnvelopeApiRowCountDefault = 0
export const notebookSQLV2EnvelopeApiHasMoreDefault = false

export const NotebookSQLV2EnvelopeApi = zod.object({
    status: zod.string().describe("Run outcome: 'ok', 'error', or 'interrupted' (user-requested stop)."),
    frames: zod
        .array(NotebookSQLV2FrameApi)
        .optional()
        .describe(
            'DuckDB objects a SQL node can SELECT from as of this run, for the schema browser. Only kernel runs (python\/duckdb) report these; a hogql run never enters the kernel.'
        ),
    stdout: zod
        .string()
        .default(notebookSQLV2EnvelopeApiStdoutDefault)
        .describe('Captured stdout from a Python node run.'),
    stderr: zod
        .string()
        .default(notebookSQLV2EnvelopeApiStderrDefault)
        .describe('Captured stderr (including tracebacks) from a Python node run.'),
    media: zod
        .array(NotebookSQLV2MediaApi)
        .optional()
        .describe('Rich outputs from a Python node run, e.g. matplotlib figures as PNGs.'),
    columns: zod.array(zod.string()).optional().describe('Result column names.'),
    types: zod
        .array(zod.array(zod.string()).describe('A [column name, ClickHouse type] pair.'))
        .optional()
        .describe('ClickHouse type per column, as [name, type] pairs; used by the visualization tab.'),
    row_count: zod.number().default(notebookSQLV2EnvelopeApiRowCountDefault).describe('Number of rows in the result.'),
    has_more: zod
        .boolean()
        .default(notebookSQLV2EnvelopeApiHasMoreDefault)
        .describe('Whether ClickHouse has more rows beyond first_page (detected by fetching limit+1).'),
    first_page: zod
        .array(zod.array(zod.unknown()).describe('A single result row as a list of cell values.'))
        .optional()
        .describe('First page of result rows for display; each row is a list of cell values.'),
    result_id: zod.uuid().nullish().describe('Identifier of the materialized result, used as the paging key.'),
    error: zod.string().nullish().describe("Error message when status is 'error'."),
    timings: zod
        .record(zod.string(), zod.number())
        .optional()
        .describe(
            'Phase durations in seconds. From the sandbox: input_wait_s (waiting on the data plane), download_s (presigned frame downloads), kernel_boot_s (ensuring the ipykernel is up), exec_s (kernel cell execution), sandbox_total_s (the whole sandbox-side run). From the direct lane: queued_s (enqueue to Celery pickup), clickhouse_s (pickup to completion). Feeds the node-run metrics.'
        ),
})

export type NotebookSQLV2EnvelopeApi = zod.input<typeof NotebookSQLV2EnvelopeApi>
export type NotebookSQLV2EnvelopeApiOutput = zod.output<typeof NotebookSQLV2EnvelopeApi>

export const NotebookSQLV2RunStatusResponseApi = zod.object({
    status: zod
        .string()
        .describe("Run state: 'running' (keep polling), or terminal — 'done', 'failed', or 'interrupted'."),
    result: zod
        .union([NotebookSQLV2EnvelopeApi, zod.null()])
        .optional()
        .describe(
            "The result envelope once the run is 'done' or 'interrupted' (an interrupted run keeps the stdout\/stderr captured before the stop); null while running and for failed runs."
        ),
    error: zod
        .string()
        .nullish()
        .describe(
            "Why the run failed when it never produced an envelope (dispatch or watchdog failure); execution errors arrive inside the envelope's error field instead."
        ),
    rows: zod
        .array(zod.array(zod.unknown()).describe('A single result row as a list of cell values.'))
        .optional()
        .describe(
            "SQL (hogql) runs only: the full capped row set for client-side paging, present while the query manager's transient result is alive (~20 minutes). Absent afterwards and for kernel (python\/duckdb) runs, which keep only the envelope's first_page preview."
        ),
})

export type NotebookSQLV2RunStatusResponseApi = zod.input<typeof NotebookSQLV2RunStatusResponseApi>
export type NotebookSQLV2RunStatusResponseApiOutput = zod.output<typeof NotebookSQLV2RunStatusResponseApi>

export const NotebookSQLV2InterruptResponseApi = zod.object({
    status: zod
        .string()
        .describe(
            "The run's status after the interrupt request. Already-terminal runs return their outcome unchanged (idempotent noop); a stopped kernel run reports its terminal state through the normal result poll."
        ),
    detail: zod
        .string()
        .optional()
        .describe('Present when the interrupt could not take effect yet, e.g. the run has not reached the kernel.'),
})

export type NotebookSQLV2InterruptResponseApi = zod.input<typeof NotebookSQLV2InterruptResponseApi>
export type NotebookSQLV2InterruptResponseApiOutput = zod.output<typeof NotebookSQLV2InterruptResponseApi>

export const NotebookKernelStateApi = zod.object({
    status: zod
        .string()
        .describe("Kernel runtime state: 'starting', 'running', 'stopped', 'timed_out', 'discarded', or 'error'."),
    cpu_cores: zod.number().nullish().describe("CPU cores the notebook's sandbox is configured with."),
    memory_gb: zod.number().nullish().describe("Memory in GB the notebook's sandbox is configured with."),
    idle_timeout_seconds: zod.number().nullish().describe('Seconds of inactivity before the sandbox shuts down.'),
})

export type NotebookKernelStateApi = zod.input<typeof NotebookKernelStateApi>
export type NotebookKernelStateApiOutput = zod.output<typeof NotebookKernelStateApi>

export const NotebookCellLastRunApi = zod.object({
    run_id: zod.uuid().describe("Identifier of the cell's most recent run."),
    status: zod.string().describe("The run's own state: 'running', 'done', 'failed', or 'interrupted'."),
    finished_at: zod.iso.datetime({ offset: true }).describe('When the run last changed state.'),
    row_count: zod.number().nullish().describe('Rows in the result, when the run produced one.'),
    columns: zod.array(zod.string()).nullish().describe('Result column names.'),
    error: zod.string().nullish().describe('Error message when the run failed.'),
})

export type NotebookCellLastRunApi = zod.input<typeof NotebookCellLastRunApi>
export type NotebookCellLastRunApiOutput = zod.output<typeof NotebookCellLastRunApi>

export const NotebookCellStateApi = zod.object({
    node_id: zod.string().describe('Durable cell identity, used by the cell run and edit endpoints.'),
    cell_type: zod.string().describe("Cell kind: 'sql', 'python', or 'saved_insight' (embedded insight, never runs)."),
    dataframe_name: zod
        .string()
        .describe("Name other cells reference this cell's result by; blank means display-only."),
    code: zod.string().describe("The cell's source, truncated with a marker past 8KB."),
    status: zod
        .string()
        .describe(
            "Derived cell state: 'never_run', 'running', 'done', 'failed', 'interrupted', or 'stale' — stale means re-running now would execute different code than the last completed run (the cell or an upstream dependency changed)."
        ),
    depends_on: zod.array(zod.string()).describe("node_ids of cells whose dataframes this cell's code references."),
    dependents: zod.array(zod.string()).describe("node_ids of cells that reference this cell's dataframe."),
    last_run: zod
        .union([NotebookCellLastRunApi, zod.null()])
        .optional()
        .describe('Summary of the most recent run; null when never run.'),
})

export type NotebookCellStateApi = zod.input<typeof NotebookCellStateApi>
export type NotebookCellStateApiOutput = zod.output<typeof NotebookCellStateApi>

export const NotebookSQLV2StateResponseApi = zod.object({
    notebook_id: zod.string().describe("The notebook's short id."),
    title: zod.string().nullable().describe("The notebook's title."),
    version: zod.number().nullable().describe('Document version, the optimistic-concurrency baseline for edits.'),
    markdown: zod
        .string()
        .nullable()
        .describe(
            'The full markdown source — prose and cell tags. Null for legacy rich-text notebooks, which carry their document in `content` instead.'
        ),
    content: zod
        .unknown()
        .optional()
        .describe(
            'Legacy rich-text notebooks only: the raw ProseMirror document. Omitted for markdown notebooks — their document is the `markdown` field.'
        ),
    kernel: NotebookKernelStateApi.describe("The notebook's kernel runtime state and compute config."),
    cells: zod
        .array(NotebookCellStateApi)
        .describe('Every cell in document order, with its dependency edges and derived run state.'),
})

export type NotebookSQLV2StateResponseApi = zod.input<typeof NotebookSQLV2StateResponseApi>
export type NotebookSQLV2StateResponseApiOutput = zod.output<typeof NotebookSQLV2StateResponseApi>
