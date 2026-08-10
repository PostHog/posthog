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
        .describe('Filter for notebooks last modified after this date & time'),
    date_to: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Filter for notebooks last modified before this date & time'),
    excluded_tags: zod
        .string()
        .optional()
        .describe(
            'JSON-encoded list of tag names. Excludes notebooks carrying any of the given tags, even when they also carry non-excluded tags.'
        ),
    last_modified_by: zod.string().optional().describe('UUID of the user who last modified the notebook'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('Full-text search on notebook title and text content'),
    tags: zod
        .string()
        .optional()
        .describe(
            'JSON-encoded list of tag names. Returns notebooks carrying at least one of the given tags, e.g. `[\"growth\", \"checkout\"]`.'
        ),
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

export const notebooksCreateBodyTagsItemMax = 255

export const notebooksCreateBodyTagsMax = 100

export const NotebooksCreateBody = /* @__PURE__ */ zod
    .object({
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
        tags: zod
            .array(zod.string().max(notebooksCreateBodyTagsItemMax))
            .max(notebooksCreateBodyTagsMax)
            .optional()
            .describe('Organizational tags for this notebook (up to 100, 255 characters each).'),
    })
    .describe('Serializer mixin that handles tags for objects.')

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

export const notebooksPartialUpdateBodyTagsItemMax = 255

export const notebooksPartialUpdateBodyTagsMax = 100

export const NotebooksPartialUpdateBody = /* @__PURE__ */ zod
    .object({
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
        tags: zod
            .array(zod.string().max(notebooksPartialUpdateBodyTagsItemMax))
            .max(notebooksPartialUpdateBodyTagsMax)
            .optional()
            .describe('Organizational tags for this notebook (up to 100, 255 characters each).'),
    })
    .describe('Serializer mixin that handles tags for objects.')

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
