/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const LlmPromptsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmPromptsListQueryContentDefault = `full`

export const LlmPromptsListQueryParams = /* @__PURE__ */ zod.object({
    content: zod
        .enum(['full', 'preview', 'none'])
        .default(llmPromptsListQueryContentDefault)
        .describe(
            "Controls how much prompt content is included in the response. 'full' includes the full prompt, 'preview' includes a short prompt_preview, and 'none' omits prompt content entirely. The outline field is always included.\n\n* `full` - full\n* `preview` - preview\n* `none` - none"
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('Optional substring filter applied to prompt names and prompt content.'),
})

export const LlmPromptsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmPromptsCreateBodyNameMax = 255

export const LlmPromptsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(llmPromptsCreateBodyNameMax)
        .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
})

export const llmPromptsNameRetrievePathPromptNameRegExp = new RegExp('^[^/]+$')

export const LlmPromptsNameRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    prompt_name: zod.string().regex(llmPromptsNameRetrievePathPromptNameRegExp),
})

export const llmPromptsNameRetrieveQueryContentDefault = `full`

export const LlmPromptsNameRetrieveQueryParams = /* @__PURE__ */ zod.object({
    content: zod
        .enum(['full', 'preview', 'none'])
        .default(llmPromptsNameRetrieveQueryContentDefault)
        .describe(
            "Controls how much prompt content is included in the response. 'full' includes the full prompt, 'preview' includes a short prompt_preview, and 'none' omits prompt content entirely. The outline field is always included.\n\n* `full` - full\n* `preview` - preview\n* `none` - none"
        ),
    version: zod
        .number()
        .min(1)
        .optional()
        .describe('Specific prompt version to fetch. If omitted, the latest version is returned.'),
})

export const llmPromptsNamePartialUpdatePathPromptNameRegExp = new RegExp('^[^/]+$')

export const LlmPromptsNamePartialUpdateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    prompt_name: zod.string().regex(llmPromptsNamePartialUpdatePathPromptNameRegExp),
})

export const LlmPromptsNamePartialUpdateBody = /* @__PURE__ */ zod.object({
    prompt: zod
        .unknown()
        .optional()
        .describe('Full prompt payload to publish as a new version. Mutually exclusive with edits.'),
    edits: zod
        .array(
            zod.object({
                old: zod.string().describe('Text to find in the current prompt. Must match exactly once.'),
                new: zod.string().describe('Replacement text.'),
            })
        )
        .optional()
        .describe(
            "List of find/replace operations to apply to the current prompt version. Each edit's 'old' text must match exactly once. Edits are applied sequentially. Mutually exclusive with prompt."
        ),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe('Latest version you are editing from. Used for optimistic concurrency checks.'),
})

export const llmPromptsNameDuplicateCreatePathPromptNameRegExp = new RegExp('^[^/]+$')

export const LlmPromptsNameDuplicateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    prompt_name: zod.string().regex(llmPromptsNameDuplicateCreatePathPromptNameRegExp),
})

export const llmPromptsNameDuplicateCreateBodyNewNameMax = 255

export const LlmPromptsNameDuplicateCreateBody = /* @__PURE__ */ zod.object({
    new_name: zod
        .string()
        .max(llmPromptsNameDuplicateCreateBodyNewNameMax)
        .describe(
            'Name for the duplicated prompt. Must be unique and use only letters, numbers, hyphens, and underscores.'
        ),
})
