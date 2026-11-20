/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const reusableWidgetsUpdateDemoDataBodyFrameNameMax = 200

export const reusableWidgetsUpdateDemoDataBodyRowsMax = 20

export const ReusableWidgetsUpdateDemoDataBody = /* @__PURE__ */ zod.object({
    version_id: zod.uuid().describe('Current or draft version whose demo data should be edited.'),
    frame_name: zod
        .string()
        .max(reusableWidgetsUpdateDemoDataBodyFrameNameMax)
        .describe('Logical input slot whose saved rows should be replaced.'),
    rows: zod
        .array(zod.array(zod.unknown()))
        .max(reusableWidgetsUpdateDemoDataBodyRowsMax)
        .describe("Saved demo rows in input-contract column order. Replaces this slot's entire sample, up to 20 rows."),
})

export const ReusableWidgetsDiscardVersionBody = /* @__PURE__ */ zod.object({
    pending_version_id: zod.uuid().describe('Draft version being reviewed.'),
    expected_current_version_id: zod.uuid().describe('Published version observed when the review action started.'),
})

export const reusableWidgetsGenerateBodyPromptMax = 50000

export const reusableWidgetsGenerateBodyModelDefault = `claude-sonnet-5`
export const reusableWidgetsGenerateBodyGenerationOperationDefault = `regenerate`

export const ReusableWidgetsGenerateBody = /* @__PURE__ */ zod.object({
    prompt: zod
        .string()
        .max(reusableWidgetsGenerateBodyPromptMax)
        .describe(
            'Instructions for the generated widget. Initial and improvement instructions accept up to 20,000 characters; regeneration accepts complete instructions up to 50,000 characters.'
        ),
    generation_id: zod.uuid().describe('Idempotency key for this generation job.'),
    model: zod
        .enum(['claude-haiku-4-5', 'claude-sonnet-4-6', 'claude-sonnet-5', 'claude-opus-5'])
        .describe(
            '\* `claude-haiku-4-5` - claude-haiku-4-5\n\* `claude-sonnet-4-6` - claude-sonnet-4-6\n\* `claude-sonnet-5` - claude-sonnet-5\n\* `claude-opus-5` - claude-opus-5'
        )
        .default(reusableWidgetsGenerateBodyModelDefault)
        .describe(
            'AI model used to generate the widget.\n\n\* `claude-haiku-4-5` - claude-haiku-4-5\n\* `claude-sonnet-4-6` - claude-sonnet-4-6\n\* `claude-sonnet-5` - claude-sonnet-5\n\* `claude-opus-5` - claude-opus-5'
        ),
    generation_operation: zod
        .enum(['initial', 'regenerate', 'improve'])
        .describe('\* `initial` - initial\n\* `regenerate` - regenerate\n\* `improve` - improve')
        .default(reusableWidgetsGenerateBodyGenerationOperationDefault)
        .describe(
            'Whether to generate from scratch or improve the current source.\n\n\* `initial` - initial\n\* `regenerate` - regenerate\n\* `improve` - improve'
        ),
    expected_current_version_id: zod
        .uuid()
        .optional()
        .describe('Current widget version the improvement is based on. Required for improve operations.'),
})

export const ReusableWidgetsRestoreBody = /* @__PURE__ */ zod.object({
    version_id: zod.uuid().describe('Published version to copy into a new latest version.'),
    expected_current_version_id: zod.uuid().describe('Latest version observed before restoring.'),
})

