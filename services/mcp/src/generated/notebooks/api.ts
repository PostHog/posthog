/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 10 enabled ops
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const notebooksCreateBodyTitleMax = 256

export const notebooksCreateBodyVersionMin = -2147483648
export const notebooksCreateBodyVersionMax = 2147483647

export const notebooksCreateBodyVariablesItemNameMax = 200

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
    variables: zod
        .array(
            zod
                .object({
                    name: zod
                        .string()
                        .max(notebooksCreateBodyVariablesItemNameMax)
                        .describe(
                            'Identifier the cell reads: `{name}` in a SQL cell, a plain global in a Python cell.'
                        ),
                    type: zod
                        .string()
                        .describe(
                            "How to coerce the value: 'string', 'number', 'boolean', or 'date'. Unknown types read as 'string'."
                        ),
                    value: zod
                        .unknown()
                        .optional()
                        .describe(
                            "The variable's current value. A 'date' accepts an absolute date or a relative expression ('-7d', 'mStart'), resolved against the project timezone."
                        ),
                })
                .describe("One notebook-level variable. Shared by the notebook's own `variables` field and a run body.")
        )
        .optional()
        .describe(
            'Notebook-level variables, in display order. A SQL cell reads one as a `{name}` placeholder and a Python cell as a global. Names must be unique.'
        ),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const notebooksPartialUpdateBodyTitleMax = 256

export const notebooksPartialUpdateBodyVersionMin = -2147483648
export const notebooksPartialUpdateBodyVersionMax = 2147483647

export const notebooksPartialUpdateBodyVariablesItemNameMax = 200

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
    variables: zod
        .array(
            zod
                .object({
                    name: zod
                        .string()
                        .max(notebooksPartialUpdateBodyVariablesItemNameMax)
                        .describe(
                            'Identifier the cell reads: `{name}` in a SQL cell, a plain global in a Python cell.'
                        ),
                    type: zod
                        .string()
                        .describe(
                            "How to coerce the value: 'string', 'number', 'boolean', or 'date'. Unknown types read as 'string'."
                        ),
                    value: zod
                        .unknown()
                        .optional()
                        .describe(
                            "The variable's current value. A 'date' accepts an absolute date or a relative expression ('-7d', 'mStart'), resolved against the project timezone."
                        ),
                })
                .describe("One notebook-level variable. Shared by the notebook's own `variables` field and a run body.")
        )
        .optional()
        .describe(
            'Notebook-level variables, in display order. A SQL cell reads one as a `{name}` placeholder and a Python cell as a global. Names must be unique.'
        ),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const NotebooksDestroyParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * Set the notebook's kernel compute configuration. Applies at sandbox provision time: a currently running kernel keeps its resources until restarted.
 */
export const NotebooksKernelConfigCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const NotebooksKernelConfigCreateBody = /* @__PURE__ */ zod.object({
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

/**
 * Live-checked kernel runtime state for this notebook, its compute configuration, and the catalog of dataframes/tables a cell can currently reference (with column schemas).
 */
export const NotebooksKernelStatusRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * Read a run's durable state: its status, and — once done or interrupted — the result envelope (columns, first rows, stdout/stderr, media, error). Poll until terminal. Flag-gated (revamped-py-notebooks).
 */
export const NotebooksSqlV2RunsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    run_id: zod.string().describe('ID of the run, as returned by the run dispatch endpoint.'),
    short_id: zod.string(),
})

/**
 * Stop a running cell. Idempotent: interrupting an already-finished run returns its outcome unchanged. Flag-gated (revamped-py-notebooks).
 */
export const NotebooksSqlV2RunsInterruptCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    run_id: zod.string().describe('ID of the run, as returned by the run dispatch endpoint.'),
    short_id: zod.string(),
})

/**
 * The full notebook view for agents: title, document source (markdown, or raw content for legacy rich-text notebooks), every cell with its dependency edges and derived run status (including staleness), and the kernel's runtime state and compute config. Flag-gated (revamped-py-notebooks).
 */
export const NotebooksSqlV2StateRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})
