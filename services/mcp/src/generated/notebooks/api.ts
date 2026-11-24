/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 16 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const ReusableWidgetsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ReusableWidgetsListQueryParams = () => zod.object({
    limit: zod.number().optional(),
    offset: zod.number().optional(),
    search: zod.string().optional(),
})

export const ReusableWidgetsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const NotebooksListQueryParams = () => zod.object({
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
export const NotebooksRetrieveParams = () => zod.object({
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
export const NotebooksPartialUpdateParams = () => zod.object({
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

export const notebooksPartialUpdateBodyAppDraftOneTitleDefault = ``
export const notebooksPartialUpdateBodyAppDraftOneTitleMax = 256

export const notebooksPartialUpdateBodyAppDraftOneDescriptionDefault = ``
export const notebooksPartialUpdateBodyAppDraftOneDescriptionMax = 2000

export const notebooksPartialUpdateBodyAppDraftOneFullWidthDefault = false
export const notebooksPartialUpdateBodyAppDraftOneTabsItemIdMax = 80

export const notebooksPartialUpdateBodyAppDraftOneTabsItemTitleMax = 80

export const notebooksPartialUpdateBodyAppDraftOneBlocksItemIdMax = 80

export const notebooksPartialUpdateBodyAppDraftOneBlocksItemTabIdMax = 80

export const notebooksPartialUpdateBodyAppDraftOneBlocksItemTitleDefault = ``
export const notebooksPartialUpdateBodyAppDraftOneBlocksItemTitleMax = 256

export const notebooksPartialUpdateBodyAppDraftOneBlocksItemWidthDefault = 12
export const notebooksPartialUpdateBodyAppDraftOneBlocksItemWidthMax = 12

export const notebooksPartialUpdateBodyAppDraftOneBlocksItemNodeIdDefault = ``
export const notebooksPartialUpdateBodyAppDraftOneBlocksItemNodeIdMax = 160

export const notebooksPartialUpdateBodyAppDraftOneBlocksItemTextDefault = ``
export const notebooksPartialUpdateBodyAppDraftOneBlocksItemTextMax = 20000

export const notebooksPartialUpdateBodyAppDraftOneBlocksItemVariableDefault = ``
export const notebooksPartialUpdateBodyAppDraftOneBlocksItemVariableMax = 80

export const notebooksPartialUpdateBodyAppDraftOneBlocksItemInputKindDefault = `auto`
export const notebooksPartialUpdateBodyAppDraftOneBlocksItemOptionsItemMax = 1000

export const notebooksPartialUpdateBodyAppDraftOneBlocksItemOptionsMax = 100

export const notebooksPartialUpdateBodyAppDraftOneBlocksItemMinDefault = 0
export const notebooksPartialUpdateBodyAppDraftOneBlocksItemMaxDefault = 100
export const notebooksPartialUpdateBodyAppDraftOneBlocksItemStepDefault = 1
export const notebooksPartialUpdateBodyAppDraftOneBlocksItemStepMin = 0.000001

export const notebooksPartialUpdateBodyAppDraftOneBlocksItemDisplayDefault = `output`
export const notebooksPartialUpdateBodyAppPublishedOneTitleDefault = ``
export const notebooksPartialUpdateBodyAppPublishedOneTitleMax = 256

export const notebooksPartialUpdateBodyAppPublishedOneDescriptionDefault = ``
export const notebooksPartialUpdateBodyAppPublishedOneDescriptionMax = 2000

export const notebooksPartialUpdateBodyAppPublishedOneFullWidthDefault = false
export const notebooksPartialUpdateBodyAppPublishedOneTabsItemIdMax = 80

export const notebooksPartialUpdateBodyAppPublishedOneTabsItemTitleMax = 80

export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemIdMax = 80

export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemTabIdMax = 80

export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemTitleDefault = ``
export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemTitleMax = 256

export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemWidthDefault = 12
export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemWidthMax = 12

export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemNodeIdDefault = ``
export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemNodeIdMax = 160

export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemTextDefault = ``
export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemTextMax = 20000

export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemVariableDefault = ``
export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemVariableMax = 80

export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemInputKindDefault = `auto`
export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemOptionsItemMax = 1000

export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemOptionsMax = 100

export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemMinDefault = 0
export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemMaxDefault = 100
export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemStepDefault = 1
export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemStepMin = 0.000001

export const notebooksPartialUpdateBodyAppPublishedOneBlocksItemDisplayDefault = `output`
export const notebooksPartialUpdateBodyAppRevisionMin = 0

export const NotebooksPartialUpdateBody = () => zod.object({
    title: zod.string().max(notebooksPartialUpdateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod
        .unknown()
        .optional()
        .describe(
            'Notebook content as a ProseMirror JSON document. On create, the server stores it as a markdown notebook: one ph-markdown-notebook node that holds the converted markdown.'
        ),
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
                            "The variable's current value. A 'date' is an absolute date or datetime in ISO 8601 form ('2025-01-31', '2025-01-31T09:00:00Z'); relative expressions such as '-7d' are rejected."
                        ),
                })
                .describe("One notebook-level variable. Shared by the notebook's own `variables` field and a run body.")
        )
        .optional()
        .describe(
            'Notebook-level variables, in display order. A SQL cell reads one as a `{name}` placeholder and a Python cell as a global. Names must be unique.'
        ),
    restore_previous_app_release: zod.boolean().optional(),
    app_draft: zod
        .union([
            zod.object({
                title: zod
                    .string()
                    .max(notebooksPartialUpdateBodyAppDraftOneTitleMax)
                    .default(notebooksPartialUpdateBodyAppDraftOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksPartialUpdateBodyAppDraftOneDescriptionMax)
                    .default(notebooksPartialUpdateBodyAppDraftOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksPartialUpdateBodyAppDraftOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppDraftOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppDraftOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppDraftOneBlocksItemIdMax)
                                .describe('Stable component identifier within the app.'),
                            kind: zod
                                .enum(['cell', 'text', 'input', 'divider'])
                                .describe(
                                    '\* `cell` - Notebook cell\n\* `text` - Text\n\* `input` - Input\n\* `divider` - Divider'
                                )
                                .describe(
                                    'Type of app component.\n\n\* `cell` - Notebook cell\n\* `text` - Text\n\* `input` - Input\n\* `divider` - Divider'
                                ),
                            tab_id: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppDraftOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppDraftOneBlocksItemTitleMax)
                                .default(notebooksPartialUpdateBodyAppDraftOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksPartialUpdateBodyAppDraftOneBlocksItemWidthMax)
                                .default(notebooksPartialUpdateBodyAppDraftOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppDraftOneBlocksItemNodeIdMax)
                                .default(notebooksPartialUpdateBodyAppDraftOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppDraftOneBlocksItemTextMax)
                                .default(notebooksPartialUpdateBodyAppDraftOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppDraftOneBlocksItemVariableMax)
                                .default(notebooksPartialUpdateBodyAppDraftOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksPartialUpdateBodyAppDraftOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(zod.string().max(notebooksPartialUpdateBodyAppDraftOneBlocksItemOptionsItemMax))
                                .max(notebooksPartialUpdateBodyAppDraftOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksPartialUpdateBodyAppDraftOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksPartialUpdateBodyAppDraftOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksPartialUpdateBodyAppDraftOneBlocksItemStepMin)
                                .default(notebooksPartialUpdateBodyAppDraftOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksPartialUpdateBodyAppDraftOneBlocksItemDisplayDefault)
                                .describe(
                                    'Whether to display cell source, output, or both.\n\n\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output'
                                ),
                        })
                    )
                    .describe('Ordered components, arranged in rows within each tab.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Editable app layout. Does not change the published layout.'),
    app_published: zod
        .union([
            zod.object({
                title: zod
                    .string()
                    .max(notebooksPartialUpdateBodyAppPublishedOneTitleMax)
                    .default(notebooksPartialUpdateBodyAppPublishedOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksPartialUpdateBodyAppPublishedOneDescriptionMax)
                    .default(notebooksPartialUpdateBodyAppPublishedOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksPartialUpdateBodyAppPublishedOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppPublishedOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppPublishedOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppPublishedOneBlocksItemIdMax)
                                .describe('Stable component identifier within the app.'),
                            kind: zod
                                .enum(['cell', 'text', 'input', 'divider'])
                                .describe(
                                    '\* `cell` - Notebook cell\n\* `text` - Text\n\* `input` - Input\n\* `divider` - Divider'
                                )
                                .describe(
                                    'Type of app component.\n\n\* `cell` - Notebook cell\n\* `text` - Text\n\* `input` - Input\n\* `divider` - Divider'
                                ),
                            tab_id: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppPublishedOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppPublishedOneBlocksItemTitleMax)
                                .default(notebooksPartialUpdateBodyAppPublishedOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksPartialUpdateBodyAppPublishedOneBlocksItemWidthMax)
                                .default(notebooksPartialUpdateBodyAppPublishedOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppPublishedOneBlocksItemNodeIdMax)
                                .default(notebooksPartialUpdateBodyAppPublishedOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppPublishedOneBlocksItemTextMax)
                                .default(notebooksPartialUpdateBodyAppPublishedOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksPartialUpdateBodyAppPublishedOneBlocksItemVariableMax)
                                .default(notebooksPartialUpdateBodyAppPublishedOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksPartialUpdateBodyAppPublishedOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(
                                    zod.string().max(notebooksPartialUpdateBodyAppPublishedOneBlocksItemOptionsItemMax)
                                )
                                .max(notebooksPartialUpdateBodyAppPublishedOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksPartialUpdateBodyAppPublishedOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksPartialUpdateBodyAppPublishedOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksPartialUpdateBodyAppPublishedOneBlocksItemStepMin)
                                .default(notebooksPartialUpdateBodyAppPublishedOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksPartialUpdateBodyAppPublishedOneBlocksItemDisplayDefault)
                                .describe(
                                    'Whether to display cell source, output, or both.\n\n\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output'
                                ),
                        })
                    )
                    .describe('Ordered components, arranged in rows within each tab.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Publish this layout with the saved notebook sources and input defaults. Null unpublishes the app.'),
    app_revision: zod
        .number()
        .min(notebooksPartialUpdateBodyAppRevisionMin)
        .optional()
        .describe('Current app revision. Required when saving or publishing a layout; stale revisions return 409.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const NotebooksDestroyParams = () => zod.object({
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
export const NotebooksKernelConfigCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const NotebooksKernelConfigCreateBody = () => zod.object({
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
        .describe(
            'Maximum lifetime of the sandbox kernel in seconds. It shuts down this long after it starts, even while in use. A running kernel keeps its current lifetime until it restarts.'
        ),
})

/**
 * Live-checked kernel runtime state for this notebook, its compute configuration, and the catalog of dataframes/tables a cell can currently reference (with column schemas).
 */
export const NotebooksKernelStatusRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * Read a run's durable state: its status, and — once done or interrupted — the result envelope (columns, first rows, stdout/stderr, media, error). Poll until terminal. Requires notebook and query read access, including after a notebook feature flag is disabled.
 */
export const NotebooksSqlV2RunsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    run_id: zod.string().describe('ID of the run, as returned by the run dispatch endpoint.'),
    short_id: zod.string(),
})

export const NotebooksSqlV2RunsRetrieveQueryParams = () => zod.object({
    node_id: zod.string().optional().describe('Only return the run if it belongs to this cell.'),
})

/**
 * Stop a running cell. Idempotent: interrupting an already-finished run returns its outcome unchanged.
 */
export const NotebooksSqlV2RunsInterruptCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    run_id: zod.string().describe('ID of the run, as returned by the run dispatch endpoint.'),
    short_id: zod.string(),
})

/**
 * The full notebook view for agents: title, document source (markdown, or raw content for legacy rich-text notebooks), the notebook's declared variables, every cell with its dependency edges and derived run status (including staleness), and the kernel's runtime state and compute config.
 */
export const NotebooksSqlV2StateRetrieveParams = () => zod.object({
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
export const NotebooksWidgetAttachParams = () => zod.object({
    node_id: zod.string().describe('Stable identifier of the generated widget node.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const NotebooksWidgetAttachBody = () => zod.object({
    widget_id: zod.string().describe('Reusable widget to place in this notebook node.'),
    version_id: zod
        .string()
        .nullish()
        .describe("Version to pin, or null to follow the reusable widget's latest version."),
    input_bindings: zod
        .record(
            zod.string(),
            zod.object({
                source: zod.string(),
                hog: zod.string().optional(),
            })
        )
        .optional()
        .describe(
            'Notebook-local input mappings keyed by contract slot. Each value names a source dataframe and may include pure Hog source for reshaping its rows.'
        ),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksWidgetCancelParams = () => zod.object({
    node_id: zod.string().describe('Stable identifier of the generated widget node.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const NotebooksWidgetCancelBody = () => zod.object({
    generation_id: zod.string().describe('Generation job to cancel.'),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksWidgetGenerateParams = () => zod.object({
    node_id: zod.string().describe('Stable identifier of the generated widget node.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const notebooksWidgetGenerateBodyPromptMax = 50000

export const notebooksWidgetGenerateBodyModelDefault = `claude-sonnet-5`
export const notebooksWidgetGenerateBodyGenerationOperationDefault = `regenerate`

export const NotebooksWidgetGenerateBody = () => zod.object({
    prompt: zod
        .string()
        .max(notebooksWidgetGenerateBodyPromptMax)
        .describe(
            'Instructions for the generated widget. Initial and improvement instructions accept up to 20,000 characters; regeneration accepts complete instructions up to 50,000 characters.'
        ),
    generation_id: zod.string().describe('Idempotency key for this generation job.'),
    model: zod
        .enum(['claude-haiku-4-5', 'claude-sonnet-4-6', 'claude-sonnet-5', 'claude-opus-5'])
        .describe(
            '\* `claude-haiku-4-5` - claude-haiku-4-5\n\* `claude-sonnet-4-6` - claude-sonnet-4-6\n\* `claude-sonnet-5` - claude-sonnet-5\n\* `claude-opus-5` - claude-opus-5'
        )
        .default(notebooksWidgetGenerateBodyModelDefault)
        .describe(
            'AI model used to generate the widget.\n\n\* `claude-haiku-4-5` - claude-haiku-4-5\n\* `claude-sonnet-4-6` - claude-sonnet-4-6\n\* `claude-sonnet-5` - claude-sonnet-5\n\* `claude-opus-5` - claude-opus-5'
        ),
    generation_operation: zod
        .enum(['initial', 'regenerate', 'improve'])
        .describe('\* `initial` - initial\n\* `regenerate` - regenerate\n\* `improve` - improve')
        .default(notebooksWidgetGenerateBodyGenerationOperationDefault)
        .describe(
            'Whether to generate from scratch or improve the current source.\n\n\* `initial` - initial\n\* `regenerate` - regenerate\n\* `improve` - improve'
        ),
    expected_current_version_id: zod
        .string()
        .optional()
        .describe('Current widget version the improvement is based on. Required for improve operations.'),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksWidgetStatusParams = () => zod.object({
    node_id: zod.string().describe('Stable identifier of the generated widget node.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * Compute rates, presets, and the sizes the kernel config endpoint accepts. Static per region, so a client can fetch it once and price any shape a user picks.
 */
export const NotebooksKernelComputeOptionsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
