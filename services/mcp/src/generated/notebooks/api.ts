/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const NotebooksListQueryParams = /* @__PURE__ */ zod.object({
    contains: zod
        .string()
        .optional()
        .describe(
            'Filter for notebooks that match a provided filter.\n                Each match pair is separated by a colon,\n                multiple match pairs can be sent separated by a space or a comma'
        ),
    created_by: zod.string().optional().describe("The UUID of the Notebook's creator"),
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Filter for notebooks created after this date & time'),
    date_to: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Filter for notebooks created before this date & time'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    user: zod
        .string()
        .optional()
        .describe('If any value is provided for this parameter, return notebooks created by the logged in user.'),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const notebooksCreateBodyTitleMax = 256

export const notebooksCreateBodyVersionMin = -2147483648
export const notebooksCreateBodyVersionMax = 2147483647

export const NotebooksCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().optional().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksCreateBodyVersionMin)
        .max(notebooksCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    short_id: zod.string(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksPartialUpdateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    short_id: zod.string(),
})

export const notebooksPartialUpdateBodyTitleMax = 256

export const notebooksPartialUpdateBodyVersionMin = -2147483648
export const notebooksPartialUpdateBodyVersionMax = 2147483647

export const NotebooksPartialUpdateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksPartialUpdateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().optional().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksPartialUpdateBodyVersionMin)
        .max(notebooksPartialUpdateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const NotebooksDestroyParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    short_id: zod.string(),
})

/**
 * Dispatch a SQL (HogQL) or Python cell of a revamped notebook to its sandbox kernel. Returns a run_id immediately; poll the run result endpoint until the status is terminal. Requires the notebook's kernel to be running and the revamped-py-notebooks feature.
 * @summary Run a notebook cell
 */
export const NotebooksSqlV2RunCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    short_id: zod.string(),
})

export const notebooksSqlV2RunCreateBodyNodeTypeDefault = `hogql`
export const notebooksSqlV2RunCreateBodyOutputNameDefault = ``
export const notebooksSqlV2RunCreateBodyRefsKindDefault = `hogql`

export const NotebooksSqlV2RunCreateBody = /* @__PURE__ */ zod.object({
    node_id: zod.string().describe('ProseMirror node id of the SQLV2 node being run.'),
    node_type: zod
        .enum(['hogql', 'python'])
        .describe('* `hogql` - hogql\n* `python` - python')
        .default(notebooksSqlV2RunCreateBodyNodeTypeDefault)
        .describe(
            "Execution kind. 'hogql' is a SQL node — pushed to ClickHouse, or rerouted to the sandbox's DuckDB when it references a local frame; 'python' runs the code in the sandbox kernel, materializing referenced upstream nodes as pandas frames first.\n\n* `hogql` - hogql\n* `python` - python"
        ),
    code: zod
        .string()
        .describe("The node's source — SQL for a hogql node, Python for a python node. Must not be blank."),
    output_name: zod
        .string()
        .default(notebooksSqlV2RunCreateBodyOutputNameDefault)
        .describe(
            'Kernel nodes only: the dataframe variable to bind the result to in the kernel namespace (a python node falls back to the last expression for its preview).'
        ),
    refs: zod
        .record(
            zod.string(),
            zod.object({
                node_id: zod.string().describe('ProseMirror node id of the upstream node this name points at.'),
                kind: zod
                    .enum(['hogql', 'local'])
                    .describe('* `hogql` - hogql\n* `local` - local')
                    .default(notebooksSqlV2RunCreateBodyRefsKindDefault)
                    .describe(
                        "What the name resolves to: 'hogql' is a SQL node's query definition (resolved to its last-run HogQL); 'local' is a dataframe a Python node bound in the kernel namespace.\n\n* `hogql` - hogql\n* `local` - local"
                    ),
            })
        )
        .optional()
        .describe(
            "Available upstream nodes, keyed by dataframe name. A SQL node inlines referenced hogql refs as CTEs — unless it references a local ref, which reroutes the run to the sandbox's DuckDB; a python node materializes the hogql refs its code reads as pandas frames."
        ),
})

/**
 * Read a dispatched run's state. Poll until status is 'done', 'failed', or 'interrupted'; done and interrupted runs carry the result envelope (columns, first rows, and for python cells the captured stdout/stderr and figures).
 * @summary Get a notebook cell run's status and result
 */
export const NotebooksSqlV2RunsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    run_id: zod.string().describe('The run_id returned by the run endpoint.'),
    short_id: zod.string(),
})

/**
 * Stop a running cell. The terminal 'interrupted' state (with any captured output) arrives via the run result endpoint; when no kernel is reachable the run is marked interrupted directly.
 * @summary Interrupt a running notebook cell
 */
export const NotebooksSqlV2RunsInterruptCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    run_id: zod.string().describe('The run_id returned by the run endpoint.'),
    short_id: zod.string(),
})
