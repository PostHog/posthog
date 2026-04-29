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

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksCreateBodyTitleMax = 256

export const notebooksCreateBodyVersionMin = -2147483648
export const notebooksCreateBodyVersionMax = 2147483647

export const NotebooksCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
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
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksUpdateBodyTitleMax = 256

export const notebooksUpdateBodyVersionMin = -2147483648
export const notebooksUpdateBodyVersionMax = 2147483647

export const NotebooksUpdateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksUpdateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
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
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksPartialUpdateBodyTitleMax = 256

export const notebooksPartialUpdateBodyVersionMin = -2147483648
export const notebooksPartialUpdateBodyVersionMax = 2147483647

export const NotebooksPartialUpdateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksPartialUpdateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
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
    _create_in_folder: zod.string().optional(),
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
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksHogqlExecuteCreateBodyTitleMax = 256

export const notebooksHogqlExecuteCreateBodyVersionMin = -2147483648
export const notebooksHogqlExecuteCreateBodyVersionMax = 2147483647

export const NotebooksHogqlExecuteCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksHogqlExecuteCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksHogqlExecuteCreateBodyVersionMin)
        .max(notebooksHogqlExecuteCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelConfigCreateBodyTitleMax = 256

export const notebooksKernelConfigCreateBodyVersionMin = -2147483648
export const notebooksKernelConfigCreateBodyVersionMax = 2147483647

export const NotebooksKernelConfigCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelConfigCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelConfigCreateBodyVersionMin)
        .max(notebooksKernelConfigCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelExecuteCreateBodyTitleMax = 256

export const notebooksKernelExecuteCreateBodyVersionMin = -2147483648
export const notebooksKernelExecuteCreateBodyVersionMax = 2147483647

export const NotebooksKernelExecuteCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelExecuteCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
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
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelExecuteStreamCreateBodyTitleMax = 256

export const notebooksKernelExecuteStreamCreateBodyVersionMin = -2147483648
export const notebooksKernelExecuteStreamCreateBodyVersionMax = 2147483647

export const NotebooksKernelExecuteStreamCreateBody = /* @__PURE__ */ zod.object({
    title: zod
        .string()
        .max(notebooksKernelExecuteStreamCreateBodyTitleMax)
        .nullish()
        .describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelExecuteStreamCreateBodyVersionMin)
        .max(notebooksKernelExecuteStreamCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelRestartCreateBodyTitleMax = 256

export const notebooksKernelRestartCreateBodyVersionMin = -2147483648
export const notebooksKernelRestartCreateBodyVersionMax = 2147483647

export const NotebooksKernelRestartCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelRestartCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
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
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelStartCreateBodyTitleMax = 256

export const notebooksKernelStartCreateBodyVersionMin = -2147483648
export const notebooksKernelStartCreateBodyVersionMax = 2147483647

export const NotebooksKernelStartCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelStartCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
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
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelStopCreateBodyTitleMax = 256

export const notebooksKernelStopCreateBodyVersionMin = -2147483648
export const notebooksKernelStopCreateBodyVersionMax = 2147483647

export const NotebooksKernelStopCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelStopCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
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
    _create_in_folder: zod.string().optional(),
})
