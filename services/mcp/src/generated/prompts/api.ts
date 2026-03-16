/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const LlmPromptsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmPromptsListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('Optional substring filter applied to prompt names and prompt content.'),
})

export const LlmPromptsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmPromptsCreateBodyNameMax = 255

export const LlmPromptsCreateBody = zod.object({
    name: zod
        .string()
        .max(llmPromptsCreateBodyNameMax)
        .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
})

export const llmPromptsNameRetrievePathPromptNameRegExp = new RegExp('^[^/]+$')

export const LlmPromptsNameRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    prompt_name: zod.string().regex(llmPromptsNameRetrievePathPromptNameRegExp),
})

export const LlmPromptsNameRetrieveQueryParams = zod.object({
    version: zod
        .number()
        .min(1)
        .optional()
        .describe('Specific prompt version to fetch. If omitted, the latest version is returned.'),
})

export const llmPromptsNamePartialUpdatePathPromptNameRegExp = new RegExp('^[^/]+$')

export const LlmPromptsNamePartialUpdateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    prompt_name: zod.string().regex(llmPromptsNamePartialUpdatePathPromptNameRegExp),
})

export const LlmPromptsNamePartialUpdateBody = zod.object({
    prompt: zod.unknown().optional().describe('Prompt payload to publish as a new version.'),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe('Latest version you are editing from. Used for optimistic concurrency checks.'),
})