export const ReusableWidgetsSaveVersionBody = /* @__PURE__ */ zod.object({
    pending_version_id: zod.uuid().describe('Draft version being reviewed.'),
    expected_current_version_id: zod.uuid().describe('Published version observed when the review action started.'),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksCreateBodyTitleMax = 256

export const notebooksCreateBodyVersionMin = -2147483648
export const notebooksCreateBodyVersionMax = 2147483647

export const notebooksCreateBodyVariablesItemNameMax = 200

export const notebooksCreateBodyAppDraftOneTitleDefault = ``
export const notebooksCreateBodyAppDraftOneTitleMax = 256

export const notebooksCreateBodyAppDraftOneDescriptionDefault = ``
export const notebooksCreateBodyAppDraftOneDescriptionMax = 2000

export const notebooksCreateBodyAppDraftOneFullWidthDefault = false
export const notebooksCreateBodyAppDraftOneTabsItemIdMax = 80

export const notebooksCreateBodyAppDraftOneTabsItemTitleMax = 80

export const notebooksCreateBodyAppDraftOneBlocksItemIdMax = 80

export const notebooksCreateBodyAppDraftOneBlocksItemTabIdMax = 80

export const notebooksCreateBodyAppDraftOneBlocksItemTitleDefault = ``
export const notebooksCreateBodyAppDraftOneBlocksItemTitleMax = 256

export const notebooksCreateBodyAppDraftOneBlocksItemWidthDefault = 12
export const notebooksCreateBodyAppDraftOneBlocksItemWidthMax = 12

export const notebooksCreateBodyAppDraftOneBlocksItemNodeIdDefault = ``
export const notebooksCreateBodyAppDraftOneBlocksItemNodeIdMax = 160

export const notebooksCreateBodyAppDraftOneBlocksItemTextDefault = ``
export const notebooksCreateBodyAppDraftOneBlocksItemTextMax = 20000

export const notebooksCreateBodyAppDraftOneBlocksItemVariableDefault = ``
export const notebooksCreateBodyAppDraftOneBlocksItemVariableMax = 80

export const notebooksCreateBodyAppDraftOneBlocksItemInputKindDefault = `auto`
export const notebooksCreateBodyAppDraftOneBlocksItemOptionsItemMax = 1000

export const notebooksCreateBodyAppDraftOneBlocksItemOptionsMax = 100

export const notebooksCreateBodyAppDraftOneBlocksItemMinDefault = 0
export const notebooksCreateBodyAppDraftOneBlocksItemMaxDefault = 100
export const notebooksCreateBodyAppDraftOneBlocksItemStepDefault = 1
export const notebooksCreateBodyAppDraftOneBlocksItemStepMin = 0.000001

export const notebooksCreateBodyAppDraftOneBlocksItemDisplayDefault = `output`
export const notebooksCreateBodyAppPublishedOneTitleDefault = ``
export const notebooksCreateBodyAppPublishedOneTitleMax = 256

export const notebooksCreateBodyAppPublishedOneDescriptionDefault = ``
export const notebooksCreateBodyAppPublishedOneDescriptionMax = 2000

export const notebooksCreateBodyAppPublishedOneFullWidthDefault = false
export const notebooksCreateBodyAppPublishedOneTabsItemIdMax = 80

export const notebooksCreateBodyAppPublishedOneTabsItemTitleMax = 80

export const notebooksCreateBodyAppPublishedOneBlocksItemIdMax = 80

export const notebooksCreateBodyAppPublishedOneBlocksItemTabIdMax = 80

export const notebooksCreateBodyAppPublishedOneBlocksItemTitleDefault = ``
export const notebooksCreateBodyAppPublishedOneBlocksItemTitleMax = 256

export const notebooksCreateBodyAppPublishedOneBlocksItemWidthDefault = 12
export const notebooksCreateBodyAppPublishedOneBlocksItemWidthMax = 12

export const notebooksCreateBodyAppPublishedOneBlocksItemNodeIdDefault = ``
export const notebooksCreateBodyAppPublishedOneBlocksItemNodeIdMax = 160

export const notebooksCreateBodyAppPublishedOneBlocksItemTextDefault = ``
export const notebooksCreateBodyAppPublishedOneBlocksItemTextMax = 20000

export const notebooksCreateBodyAppPublishedOneBlocksItemVariableDefault = ``
export const notebooksCreateBodyAppPublishedOneBlocksItemVariableMax = 80

export const notebooksCreateBodyAppPublishedOneBlocksItemInputKindDefault = `auto`
export const notebooksCreateBodyAppPublishedOneBlocksItemOptionsItemMax = 1000

export const notebooksCreateBodyAppPublishedOneBlocksItemOptionsMax = 100

export const notebooksCreateBodyAppPublishedOneBlocksItemMinDefault = 0
export const notebooksCreateBodyAppPublishedOneBlocksItemMaxDefault = 100
export const notebooksCreateBodyAppPublishedOneBlocksItemStepDefault = 1
export const notebooksCreateBodyAppPublishedOneBlocksItemStepMin = 0.000001

export const notebooksCreateBodyAppPublishedOneBlocksItemDisplayDefault = `output`
export const notebooksCreateBodyAppRevisionMin = 0

export const NotebooksCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod
        .unknown()
        .optional()
        .describe(
            'Notebook content as a ProseMirror JSON document. On create, the server stores it as a markdown notebook: one ph-markdown-notebook node that holds the converted markdown.'
        ),
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
                            "The variable's current value. A 'date' is an absolute date or datetime in ISO 8601 form ('2025-01-31', '2025-01-31T09:00:00Z'); relative expressions such as '-7d' are rejected."
                        ),
                })
                .describe("One notebook-level variable. Shared by the notebook's own `variables` field and a run body.")
        )
        .optional()
        .describe(
            'Notebook-level variables, in display order. A SQL cell reads one as a `{name}` placeholder and a Python cell as a global. Names must be unique.'
        ),
    app_draft: zod
        .union([
            zod.object({
                title: zod
                    .string()
                    .max(notebooksCreateBodyAppDraftOneTitleMax)
                    .default(notebooksCreateBodyAppDraftOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksCreateBodyAppDraftOneDescriptionMax)
                    .default(notebooksCreateBodyAppDraftOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksCreateBodyAppDraftOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksCreateBodyAppDraftOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksCreateBodyAppDraftOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksCreateBodyAppDraftOneBlocksItemIdMax)
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
                                .max(notebooksCreateBodyAppDraftOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksCreateBodyAppDraftOneBlocksItemTitleMax)
                                .default(notebooksCreateBodyAppDraftOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksCreateBodyAppDraftOneBlocksItemWidthMax)
                                .default(notebooksCreateBodyAppDraftOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksCreateBodyAppDraftOneBlocksItemNodeIdMax)
                                .default(notebooksCreateBodyAppDraftOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksCreateBodyAppDraftOneBlocksItemTextMax)
                                .default(notebooksCreateBodyAppDraftOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksCreateBodyAppDraftOneBlocksItemVariableMax)
                                .default(notebooksCreateBodyAppDraftOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksCreateBodyAppDraftOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(zod.string().max(notebooksCreateBodyAppDraftOneBlocksItemOptionsItemMax))
                                .max(notebooksCreateBodyAppDraftOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksCreateBodyAppDraftOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksCreateBodyAppDraftOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksCreateBodyAppDraftOneBlocksItemStepMin)
                                .default(notebooksCreateBodyAppDraftOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksCreateBodyAppDraftOneBlocksItemDisplayDefault)
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
                    .max(notebooksCreateBodyAppPublishedOneTitleMax)
                    .default(notebooksCreateBodyAppPublishedOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksCreateBodyAppPublishedOneDescriptionMax)
                    .default(notebooksCreateBodyAppPublishedOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksCreateBodyAppPublishedOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksCreateBodyAppPublishedOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksCreateBodyAppPublishedOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksCreateBodyAppPublishedOneBlocksItemIdMax)
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
                                .max(notebooksCreateBodyAppPublishedOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksCreateBodyAppPublishedOneBlocksItemTitleMax)
                                .default(notebooksCreateBodyAppPublishedOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksCreateBodyAppPublishedOneBlocksItemWidthMax)
                                .default(notebooksCreateBodyAppPublishedOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksCreateBodyAppPublishedOneBlocksItemNodeIdMax)
                                .default(notebooksCreateBodyAppPublishedOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksCreateBodyAppPublishedOneBlocksItemTextMax)
                                .default(notebooksCreateBodyAppPublishedOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksCreateBodyAppPublishedOneBlocksItemVariableMax)
                                .default(notebooksCreateBodyAppPublishedOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksCreateBodyAppPublishedOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(zod.string().max(notebooksCreateBodyAppPublishedOneBlocksItemOptionsItemMax))
                                .max(notebooksCreateBodyAppPublishedOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksCreateBodyAppPublishedOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksCreateBodyAppPublishedOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksCreateBodyAppPublishedOneBlocksItemStepMin)
                                .default(notebooksCreateBodyAppPublishedOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksCreateBodyAppPublishedOneBlocksItemDisplayDefault)
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
        .describe(
            'Published app layout. Cell content and results remain linked to the notebook. Null unpublishes the app.'
        ),
    app_revision: zod
        .number()
        .min(notebooksCreateBodyAppRevisionMin)
        .optional()
        .describe('Current app revision. Required when saving or publishing a layout; stale revisions return 409.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksUpdateBodyTitleMax = 256

export const notebooksUpdateBodyVersionMin = -2147483648
export const notebooksUpdateBodyVersionMax = 2147483647

export const notebooksUpdateBodyVariablesItemNameMax = 200

export const notebooksUpdateBodyAppDraftOneTitleDefault = ``
export const notebooksUpdateBodyAppDraftOneTitleMax = 256

export const notebooksUpdateBodyAppDraftOneDescriptionDefault = ``
export const notebooksUpdateBodyAppDraftOneDescriptionMax = 2000

export const notebooksUpdateBodyAppDraftOneFullWidthDefault = false
export const notebooksUpdateBodyAppDraftOneTabsItemIdMax = 80

export const notebooksUpdateBodyAppDraftOneTabsItemTitleMax = 80

export const notebooksUpdateBodyAppDraftOneBlocksItemIdMax = 80

export const notebooksUpdateBodyAppDraftOneBlocksItemTabIdMax = 80

export const notebooksUpdateBodyAppDraftOneBlocksItemTitleDefault = ``
export const notebooksUpdateBodyAppDraftOneBlocksItemTitleMax = 256

export const notebooksUpdateBodyAppDraftOneBlocksItemWidthDefault = 12
export const notebooksUpdateBodyAppDraftOneBlocksItemWidthMax = 12

export const notebooksUpdateBodyAppDraftOneBlocksItemNodeIdDefault = ``
export const notebooksUpdateBodyAppDraftOneBlocksItemNodeIdMax = 160

export const notebooksUpdateBodyAppDraftOneBlocksItemTextDefault = ``
export const notebooksUpdateBodyAppDraftOneBlocksItemTextMax = 20000

export const notebooksUpdateBodyAppDraftOneBlocksItemVariableDefault = ``
export const notebooksUpdateBodyAppDraftOneBlocksItemVariableMax = 80

export const notebooksUpdateBodyAppDraftOneBlocksItemInputKindDefault = `auto`
export const notebooksUpdateBodyAppDraftOneBlocksItemOptionsItemMax = 1000

export const notebooksUpdateBodyAppDraftOneBlocksItemOptionsMax = 100

export const notebooksUpdateBodyAppDraftOneBlocksItemMinDefault = 0
export const notebooksUpdateBodyAppDraftOneBlocksItemMaxDefault = 100
export const notebooksUpdateBodyAppDraftOneBlocksItemStepDefault = 1
export const notebooksUpdateBodyAppDraftOneBlocksItemStepMin = 0.000001

export const notebooksUpdateBodyAppDraftOneBlocksItemDisplayDefault = `output`
export const notebooksUpdateBodyAppPublishedOneTitleDefault = ``
export const notebooksUpdateBodyAppPublishedOneTitleMax = 256

export const notebooksUpdateBodyAppPublishedOneDescriptionDefault = ``
export const notebooksUpdateBodyAppPublishedOneDescriptionMax = 2000

export const notebooksUpdateBodyAppPublishedOneFullWidthDefault = false
export const notebooksUpdateBodyAppPublishedOneTabsItemIdMax = 80

export const notebooksUpdateBodyAppPublishedOneTabsItemTitleMax = 80

export const notebooksUpdateBodyAppPublishedOneBlocksItemIdMax = 80

export const notebooksUpdateBodyAppPublishedOneBlocksItemTabIdMax = 80

export const notebooksUpdateBodyAppPublishedOneBlocksItemTitleDefault = ``
export const notebooksUpdateBodyAppPublishedOneBlocksItemTitleMax = 256

export const notebooksUpdateBodyAppPublishedOneBlocksItemWidthDefault = 12
export const notebooksUpdateBodyAppPublishedOneBlocksItemWidthMax = 12

export const notebooksUpdateBodyAppPublishedOneBlocksItemNodeIdDefault = ``
export const notebooksUpdateBodyAppPublishedOneBlocksItemNodeIdMax = 160

export const notebooksUpdateBodyAppPublishedOneBlocksItemTextDefault = ``
export const notebooksUpdateBodyAppPublishedOneBlocksItemTextMax = 20000

export const notebooksUpdateBodyAppPublishedOneBlocksItemVariableDefault = ``
export const notebooksUpdateBodyAppPublishedOneBlocksItemVariableMax = 80

export const notebooksUpdateBodyAppPublishedOneBlocksItemInputKindDefault = `auto`
export const notebooksUpdateBodyAppPublishedOneBlocksItemOptionsItemMax = 1000

export const notebooksUpdateBodyAppPublishedOneBlocksItemOptionsMax = 100

export const notebooksUpdateBodyAppPublishedOneBlocksItemMinDefault = 0
export const notebooksUpdateBodyAppPublishedOneBlocksItemMaxDefault = 100
export const notebooksUpdateBodyAppPublishedOneBlocksItemStepDefault = 1
export const notebooksUpdateBodyAppPublishedOneBlocksItemStepMin = 0.000001

export const notebooksUpdateBodyAppPublishedOneBlocksItemDisplayDefault = `output`
export const notebooksUpdateBodyAppRevisionMin = 0

export const NotebooksUpdateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksUpdateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod
        .unknown()
        .optional()
        .describe(
            'Notebook content as a ProseMirror JSON document. On create, the server stores it as a markdown notebook: one ph-markdown-notebook node that holds the converted markdown.'
        ),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksUpdateBodyVersionMin)
        .max(notebooksUpdateBodyVersionMax)
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
                        .max(notebooksUpdateBodyVariablesItemNameMax)
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
    app_draft: zod
        .union([
            zod.object({
                title: zod
                    .string()
                    .max(notebooksUpdateBodyAppDraftOneTitleMax)
                    .default(notebooksUpdateBodyAppDraftOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksUpdateBodyAppDraftOneDescriptionMax)
                    .default(notebooksUpdateBodyAppDraftOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksUpdateBodyAppDraftOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksUpdateBodyAppDraftOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksUpdateBodyAppDraftOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksUpdateBodyAppDraftOneBlocksItemIdMax)
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
                                .max(notebooksUpdateBodyAppDraftOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksUpdateBodyAppDraftOneBlocksItemTitleMax)
                                .default(notebooksUpdateBodyAppDraftOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksUpdateBodyAppDraftOneBlocksItemWidthMax)
                                .default(notebooksUpdateBodyAppDraftOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksUpdateBodyAppDraftOneBlocksItemNodeIdMax)
                                .default(notebooksUpdateBodyAppDraftOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksUpdateBodyAppDraftOneBlocksItemTextMax)
                                .default(notebooksUpdateBodyAppDraftOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksUpdateBodyAppDraftOneBlocksItemVariableMax)
                                .default(notebooksUpdateBodyAppDraftOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksUpdateBodyAppDraftOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(zod.string().max(notebooksUpdateBodyAppDraftOneBlocksItemOptionsItemMax))
                                .max(notebooksUpdateBodyAppDraftOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksUpdateBodyAppDraftOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksUpdateBodyAppDraftOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksUpdateBodyAppDraftOneBlocksItemStepMin)
                                .default(notebooksUpdateBodyAppDraftOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksUpdateBodyAppDraftOneBlocksItemDisplayDefault)
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
                    .max(notebooksUpdateBodyAppPublishedOneTitleMax)
                    .default(notebooksUpdateBodyAppPublishedOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksUpdateBodyAppPublishedOneDescriptionMax)
                    .default(notebooksUpdateBodyAppPublishedOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksUpdateBodyAppPublishedOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksUpdateBodyAppPublishedOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksUpdateBodyAppPublishedOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksUpdateBodyAppPublishedOneBlocksItemIdMax)
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
                                .max(notebooksUpdateBodyAppPublishedOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksUpdateBodyAppPublishedOneBlocksItemTitleMax)
                                .default(notebooksUpdateBodyAppPublishedOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksUpdateBodyAppPublishedOneBlocksItemWidthMax)
                                .default(notebooksUpdateBodyAppPublishedOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksUpdateBodyAppPublishedOneBlocksItemNodeIdMax)
                                .default(notebooksUpdateBodyAppPublishedOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksUpdateBodyAppPublishedOneBlocksItemTextMax)
                                .default(notebooksUpdateBodyAppPublishedOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksUpdateBodyAppPublishedOneBlocksItemVariableMax)
                                .default(notebooksUpdateBodyAppPublishedOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksUpdateBodyAppPublishedOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(zod.string().max(notebooksUpdateBodyAppPublishedOneBlocksItemOptionsItemMax))
                                .max(notebooksUpdateBodyAppPublishedOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksUpdateBodyAppPublishedOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksUpdateBodyAppPublishedOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksUpdateBodyAppPublishedOneBlocksItemStepMin)
                                .default(notebooksUpdateBodyAppPublishedOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksUpdateBodyAppPublishedOneBlocksItemDisplayDefault)
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
        .describe(
            'Published app layout. Cell content and results remain linked to the notebook. Null unpublishes the app.'
        ),
    app_revision: zod
        .number()
        .min(notebooksUpdateBodyAppRevisionMin)
        .optional()
        .describe('Current app revision. Required when saving or publishing a layout; stale revisions return 409.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
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

export const NotebooksPartialUpdateBody = /* @__PURE__ */ zod.object({
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
        .describe(
            'Published app layout. Cell content and results remain linked to the notebook. Null unpublishes the app.'
        ),
    app_revision: zod
        .number()
        .min(notebooksPartialUpdateBodyAppRevisionMin)
        .optional()
        .describe('Current app revision. Required when saving or publishing a layout; stale revisions return 409.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksCollabMarkdownSaveCreateBodyTextContentDefault = ``
export const notebooksCollabMarkdownSaveCreateBodyCursorOneHeadMin = 0

export const notebooksCollabMarkdownSaveCreateBodyCursorOneNodeIndexMin = 0

export const notebooksCollabMarkdownSaveCreateBodyCursorOneOffsetMin = 0

export const notebooksCollabMarkdownSaveCreateBodyCursorOneListItemIndexMin = 0

export const NotebooksCollabMarkdownSaveCreateBody = /* @__PURE__ */ zod.object({
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
        .default(notebooksCollabMarkdownSaveCreateBodyTextContentDefault)
        .describe('Plain text for search indexing.'),
    title: zod.string().optional().describe('Updated notebook title.'),
    cursor: zod
        .object({
            head: zod
                .number()
                .min(notebooksCollabMarkdownSaveCreateBodyCursorOneHeadMin)
                .optional()
                .describe('ProseMirror selection head position (rich v1 notebooks).'),
            node_index: zod
                .number()
                .min(notebooksCollabMarkdownSaveCreateBodyCursorOneNodeIndexMin)
                .optional()
                .describe("Index of the caret's block node in the markdown notebook document (markdown notebooks)."),
            offset: zod
                .number()
                .min(notebooksCollabMarkdownSaveCreateBodyCursorOneOffsetMin)
                .optional()
                .describe('Caret offset in the plain text of the focused editable element, in UTF-16 code units.'),
            list_item_index: zod
                .number()
                .min(notebooksCollabMarkdownSaveCreateBodyCursorOneListItemIndexMin)
                .optional()
                .describe('Index of the focused list item when the caret is inside a list block.'),
        })
        .optional()
        .describe(
            "The author's caret in the saved markdown, broadcast with the update so other clients can move the author's remote caret together with the text change."
        ),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksCollabPresenceCreateBodyClientIdMax = 200

export const notebooksCollabPresenceCreateBodyVersionMin = 0

export const notebooksCollabPresenceCreateBodyCursorOneHeadMin = 0

export const notebooksCollabPresenceCreateBodyCursorOneNodeIndexMin = 0

export const notebooksCollabPresenceCreateBodyCursorOneOffsetMin = 0

export const notebooksCollabPresenceCreateBodyCursorOneListItemIndexMin = 0

export const NotebooksCollabPresenceCreateBody = /* @__PURE__ */ zod.object({
    client_id: zod
        .string()
        .max(notebooksCollabPresenceCreateBodyClientIdMax)
        .describe('Unique identifier for the client session, used to skip self-echo on the update stream.'),
    version: zod
        .number()
        .min(notebooksCollabPresenceCreateBodyVersionMin)
        .describe('The notebook version the cursor position is relative to.'),
    cursor: zod
        .object({
            head: zod
                .number()
                .min(notebooksCollabPresenceCreateBodyCursorOneHeadMin)
                .optional()
                .describe('ProseMirror selection head position (rich v1 notebooks).'),
            node_index: zod
                .number()
                .min(notebooksCollabPresenceCreateBodyCursorOneNodeIndexMin)
                .optional()
                .describe("Index of the caret's block node in the markdown notebook document (markdown notebooks)."),
            offset: zod
                .number()
                .min(notebooksCollabPresenceCreateBodyCursorOneOffsetMin)
                .optional()
                .describe('Caret offset in the plain text of the focused editable element, in UTF-16 code units.'),
            list_item_index: zod
                .number()
                .min(notebooksCollabPresenceCreateBodyCursorOneListItemIndexMin)
                .optional()
                .describe('Index of the focused list item when the caret is inside a list block.'),
        })
        .describe("The caller's caret position, broadcast to other clients on this notebook's collab stream."),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksCollabSaveCreateBodyTextContentDefault = ``

export const NotebooksCollabSaveCreateBody = /* @__PURE__ */ zod.object({
    client_id: zod.string().describe('Unique identifier for the client session.'),
    version: zod.number().describe("The collab version the client's steps are based on."),
    steps: zod.array(zod.unknown()).describe('List of ProseMirror step JSON objects to apply.'),
    content: zod.unknown().describe('The resulting ProseMirror document after applying the steps locally.'),
    text_content: zod
        .string()
        .default(notebooksCollabSaveCreateBodyTextContentDefault)
        .describe('Plain text for search indexing.'),
    title: zod.string().optional().describe('Updated notebook title.'),
    cursor_head: zod.number().nullish().describe('ProseMirror cursor head position after applying steps.'),
})

/**
 * Completions for the cursor position in a Python cell, from the notebook's running kernel. Returns no matches when no kernel is running or the kernel is busy, and never starts one.
 */
export const notebooksKernelCompleteCreateBodyCodeMax = 100000

export const notebooksKernelCompleteCreateBodyCursorPosMin = 0

export const NotebooksKernelCompleteCreateBody = /* @__PURE__ */ zod.object({
    code: zod
        .string()
        .max(notebooksKernelCompleteCreateBodyCodeMax)
        .describe('The full source of the cell being edited.'),
    cursor_pos: zod
        .number()
        .min(notebooksKernelCompleteCreateBodyCursorPosMin)
        .describe('Character offset of the cursor in `code`, counting from 0.'),
})

/**
 * Set the notebook's kernel compute configuration. Applies at sandbox provision time: a currently running kernel keeps its resources until restarted.
 */
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
        .describe(
            'Maximum lifetime of the sandbox kernel in seconds. It shuts down this long after it starts, even while in use. A running kernel keeps its current lifetime until it restarts.'
        ),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelExecuteCreateBodyTitleMax = 256

export const notebooksKernelExecuteCreateBodyVersionMin = -2147483648
export const notebooksKernelExecuteCreateBodyVersionMax = 2147483647

export const notebooksKernelExecuteCreateBodyVariablesItemNameMax = 200

export const notebooksKernelExecuteCreateBodyAppDraftOneTitleDefault = ``
export const notebooksKernelExecuteCreateBodyAppDraftOneTitleMax = 256

export const notebooksKernelExecuteCreateBodyAppDraftOneDescriptionDefault = ``
export const notebooksKernelExecuteCreateBodyAppDraftOneDescriptionMax = 2000

export const notebooksKernelExecuteCreateBodyAppDraftOneFullWidthDefault = false
export const notebooksKernelExecuteCreateBodyAppDraftOneTabsItemIdMax = 80

export const notebooksKernelExecuteCreateBodyAppDraftOneTabsItemTitleMax = 80

export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemIdMax = 80

export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemTabIdMax = 80

export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemTitleDefault = ``
export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemTitleMax = 256

export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemWidthDefault = 12
export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemWidthMax = 12

export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemNodeIdDefault = ``
export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemNodeIdMax = 160

export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemTextDefault = ``
export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemTextMax = 20000

export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemVariableDefault = ``
export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemVariableMax = 80

export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemInputKindDefault = `auto`
export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemOptionsItemMax = 1000

export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemOptionsMax = 100

export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemMinDefault = 0
export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemMaxDefault = 100
export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemStepDefault = 1
export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemStepMin = 0.000001

export const notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemDisplayDefault = `output`
export const notebooksKernelExecuteCreateBodyAppPublishedOneTitleDefault = ``
export const notebooksKernelExecuteCreateBodyAppPublishedOneTitleMax = 256

export const notebooksKernelExecuteCreateBodyAppPublishedOneDescriptionDefault = ``
export const notebooksKernelExecuteCreateBodyAppPublishedOneDescriptionMax = 2000

export const notebooksKernelExecuteCreateBodyAppPublishedOneFullWidthDefault = false
export const notebooksKernelExecuteCreateBodyAppPublishedOneTabsItemIdMax = 80

export const notebooksKernelExecuteCreateBodyAppPublishedOneTabsItemTitleMax = 80

export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemIdMax = 80

export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemTabIdMax = 80

export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemTitleDefault = ``
export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemTitleMax = 256

export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemWidthDefault = 12
export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemWidthMax = 12

export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemNodeIdDefault = ``
export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemNodeIdMax = 160

export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemTextDefault = ``
export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemTextMax = 20000

export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemVariableDefault = ``
export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemVariableMax = 80

export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemInputKindDefault = `auto`
export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemOptionsItemMax = 1000

export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemOptionsMax = 100

export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemMinDefault = 0
export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemMaxDefault = 100
export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemStepDefault = 1
export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemStepMin = 0.000001

export const notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemDisplayDefault = `output`
export const notebooksKernelExecuteCreateBodyAppRevisionMin = 0

export const NotebooksKernelExecuteCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelExecuteCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod
        .unknown()
        .optional()
        .describe(
            'Notebook content as a ProseMirror JSON document. On create, the server stores it as a markdown notebook: one ph-markdown-notebook node that holds the converted markdown.'
        ),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelExecuteCreateBodyVersionMin)
        .max(notebooksKernelExecuteCreateBodyVersionMax)
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
                        .max(notebooksKernelExecuteCreateBodyVariablesItemNameMax)
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
    app_draft: zod
        .union([
            zod.object({
                title: zod
                    .string()
                    .max(notebooksKernelExecuteCreateBodyAppDraftOneTitleMax)
                    .default(notebooksKernelExecuteCreateBodyAppDraftOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksKernelExecuteCreateBodyAppDraftOneDescriptionMax)
                    .default(notebooksKernelExecuteCreateBodyAppDraftOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksKernelExecuteCreateBodyAppDraftOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppDraftOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppDraftOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemIdMax)
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
                                .max(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemTitleMax)
                                .default(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemWidthMax)
                                .default(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemNodeIdMax)
                                .default(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemTextMax)
                                .default(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemVariableMax)
                                .default(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(
                                    zod
                                        .string()
                                        .max(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemOptionsItemMax)
                                )
                                .max(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemStepMin)
                                .default(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksKernelExecuteCreateBodyAppDraftOneBlocksItemDisplayDefault)
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
                    .max(notebooksKernelExecuteCreateBodyAppPublishedOneTitleMax)
                    .default(notebooksKernelExecuteCreateBodyAppPublishedOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksKernelExecuteCreateBodyAppPublishedOneDescriptionMax)
                    .default(notebooksKernelExecuteCreateBodyAppPublishedOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksKernelExecuteCreateBodyAppPublishedOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppPublishedOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppPublishedOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemIdMax)
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
                                .max(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemTitleMax)
                                .default(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemWidthMax)
                                .default(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemNodeIdMax)
                                .default(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemTextMax)
                                .default(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemVariableMax)
                                .default(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(
                                    zod
                                        .string()
                                        .max(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemOptionsItemMax)
                                )
                                .max(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemStepMin)
                                .default(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksKernelExecuteCreateBodyAppPublishedOneBlocksItemDisplayDefault)
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
        .describe(
            'Published app layout. Cell content and results remain linked to the notebook. Null unpublishes the app.'
        ),
    app_revision: zod
        .number()
        .min(notebooksKernelExecuteCreateBodyAppRevisionMin)
        .optional()
        .describe('Current app revision. Required when saving or publishing a layout; stale revisions return 409.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The signature and docstring of the name at the cursor in a Python cell, from the notebook's running kernel. Returns found=false when no kernel is running or the kernel is busy.
 */
export const notebooksKernelInspectCreateBodyCodeMax = 100000

export const notebooksKernelInspectCreateBodyCursorPosMin = 0

export const notebooksKernelInspectCreateBodyDetailLevelDefault = 0
export const notebooksKernelInspectCreateBodyDetailLevelMin = 0
export const notebooksKernelInspectCreateBodyDetailLevelMax = 1

export const NotebooksKernelInspectCreateBody = /* @__PURE__ */ zod.object({
    code: zod
        .string()
        .max(notebooksKernelInspectCreateBodyCodeMax)
        .describe('The full source of the cell being edited.'),
    cursor_pos: zod
        .number()
        .min(notebooksKernelInspectCreateBodyCursorPosMin)
        .describe('Character offset of the cursor in `code`, counting from 0.'),
    detail_level: zod
        .number()
        .min(notebooksKernelInspectCreateBodyDetailLevelMin)
        .max(notebooksKernelInspectCreateBodyDetailLevelMax)
        .default(notebooksKernelInspectCreateBodyDetailLevelDefault)
        .describe('0 for the signature and docstring, 1 to add the source when the kernel can find it.'),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelRestartCreateBodyTitleMax = 256

export const notebooksKernelRestartCreateBodyVersionMin = -2147483648
export const notebooksKernelRestartCreateBodyVersionMax = 2147483647

export const notebooksKernelRestartCreateBodyVariablesItemNameMax = 200

export const notebooksKernelRestartCreateBodyAppDraftOneTitleDefault = ``
export const notebooksKernelRestartCreateBodyAppDraftOneTitleMax = 256

export const notebooksKernelRestartCreateBodyAppDraftOneDescriptionDefault = ``
export const notebooksKernelRestartCreateBodyAppDraftOneDescriptionMax = 2000

export const notebooksKernelRestartCreateBodyAppDraftOneFullWidthDefault = false
export const notebooksKernelRestartCreateBodyAppDraftOneTabsItemIdMax = 80

export const notebooksKernelRestartCreateBodyAppDraftOneTabsItemTitleMax = 80

export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemIdMax = 80

export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemTabIdMax = 80

export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemTitleDefault = ``
export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemTitleMax = 256

export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemWidthDefault = 12
export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemWidthMax = 12

export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemNodeIdDefault = ``
export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemNodeIdMax = 160

export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemTextDefault = ``
export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemTextMax = 20000

export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemVariableDefault = ``
export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemVariableMax = 80

export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemInputKindDefault = `auto`
export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemOptionsItemMax = 1000

export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemOptionsMax = 100

export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemMinDefault = 0
export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemMaxDefault = 100
export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemStepDefault = 1
export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemStepMin = 0.000001

export const notebooksKernelRestartCreateBodyAppDraftOneBlocksItemDisplayDefault = `output`
export const notebooksKernelRestartCreateBodyAppPublishedOneTitleDefault = ``
export const notebooksKernelRestartCreateBodyAppPublishedOneTitleMax = 256

export const notebooksKernelRestartCreateBodyAppPublishedOneDescriptionDefault = ``
export const notebooksKernelRestartCreateBodyAppPublishedOneDescriptionMax = 2000

export const notebooksKernelRestartCreateBodyAppPublishedOneFullWidthDefault = false
export const notebooksKernelRestartCreateBodyAppPublishedOneTabsItemIdMax = 80

export const notebooksKernelRestartCreateBodyAppPublishedOneTabsItemTitleMax = 80

export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemIdMax = 80

export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemTabIdMax = 80

export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemTitleDefault = ``
export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemTitleMax = 256

export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemWidthDefault = 12
export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemWidthMax = 12

export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemNodeIdDefault = ``
export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemNodeIdMax = 160

export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemTextDefault = ``
export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemTextMax = 20000

export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemVariableDefault = ``
export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemVariableMax = 80

export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemInputKindDefault = `auto`
export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemOptionsItemMax = 1000

export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemOptionsMax = 100

export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemMinDefault = 0
export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemMaxDefault = 100
export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemStepDefault = 1
export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemStepMin = 0.000001

export const notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemDisplayDefault = `output`
export const notebooksKernelRestartCreateBodyAppRevisionMin = 0

export const NotebooksKernelRestartCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelRestartCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod
        .unknown()
        .optional()
        .describe(
            'Notebook content as a ProseMirror JSON document. On create, the server stores it as a markdown notebook: one ph-markdown-notebook node that holds the converted markdown.'
        ),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelRestartCreateBodyVersionMin)
        .max(notebooksKernelRestartCreateBodyVersionMax)
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
                        .max(notebooksKernelRestartCreateBodyVariablesItemNameMax)
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
    app_draft: zod
        .union([
            zod.object({
                title: zod
                    .string()
                    .max(notebooksKernelRestartCreateBodyAppDraftOneTitleMax)
                    .default(notebooksKernelRestartCreateBodyAppDraftOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksKernelRestartCreateBodyAppDraftOneDescriptionMax)
                    .default(notebooksKernelRestartCreateBodyAppDraftOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksKernelRestartCreateBodyAppDraftOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppDraftOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppDraftOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemIdMax)
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
                                .max(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemTitleMax)
                                .default(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemWidthMax)
                                .default(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemNodeIdMax)
                                .default(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemTextMax)
                                .default(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemVariableMax)
                                .default(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(
                                    zod
                                        .string()
                                        .max(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemOptionsItemMax)
                                )
                                .max(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemStepMin)
                                .default(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksKernelRestartCreateBodyAppDraftOneBlocksItemDisplayDefault)
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
                    .max(notebooksKernelRestartCreateBodyAppPublishedOneTitleMax)
                    .default(notebooksKernelRestartCreateBodyAppPublishedOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksKernelRestartCreateBodyAppPublishedOneDescriptionMax)
                    .default(notebooksKernelRestartCreateBodyAppPublishedOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksKernelRestartCreateBodyAppPublishedOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppPublishedOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppPublishedOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemIdMax)
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
                                .max(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemTitleMax)
                                .default(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemWidthMax)
                                .default(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemNodeIdMax)
                                .default(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemTextMax)
                                .default(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemVariableMax)
                                .default(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(
                                    zod
                                        .string()
                                        .max(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemOptionsItemMax)
                                )
                                .max(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemStepMin)
                                .default(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksKernelRestartCreateBodyAppPublishedOneBlocksItemDisplayDefault)
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
        .describe(
            'Published app layout. Cell content and results remain linked to the notebook. Null unpublishes the app.'
        ),
    app_revision: zod
        .number()
        .min(notebooksKernelRestartCreateBodyAppRevisionMin)
        .optional()
        .describe('Current app revision. Required when saving or publishing a layout; stale revisions return 409.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelStartCreateBodyTitleMax = 256

export const notebooksKernelStartCreateBodyVersionMin = -2147483648
export const notebooksKernelStartCreateBodyVersionMax = 2147483647

export const notebooksKernelStartCreateBodyVariablesItemNameMax = 200

export const notebooksKernelStartCreateBodyAppDraftOneTitleDefault = ``
export const notebooksKernelStartCreateBodyAppDraftOneTitleMax = 256

export const notebooksKernelStartCreateBodyAppDraftOneDescriptionDefault = ``
export const notebooksKernelStartCreateBodyAppDraftOneDescriptionMax = 2000

export const notebooksKernelStartCreateBodyAppDraftOneFullWidthDefault = false
export const notebooksKernelStartCreateBodyAppDraftOneTabsItemIdMax = 80

export const notebooksKernelStartCreateBodyAppDraftOneTabsItemTitleMax = 80

export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemIdMax = 80

export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemTabIdMax = 80

export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemTitleDefault = ``
export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemTitleMax = 256

export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemWidthDefault = 12
export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemWidthMax = 12

export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemNodeIdDefault = ``
export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemNodeIdMax = 160

export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemTextDefault = ``
export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemTextMax = 20000

export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemVariableDefault = ``
export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemVariableMax = 80

export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemInputKindDefault = `auto`
export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemOptionsItemMax = 1000

export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemOptionsMax = 100

export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemMinDefault = 0
export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemMaxDefault = 100
export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemStepDefault = 1
export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemStepMin = 0.000001

export const notebooksKernelStartCreateBodyAppDraftOneBlocksItemDisplayDefault = `output`
export const notebooksKernelStartCreateBodyAppPublishedOneTitleDefault = ``
export const notebooksKernelStartCreateBodyAppPublishedOneTitleMax = 256

export const notebooksKernelStartCreateBodyAppPublishedOneDescriptionDefault = ``
export const notebooksKernelStartCreateBodyAppPublishedOneDescriptionMax = 2000

export const notebooksKernelStartCreateBodyAppPublishedOneFullWidthDefault = false
export const notebooksKernelStartCreateBodyAppPublishedOneTabsItemIdMax = 80

export const notebooksKernelStartCreateBodyAppPublishedOneTabsItemTitleMax = 80

export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemIdMax = 80

export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemTabIdMax = 80

export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemTitleDefault = ``
export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemTitleMax = 256

export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemWidthDefault = 12
export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemWidthMax = 12

export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemNodeIdDefault = ``
export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemNodeIdMax = 160

export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemTextDefault = ``
export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemTextMax = 20000

export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemVariableDefault = ``
export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemVariableMax = 80

export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemInputKindDefault = `auto`
export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemOptionsItemMax = 1000

export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemOptionsMax = 100

export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemMinDefault = 0
export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemMaxDefault = 100
export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemStepDefault = 1
export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemStepMin = 0.000001

export const notebooksKernelStartCreateBodyAppPublishedOneBlocksItemDisplayDefault = `output`
export const notebooksKernelStartCreateBodyAppRevisionMin = 0

export const NotebooksKernelStartCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelStartCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod
        .unknown()
        .optional()
        .describe(
            'Notebook content as a ProseMirror JSON document. On create, the server stores it as a markdown notebook: one ph-markdown-notebook node that holds the converted markdown.'
        ),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelStartCreateBodyVersionMin)
        .max(notebooksKernelStartCreateBodyVersionMax)
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
                        .max(notebooksKernelStartCreateBodyVariablesItemNameMax)
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
    app_draft: zod
        .union([
            zod.object({
                title: zod
                    .string()
                    .max(notebooksKernelStartCreateBodyAppDraftOneTitleMax)
                    .default(notebooksKernelStartCreateBodyAppDraftOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksKernelStartCreateBodyAppDraftOneDescriptionMax)
                    .default(notebooksKernelStartCreateBodyAppDraftOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksKernelStartCreateBodyAppDraftOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppDraftOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppDraftOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppDraftOneBlocksItemIdMax)
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
                                .max(notebooksKernelStartCreateBodyAppDraftOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppDraftOneBlocksItemTitleMax)
                                .default(notebooksKernelStartCreateBodyAppDraftOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksKernelStartCreateBodyAppDraftOneBlocksItemWidthMax)
                                .default(notebooksKernelStartCreateBodyAppDraftOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppDraftOneBlocksItemNodeIdMax)
                                .default(notebooksKernelStartCreateBodyAppDraftOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppDraftOneBlocksItemTextMax)
                                .default(notebooksKernelStartCreateBodyAppDraftOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppDraftOneBlocksItemVariableMax)
                                .default(notebooksKernelStartCreateBodyAppDraftOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksKernelStartCreateBodyAppDraftOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(
                                    zod.string().max(notebooksKernelStartCreateBodyAppDraftOneBlocksItemOptionsItemMax)
                                )
                                .max(notebooksKernelStartCreateBodyAppDraftOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksKernelStartCreateBodyAppDraftOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksKernelStartCreateBodyAppDraftOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksKernelStartCreateBodyAppDraftOneBlocksItemStepMin)
                                .default(notebooksKernelStartCreateBodyAppDraftOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksKernelStartCreateBodyAppDraftOneBlocksItemDisplayDefault)
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
                    .max(notebooksKernelStartCreateBodyAppPublishedOneTitleMax)
                    .default(notebooksKernelStartCreateBodyAppPublishedOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksKernelStartCreateBodyAppPublishedOneDescriptionMax)
                    .default(notebooksKernelStartCreateBodyAppPublishedOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksKernelStartCreateBodyAppPublishedOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppPublishedOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppPublishedOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemIdMax)
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
                                .max(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemTitleMax)
                                .default(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemWidthMax)
                                .default(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemNodeIdMax)
                                .default(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemTextMax)
                                .default(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemVariableMax)
                                .default(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(
                                    zod
                                        .string()
                                        .max(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemOptionsItemMax)
                                )
                                .max(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemStepMin)
                                .default(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksKernelStartCreateBodyAppPublishedOneBlocksItemDisplayDefault)
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
        .describe(
            'Published app layout. Cell content and results remain linked to the notebook. Null unpublishes the app.'
        ),
    app_revision: zod
        .number()
        .min(notebooksKernelStartCreateBodyAppRevisionMin)
        .optional()
        .describe('Current app revision. Required when saving or publishing a layout; stale revisions return 409.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelStopCreateBodyTitleMax = 256

export const notebooksKernelStopCreateBodyVersionMin = -2147483648
export const notebooksKernelStopCreateBodyVersionMax = 2147483647

export const notebooksKernelStopCreateBodyVariablesItemNameMax = 200

export const notebooksKernelStopCreateBodyAppDraftOneTitleDefault = ``
export const notebooksKernelStopCreateBodyAppDraftOneTitleMax = 256

export const notebooksKernelStopCreateBodyAppDraftOneDescriptionDefault = ``
export const notebooksKernelStopCreateBodyAppDraftOneDescriptionMax = 2000

export const notebooksKernelStopCreateBodyAppDraftOneFullWidthDefault = false
export const notebooksKernelStopCreateBodyAppDraftOneTabsItemIdMax = 80

export const notebooksKernelStopCreateBodyAppDraftOneTabsItemTitleMax = 80

export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemIdMax = 80

export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemTabIdMax = 80

export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemTitleDefault = ``
export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemTitleMax = 256

export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemWidthDefault = 12
export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemWidthMax = 12

export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemNodeIdDefault = ``
export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemNodeIdMax = 160

export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemTextDefault = ``
export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemTextMax = 20000

export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemVariableDefault = ``
export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemVariableMax = 80

export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemInputKindDefault = `auto`
export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemOptionsItemMax = 1000

export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemOptionsMax = 100

export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemMinDefault = 0
export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemMaxDefault = 100
export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemStepDefault = 1
export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemStepMin = 0.000001

export const notebooksKernelStopCreateBodyAppDraftOneBlocksItemDisplayDefault = `output`
export const notebooksKernelStopCreateBodyAppPublishedOneTitleDefault = ``
export const notebooksKernelStopCreateBodyAppPublishedOneTitleMax = 256

export const notebooksKernelStopCreateBodyAppPublishedOneDescriptionDefault = ``
export const notebooksKernelStopCreateBodyAppPublishedOneDescriptionMax = 2000

export const notebooksKernelStopCreateBodyAppPublishedOneFullWidthDefault = false
export const notebooksKernelStopCreateBodyAppPublishedOneTabsItemIdMax = 80

export const notebooksKernelStopCreateBodyAppPublishedOneTabsItemTitleMax = 80

export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemIdMax = 80

export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemTabIdMax = 80

export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemTitleDefault = ``
export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemTitleMax = 256

export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemWidthDefault = 12
export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemWidthMax = 12

export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemNodeIdDefault = ``
export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemNodeIdMax = 160

export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemTextDefault = ``
export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemTextMax = 20000

export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemVariableDefault = ``
export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemVariableMax = 80

export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemInputKindDefault = `auto`
export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemOptionsItemMax = 1000

export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemOptionsMax = 100

export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemMinDefault = 0
export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemMaxDefault = 100
export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemStepDefault = 1
export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemStepMin = 0.000001

export const notebooksKernelStopCreateBodyAppPublishedOneBlocksItemDisplayDefault = `output`
export const notebooksKernelStopCreateBodyAppRevisionMin = 0

export const NotebooksKernelStopCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelStopCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod
        .unknown()
        .optional()
        .describe(
            'Notebook content as a ProseMirror JSON document. On create, the server stores it as a markdown notebook: one ph-markdown-notebook node that holds the converted markdown.'
        ),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelStopCreateBodyVersionMin)
        .max(notebooksKernelStopCreateBodyVersionMax)
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
                        .max(notebooksKernelStopCreateBodyVariablesItemNameMax)
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
    app_draft: zod
        .union([
            zod.object({
                title: zod
                    .string()
                    .max(notebooksKernelStopCreateBodyAppDraftOneTitleMax)
                    .default(notebooksKernelStopCreateBodyAppDraftOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksKernelStopCreateBodyAppDraftOneDescriptionMax)
                    .default(notebooksKernelStopCreateBodyAppDraftOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksKernelStopCreateBodyAppDraftOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppDraftOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppDraftOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppDraftOneBlocksItemIdMax)
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
                                .max(notebooksKernelStopCreateBodyAppDraftOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppDraftOneBlocksItemTitleMax)
                                .default(notebooksKernelStopCreateBodyAppDraftOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksKernelStopCreateBodyAppDraftOneBlocksItemWidthMax)
                                .default(notebooksKernelStopCreateBodyAppDraftOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppDraftOneBlocksItemNodeIdMax)
                                .default(notebooksKernelStopCreateBodyAppDraftOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppDraftOneBlocksItemTextMax)
                                .default(notebooksKernelStopCreateBodyAppDraftOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppDraftOneBlocksItemVariableMax)
                                .default(notebooksKernelStopCreateBodyAppDraftOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksKernelStopCreateBodyAppDraftOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(
                                    zod.string().max(notebooksKernelStopCreateBodyAppDraftOneBlocksItemOptionsItemMax)
                                )
                                .max(notebooksKernelStopCreateBodyAppDraftOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksKernelStopCreateBodyAppDraftOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksKernelStopCreateBodyAppDraftOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksKernelStopCreateBodyAppDraftOneBlocksItemStepMin)
                                .default(notebooksKernelStopCreateBodyAppDraftOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksKernelStopCreateBodyAppDraftOneBlocksItemDisplayDefault)
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
                    .max(notebooksKernelStopCreateBodyAppPublishedOneTitleMax)
                    .default(notebooksKernelStopCreateBodyAppPublishedOneTitleDefault)
                    .describe('App title, falling back to the notebook title.'),
                description: zod
                    .string()
                    .max(notebooksKernelStopCreateBodyAppPublishedOneDescriptionMax)
                    .default(notebooksKernelStopCreateBodyAppPublishedOneDescriptionDefault)
                    .describe('Description displayed below the app title.'),
                full_width: zod
                    .boolean()
                    .default(notebooksKernelStopCreateBodyAppPublishedOneFullWidthDefault)
                    .describe('Use all available width instead of a centered page.'),
                tabs: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppPublishedOneTabsItemIdMax)
                                .describe('Stable tab identifier.'),
                            title: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppPublishedOneTabsItemTitleMax)
                                .describe('Tab label.'),
                        })
                    )
                    .describe('Ordered app tabs.'),
                blocks: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemIdMax)
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
                                .max(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemTabIdMax)
                                .describe('Tab containing this component.'),
                            title: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemTitleMax)
                                .default(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemTitleDefault)
                                .describe('Optional component title.'),
                            width: zod
                                .number()
                                .min(1)
                                .max(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemWidthMax)
                                .default(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemWidthDefault)
                                .describe('Width in a twelve-column grid.'),
                            node_id: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemNodeIdMax)
                                .default(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemNodeIdDefault)
                                .describe('Source notebook cell ID.'),
                            text: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemTextMax)
                                .default(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemTextDefault)
                                .describe('Markdown for a text component.'),
                            variable: zod
                                .string()
                                .max(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemVariableMax)
                                .default(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemVariableDefault)
                                .describe('Notebook variable controlled by an input.'),
                            input_kind: zod
                                .enum(['auto', 'select', 'slider'])
                                .describe('\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider')
                                .default(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemInputKindDefault)
                                .describe(
                                    'Control used for an input.\n\n\* `auto` - Automatic\n\* `select` - Dropdown\n\* `slider` - Slider'
                                ),
                            options: zod
                                .array(
                                    zod
                                        .string()
                                        .max(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemOptionsItemMax)
                                )
                                .max(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemOptionsMax)
                                .optional()
                                .describe('Allowed values for a dropdown.'),
                            min: zod
                                .number()
                                .default(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemMinDefault)
                                .describe('Slider minimum.'),
                            max: zod
                                .number()
                                .default(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemMaxDefault)
                                .describe('Slider maximum.'),
                            step: zod
                                .number()
                                .min(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemStepMin)
                                .default(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemStepDefault)
                                .describe('Slider increment.'),
                            display: zod
                                .enum(['output', 'source', 'both'])
                                .describe('\* `output` - Output\n\* `source` - Source\n\* `both` - Source and output')
                                .default(notebooksKernelStopCreateBodyAppPublishedOneBlocksItemDisplayDefault)
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
        .describe(
            'Published app layout. Cell content and results remain linked to the notebook. Null unpublishes the app.'
        ),
    app_revision: zod
        .number()
        .min(notebooksKernelStopCreateBodyAppRevisionMin)
        .optional()
        .describe('Current app revision. Required when saving or publishing a layout; stale revisions return 409.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * Run every SQL and Python cell of a markdown notebook, in document order, stopping at the first cell that does not finish. Returns as soon as the run starts; poll the run status endpoint until the status is terminal.
 */
export const notebooksRunsCreateBodyIncludePreparedInsightsDefault = false
export const notebooksRunsCreateBodyVariablesItemNameMax = 200

export const NotebooksRunsCreateBody = /* @__PURE__ */ zod.object({
    include_prepared_insights: zod
        .boolean()
        .default(notebooksRunsCreateBodyIncludePreparedInsightsDefault)
        .describe('Include prepared embedded insights when refreshing a dashboard widget.'),
    variables: zod
        .array(
            zod
                .object({
                    name: zod
                        .string()
                        .max(notebooksRunsCreateBodyVariablesItemNameMax)
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
            "Replace the notebook's variables with this list before the run starts, so the results match what the document declares. Omit it to run with the variables already saved."
        ),
})

/**
 * Dispatch an asynchronous run of a notebook SQL or Python cell. Returns a run_id immediately; poll the run result endpoint until the status is terminal. One run at a time per notebook. HogQL runs without a connection or kernel are always available.
 */
export const notebooksSqlV2RunCreateBodyReuseResultsDefault = false
export const notebooksSqlV2RunCreateBodyNodeTypeDefault = `hogql`
export const notebooksSqlV2RunCreateBodyOutputNameDefault = ``
export const notebooksSqlV2RunCreateBodyRefsKindDefault = `hogql`
export const notebooksSqlV2RunCreateBodyVariablesItemNameMax = 200

export const notebooksSqlV2RunCreateBodySendRawQueryDefault = false

export const NotebooksSqlV2RunCreateBody = /* @__PURE__ */ zod.object({
    reuse_results: zod
        .boolean()
        .default(notebooksSqlV2RunCreateBodyReuseResultsDefault)
        .describe(
            "Reuse the requesting user's running or completed HogQL run with the same cell and resolved query from the last hour. Does not apply to token-only callers, kernel runs, or connection runs."
        ),
    node_id: zod.string().describe('ProseMirror node id of the SQLV2 node being run.'),
    node_type: zod
        .enum(['hogql', 'python'])
        .describe('\* `hogql` - hogql\n\* `python` - python')
        .default(notebooksSqlV2RunCreateBodyNodeTypeDefault)
        .describe(
            "Execution kind. 'hogql' is a SQL node — pushed to ClickHouse, or rerouted to the sandbox's DuckDB when it references a local frame; 'python' runs the code in the sandbox kernel, materializing referenced upstream nodes as pandas frames first.\n\n\* `hogql` - hogql\n\* `python` - python"
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
                    .describe('\* `hogql` - hogql\n\* `local` - local')
                    .default(notebooksSqlV2RunCreateBodyRefsKindDefault)
                    .describe(
                        "What the name resolves to: 'hogql' is a SQL node's query definition (resolved to its last-run HogQL); 'local' is a dataframe a Python node bound in the kernel namespace.\n\n\* `hogql` - hogql\n\* `local` - local"
                    ),
            })
        )
        .optional()
        .describe(
            "Available upstream nodes, keyed by dataframe name. A SQL node inlines referenced hogql refs as CTEs — unless it references a local ref, which reroutes the run to the sandbox's DuckDB; a python node materializes the hogql refs its code reads as pandas frames."
        ),
    variables: zod
        .array(
            zod
                .object({
                    name: zod
                        .string()
                        .max(notebooksSqlV2RunCreateBodyVariablesItemNameMax)
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
            'Notebook-level variables in scope for this run. A SQL node has each `{name}` bound to its value before dispatch; a Python node gets them as globals in the kernel namespace. A SQL node reading a `{name}` that is absent here fails the dispatch.'
        ),
    connection_id: zod
        .uuid()
        .nullish()
        .describe(
            "SQL nodes only: id of a direct-query-capable external data source to run against instead of PostHog's ClickHouse. Omit to query PostHog."
        ),
    send_raw_query: zod
        .boolean()
        .default(notebooksSqlV2RunCreateBodySendRawQueryDefault)
        .describe(
            'Send the code to the selected connection verbatim instead of compiling it from HogQL first. Ignored without connection_id, and incompatible with references to other cells.'
        ),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksWidgetSnapshotCreateBodyNodeIdMax = 128

export const NotebooksWidgetSnapshotCreateBody = /* @__PURE__ */ zod.object({
    node_id: zod
        .string()
        .max(notebooksWidgetSnapshotCreateBodyNodeIdMax)
        .describe('Notebook widget node to add to a dashboard.'),
    version_id: zod.uuid().describe('Immutable widget version to keep on the dashboard.'),
    notebook_run_id: zod
        .uuid()
        .optional()
        .describe('Completed whole-notebook run supplying every input after refresh.'),
    previous_snapshot_id: zod
        .uuid()
        .optional()
        .describe('Snapshot being refreshed; its version and input mappings must match.'),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksWidgetSnapshotPublishBodyNodeIdMax = 128

export const notebooksWidgetSnapshotPublishBodyNameDefault = ``
export const notebooksWidgetSnapshotPublishBodyNameMax = 400

export const NotebooksWidgetSnapshotPublishBody = /* @__PURE__ */ zod.object({
    node_id: zod
        .string()
        .max(notebooksWidgetSnapshotPublishBodyNodeIdMax)
        .describe('Notebook widget node to add to a dashboard.'),
    version_id: zod.uuid().describe('Immutable widget version to keep on the dashboard.'),
    notebook_run_id: zod
        .uuid()
        .optional()
        .describe('Completed whole-notebook run supplying every input after refresh.'),
    previous_snapshot_id: zod
        .uuid()
        .optional()
        .describe('Snapshot being refreshed; its version and input mappings must match.'),
    dashboard_id: zod.number().min(1).optional().describe('Dashboard to add the widget to.'),
    tile_id: zod.number().min(1).optional().describe('Existing dashboard tile to refresh.'),
    name: zod
        .string()
        .max(notebooksWidgetSnapshotPublishBodyNameMax)
        .default(notebooksWidgetSnapshotPublishBodyNameDefault)
        .describe('Title for a new dashboard widget.'),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksWidgetAttachBody = /* @__PURE__ */ zod.object({
    widget_id: zod.uuid().describe('Reusable widget to place in this notebook node.'),
    version_id: zod
        .uuid()
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
export const NotebooksWidgetCancelBody = /* @__PURE__ */ zod.object({
    generation_id: zod.uuid().describe('Generation job to cancel.'),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksWidgetForkBody = /* @__PURE__ */ zod.object({
    version_id: zod
        .uuid()
        .nullish()
        .describe("Immutable version to fork, or null to copy the placement's pinned or latest version."),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksWidgetGenerateBodyPromptMax = 50000

export const notebooksWidgetGenerateBodyModelDefault = `claude-sonnet-5`
export const notebooksWidgetGenerateBodyGenerationOperationDefault = `regenerate`

export const NotebooksWidgetGenerateBody = /* @__PURE__ */ zod.object({
    prompt: zod
        .string()
        .max(notebooksWidgetGenerateBodyPromptMax)
        .describe(
            'Instructions for the generated widget. Initial and improvement instructions accept up to 20,000 characters; regeneration accepts complete instructions up to 50,000 characters.'
        ),
    generation_id: zod.uuid().describe('Idempotency key for this generation job.'),
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
        .uuid()
        .optional()
        .describe('Current widget version the improvement is based on. Required for improve operations.'),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksWidgetPinBody = /* @__PURE__ */ zod.object({
    version_id: zod
        .uuid()
        .nullable()
        .describe("Immutable version to pin, or null to follow the reusable widget's latest version."),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksWidgetPublishBodyNameMax = 400

export const notebooksWidgetPublishBodyDescriptionMax = 2000

export const notebooksWidgetPublishBodyTagsItemMax = 50

export const notebooksWidgetPublishBodyTagsMax = 10

export const NotebooksWidgetPublishBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(notebooksWidgetPublishBodyNameMax).describe('Name shown in the reusable widget catalog.'),
    description: zod
        .string()
        .max(notebooksWidgetPublishBodyDescriptionMax)
        .optional()
        .describe('Short explanation of what the reusable widget shows and when to use it.'),
    tags: zod
        .array(zod.string().max(notebooksWidgetPublishBodyTagsItemMax))
        .max(notebooksWidgetPublishBodyTagsMax)
        .optional()
        .describe('Searchable labels attached to the reusable widget.'),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksWidgetRevertBody = /* @__PURE__ */ zod.object({
    version_id: zod.uuid().describe('Earlier version to restore as a new version.'),
    expected_current_version_id: zod.uuid().describe('Current version used for optimistic concurrency.'),
})
